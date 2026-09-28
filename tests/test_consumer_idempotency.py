import json

from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as inventory_main
from app.database import Base
from app.main import handle_sqs_message, process_order_created_event
from app.models import Inventory, ProcessedEvent


class FakeSQSClient:
    def __init__(self):
        self.deleted = []

    def delete_message(self, **kwargs):
        self.deleted.append(kwargs)


class FailingCommitSession(Session):
    def commit(self):
        raise RuntimeError("database commit failed")


def make_session_factory(session_class=Session):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, class_=session_class)


def add_inventory(session_factory, quantity=10):
    with session_factory() as db:
        db.add(Inventory(product_id=3, quantity=quantity))
        db.commit()


def order_event(event_id="event-1", quantity=2):
    return {
        "event_id": event_id,
        "event_type": "ORDER_CREATED",
        "order_id": 123,
        "product_id": 3,
        "quantity": quantity,
        "price": 100.0,
        "total_amount": 200.0,
        "status": "PENDING",
    }


def get_inventory(session_factory):
    with session_factory() as db:
        return db.scalar(select(Inventory).where(Inventory.product_id == 3))


def get_processed_event(session_factory, event_id):
    with session_factory() as db:
        return db.get(ProcessedEvent, event_id)


def test_event_id_decreases_inventory_once_and_duplicate_is_ignored():
    engine, session_factory = make_session_factory()
    add_inventory(session_factory)

    with session_factory() as db:
        assert process_order_created_event(order_event(), db) is True

    with session_factory() as db:
        assert process_order_created_event(order_event(), db) is False

    assert get_inventory(session_factory).quantity == 8
    assert get_processed_event(session_factory, "event-1") is not None
    engine.dispose()


def test_processed_event_event_id_is_unique():
    engine, session_factory = make_session_factory()
    with session_factory() as db:
        db.add(ProcessedEvent(event_id="event-1", event_type="ORDER_CREATED"))
        db.commit()
        db.add(ProcessedEvent(event_id="event-1", event_type="ORDER_CREATED"))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("duplicate event_id was accepted")
    engine.dispose()


def test_inventory_and_processed_event_roll_back_together_on_db_failure():
    engine, normal_session_factory = make_session_factory()
    add_inventory(normal_session_factory)
    session_factory = sessionmaker(bind=engine, class_=FailingCommitSession)

    with session_factory() as db:
        try:
            process_order_created_event(order_event(), db)
        except RuntimeError as error:
            assert str(error) == "database commit failed"
        else:
            raise AssertionError("database failure was not raised")

    assert get_inventory(normal_session_factory).quantity == 10
    assert get_processed_event(normal_session_factory, "event-1") is None
    engine.dispose()


def test_sqs_message_is_deleted_only_after_commit(monkeypatch):
    engine, session_factory = make_session_factory()
    add_inventory(session_factory)
    client = FakeSQSClient()
    monkeypatch.setattr(inventory_main, "SQS_QUEUE_URL", "queue-url")
    message = {
        "ReceiptHandle": "receipt-1",
        "Body": json.dumps(order_event("event-2")),
    }

    with session_factory() as db:
        handle_sqs_message(message, db, client)

    assert client.deleted == [
        {"QueueUrl": "queue-url", "ReceiptHandle": "receipt-1"}
    ]
    assert get_processed_event(session_factory, "event-2").event_id == "event-2"
    engine.dispose()


def test_sqs_message_is_not_deleted_when_db_commit_fails(monkeypatch):
    engine, normal_session_factory = make_session_factory()
    add_inventory(normal_session_factory)
    session_factory = sessionmaker(bind=engine, class_=FailingCommitSession)
    client = FakeSQSClient()
    monkeypatch.setattr(inventory_main, "SQS_QUEUE_URL", "queue-url")

    try:
        with session_factory() as db:
            handle_sqs_message(
                {
                    "ReceiptHandle": "receipt-db-failure",
                    "Body": json.dumps(order_event("event-db-failure")),
                },
                db,
                client,
            )
    except RuntimeError as error:
        assert str(error) == "database commit failed"
    else:
        raise AssertionError("database failure was not raised")

    assert client.deleted == []
    assert get_inventory(normal_session_factory).quantity == 10
    assert get_processed_event(normal_session_factory, "event-db-failure") is None
    engine.dispose()


def test_invalid_message_is_not_deleted(monkeypatch):
    engine, session_factory = make_session_factory()
    client = FakeSQSClient()
    monkeypatch.setattr(inventory_main, "SQS_QUEUE_URL", "queue-url")

    with session_factory() as db:
        try:
            handle_sqs_message(
                {"ReceiptHandle": "receipt-2", "Body": "{}"},
                db,
                client,
            )
        except ValueError as error:
            assert "required" in str(error) or "valid JSON" in str(error)
        else:
            raise AssertionError("invalid message was accepted")

    assert client.deleted == []
    engine.dispose()
