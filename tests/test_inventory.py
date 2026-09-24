from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.main import app, get_db


client = TestClient(app)


def override_get_db():
    db = MagicMock()

    inventory_data = {
        3: SimpleNamespace(
            id=1,
            product_id=3,
            quantity=10
        )
    }

    def query(model):
        query_mock = MagicMock()

        def filter_result(*args, **kwargs):
            filter_mock = MagicMock()

            def first():
                return inventory_data.get(3)

            filter_mock.first = first
            return filter_mock

        query_mock.filter = filter_result
        return query_mock

    db.query = query
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()

    def refresh(obj):
        obj.id = 1

    db.refresh.side_effect = refresh

    return db


app.dependency_overrides[get_db] = override_get_db


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "inventory-service"
    }


def test_get_inventory():
    response = client.get("/inventory/3")

    assert response.status_code == 200
    assert response.json()["product_id"] == 3
    assert response.json()["quantity"] == 10


def test_update_inventory():
    response = client.put(
        "/inventory/3",
        json={"quantity": 8}
    )

    assert response.status_code == 200
    
def test_decrease_inventory():
    response = client.post(
        "/inventory/3/decrease",
        json={"quantity": 2}
    )

    assert response.status_code == 200
    
def test_insufficient_stock():
    response = client.post(
        "/inventory/3/decrease",
        json={"quantity": 20}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Insufficient stock"