from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Inventory
from app.schemas import (
    InventoryCreate,
    InventoryDecrease,
    InventoryResponse,
    InventoryUpdate,
)

app = FastAPI(
    title="E-Commerce Inventory Service",
    version="1.0.0"
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "inventory-service"
    }


@app.post("/inventory", response_model=InventoryResponse)
def create_inventory(
    inventory: InventoryCreate,
    db: Session = Depends(get_db)
):
    existing_inventory = (
        db.query(Inventory)
        .filter(Inventory.product_id == inventory.product_id)
        .first()
    )

    if existing_inventory:
        raise HTTPException(
            status_code=400,
            detail="Inventory already exists for this product"
        )

    new_inventory = Inventory(
        product_id=inventory.product_id,
        quantity=inventory.quantity
    )

    db.add(new_inventory)
    db.commit()
    db.refresh(new_inventory)

    return new_inventory


@app.get("/inventory/{product_id}", response_model=InventoryResponse)
def get_inventory(
    product_id: int,
    db: Session = Depends(get_db)
):
    inventory = (
        db.query(Inventory)
        .filter(Inventory.product_id == product_id)
        .first()
    )

    if not inventory:
        raise HTTPException(
            status_code=404,
            detail="Inventory not found"
        )

    return inventory


@app.put("/inventory/{product_id}", response_model=InventoryResponse)
def update_inventory(
    product_id: int,
    inventory_data: InventoryUpdate,
    db: Session = Depends(get_db)
):
    inventory = (
        db.query(Inventory)
        .filter(Inventory.product_id == product_id)
        .first()
    )

    if not inventory:
        raise HTTPException(
            status_code=404,
            detail="Inventory not found"
        )

    inventory.quantity = inventory_data.quantity

    db.commit()
    db.refresh(inventory)

    return inventory


@app.post("/inventory/{product_id}/decrease", response_model=InventoryResponse)
def decrease_inventory(
    product_id: int,
    inventory_data: InventoryDecrease,
    db: Session = Depends(get_db)
):
    inventory = (
        db.query(Inventory)
        .filter(Inventory.product_id == product_id)
        .first()
    )

    if not inventory:
        raise HTTPException(
            status_code=404,
            detail="Inventory not found"
        )

    if inventory.quantity < inventory_data.quantity:
        raise HTTPException(
            status_code=400,
            detail="Insufficient stock"
        )

    inventory.quantity -= inventory_data.quantity

    db.commit()
    db.refresh(inventory)

    return inventory