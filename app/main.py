
import json
import logging
import os
import threading
import time
from typing import Any

import boto3
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Inventory, ProcessedEvent
from app.schemas import (
    InventoryCreate,
    InventoryDecrease,
    InventoryResponse,
    InventoryUpdate,
)


app = FastAPI(
    title="E-Commerce Inventory Service",
    version="1.0.0",
)


AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL", "")

sqs_client = (
    boto3.client("sqs", region_name=AWS_REGION)
    if SQS_QUEUE_URL
    else None
)

logger = logging.getLogger(__name__)


# ============================================================
# DATABASE DEPENDENCY
# ============================================================

def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


# ============================================================
# HEALTH CHECK
# ============================================================

# ECS / Target Group health check
@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "inventory-service",
    }


@app.get("/ready")
def readiness_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {
            "status": "ready",
            "service": "inventory-service",
            "database": "ok",
        }
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        )

# ALB public health check
# ALB request:
# /inventory/health
#
# This route must be declared before:
# /inventory/{product_id}
#
# Otherwise "health" can be treated as product_id.
@app.get("/inventory/health")
def inventory_health_check():
    return {
        "status": "healthy",
        "service": "inventory-service",
    }


# ============================================================
# SQS CONSUMER STARTUP
# ============================================================

@app.on_event("startup")
def start_sqs_consumer():
    if not SQS_QUEUE_URL or not sqs_client:
        return

    thread = threading.Thread(
        target=consume_inventory_events,
        daemon=True,
    )

    thread.start()


# ============================================================
# EVENT MESSAGE PARSING
# ============================================================

def parse_event_message(body: str | None) -> dict[str, Any]:
    if not body:
        return {}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {}

    # Handle SNS -> SQS wrapped message
    if isinstance(payload, dict) and "Message" in payload:
        try:
            return json.loads(payload["Message"])
        except json.JSONDecodeError:
            return payload

    return payload if isinstance(payload, dict) else {}


# ============================================================
# ORDER CREATED EVENT PROCESSING
# ============================================================

def process_order_created_event(
    event_data: dict[str, Any],
    db: Session,
) -> bool:

    if event_data.get("event_type") != "ORDER_CREATED":
        raise ValueError("Unsupported inventory event type")

    event_id = event_data.get("event_id")
    order_id = event_data.get("order_id")
    product_id = event_data.get("product_id")
    quantity = event_data.get("quantity")

    if (
        event_id is None
        or order_id is None
        or product_id is None
        or quantity is None
    ):
        raise ValueError(
            "ORDER_CREATED event missing required fields"
        )

    if not isinstance(event_id, str) or not event_id:
        raise ValueError(
            "ORDER_CREATED event has an invalid event_id"
        )

    order_id_value = int(order_id)
    product_id_value = int(product_id)
    requested_quantity = int(quantity)

    try:
        inventory = (
            db.query(Inventory)
            .filter(
                Inventory.product_id == product_id_value
            )
            .with_for_update()
            .first()
        )

        if inventory is None:
            raise ValueError("Inventory not found")

        # Idempotency check
        processed_event = db.get(
            ProcessedEvent,
            event_id,
        )

        if processed_event is not None:
            db.commit()
            return False

        if inventory.quantity < requested_quantity:
            raise ValueError("Insufficient stock")

        inventory.quantity -= requested_quantity

        db.add(
            ProcessedEvent(
                event_id=event_id,
                event_type="ORDER_CREATED",
            )
        )

        db.commit()

        return True

    except IntegrityError:
        db.rollback()

        if db.get(
            ProcessedEvent,
            event_id,
        ) is not None:
            db.commit()
            return False

        raise

    except Exception:
        db.rollback()
        raise


# ============================================================
# SQS MESSAGE HANDLER
# ============================================================

