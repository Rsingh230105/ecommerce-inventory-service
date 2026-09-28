"""add inventory quantity constraint

Revision ID: 0c227cc4a67a
Revises: 9089013604c4
Create Date: 2026-09-25 12:26:06.924662

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0c227cc4a67a"
down_revision: Union[str, Sequence[str], None] = "9089013604c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add a database-level protection against negative inventory."""
    op.create_check_constraint(
        "check_inventory_quantity_non_negative",
        "inventory",
        "quantity >= 0",
    )


def downgrade() -> None:
    """Remove the inventory quantity constraint."""
    op.drop_constraint(
        "check_inventory_quantity_non_negative",
        "inventory",
        type_="check",
    )