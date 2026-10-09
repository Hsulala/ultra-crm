"""add remittance_last5 to revenue_details

Revision ID: b4d8f2a61c07
Revises: a7c3e9f10b42
Create Date: 2026-10-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4d8f2a61c07"
down_revision: Union[str, None] = "a7c3e9f10b42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("revenue_details", sa.Column("remittance_last5", sa.String(length=5), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("revenue_details") as batch:
        batch.drop_column("remittance_last5")
