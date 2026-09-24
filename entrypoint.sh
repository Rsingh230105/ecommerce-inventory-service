#!/bin/sh

echo "Running database migrations..."

alembic upgrade head

if [ $? -ne 0 ]; then
    echo "Database migration failed. Stopping container."
    exit 1
fi

echo "Database migrations completed successfully."

echo "Starting Inventory Service..."

exec uvicorn app.main:app --host 0.0.0.0 --port 8002