def handle_sqs_message(
    message: dict[str, Any],
    db: Session,
    client: Any,
) -> None:

    receipt_handle = message.get("ReceiptHandle")

    event_data = parse_event_message(
        message.get("Body")
    )

    if not event_data:
        raise ValueError(
            "SQS message does not contain valid JSON"
        )

    process_order_created_event(
        event_data,
        db,
    )

    if not receipt_handle:
        raise ValueError(
            "SQS message is missing ReceiptHandle"
        )

    client.delete_message(
        QueueUrl=SQS_QUEUE_URL,
        ReceiptHandle=receipt_handle,
    )


# ============================================================
# SQS CONSUMER
# ============================================================

def consume_inventory_events():

    while True:

        if not sqs_client or not SQS_QUEUE_URL:
            time.sleep(10)
            continue

        try:
            response = sqs_client.receive_message(
                QueueUrl=SQS_QUEUE_URL,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=10,
                VisibilityTimeout=30,
            )

            messages = response.get(
                "Messages",
                [],
            )

            for message in messages:

                db = SessionLocal()

                try:
                    handle_sqs_message(
                        message,
                        db,
                        sqs_client,
                    )

                except Exception:
                    logger.exception(
                        "Inventory SQS message processing failed"
                    )

                finally:
                    db.close()

        except Exception:

            logger.exception(
                "Inventory SQS receive failed"
            )

            time.sleep(5)


# ============================================================
# CREATE INVENTORY
# ============================================================

@app.post(
    "/inventory",
    response_model=InventoryResponse,
)
def create_inventory(
    inventory: InventoryCreate,
    db: Session = Depends(get_db),
):

    existing_inventory = (
        db.query(Inventory)
        .filter(
            Inventory.product_id
            == inventory.product_id
        )
        .first()
    )

    if existing_inventory:
        raise HTTPException(
            status_code=400,
            detail="Inventory already exists for this product",
        )

    new_inventory = Inventory(
        product_id=inventory.product_id,
        quantity=inventory.quantity,
    )

    db.add(new_inventory)
    db.commit()
    db.refresh(new_inventory)

    return new_inventory


# ============================================================
# GET INVENTORY
# ============================================================

@app.get(
    "/inventory/{product_id}",
    response_model=InventoryResponse,
)
def get_inventory(
    product_id: int,
    db: Session = Depends(get_db),
):

    inventory = (
        db.query(Inventory)
        .filter(
            Inventory.product_id == product_id
        )
        .first()
    )

    if not inventory:
        raise HTTPException(
            status_code=404,
            detail="Inventory not found",
        )

    return inventory


# ============================================================
# UPDATE INVENTORY
# ============================================================

@app.put(
    "/inventory/{product_id}",
    response_model=InventoryResponse,
)
def update_inventory(
    product_id: int,
    inventory_data: InventoryUpdate,
    db: Session = Depends(get_db),
):

    inventory = (
        db.query(Inventory)
        .filter(
            Inventory.product_id == product_id
        )
        .first()
    )

    if not inventory:
        raise HTTPException(
            status_code=404,
            detail="Inventory not found",
        )

    inventory.quantity = inventory_data.quantity

    db.commit()
    db.refresh(inventory)

    return inventory


# ============================================================
# DECREASE INVENTORY
# ============================================================

@app.post(
    "/inventory/{product_id}/decrease",
    response_model=InventoryResponse,
)
def decrease_inventory(
    product_id: int,
    inventory_data: InventoryDecrease,
    db: Session = Depends(get_db),
):

    inventory = (
        db.query(Inventory)
        .filter(
            Inventory.product_id == product_id
        )
        .first()
    )

    if not inventory:
        raise HTTPException(
            status_code=404,
            detail="Inventory not found",
        )

    if inventory.quantity < inventory_data.quantity:
        raise HTTPException(
            status_code=400,
            detail="Insufficient stock",
        )

    inventory.quantity -= inventory_data.quantity

    db.commit()
    db.refresh(inventory)

    return inventory
