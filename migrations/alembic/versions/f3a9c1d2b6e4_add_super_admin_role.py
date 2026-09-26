"""add super_admin role to admin_users check constraint

新增超級管理者角色——高於店長，可以管理後台帳號。

Revision ID: f3a9c1d2b6e4
Revises: 65ed456087fc
Create Date: 2026-09-26 00:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f3a9c1d2b6e4"
down_revision = "65ed456087fc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("admin_users") as batch_op:
        batch_op.drop_constraint("ck_admin_users_role", type_="check")
        batch_op.create_check_constraint(
            "ck_admin_users_role",
            "role IN ('super_admin', 'manager', 'front_desk', 'coach')",
        )


def downgrade() -> None:
    with op.batch_alter_table("admin_users") as batch_op:
        batch_op.drop_constraint("ck_admin_users_role", type_="check")
        batch_op.create_check_constraint(
            "ck_admin_users_role",
            "role IN ('manager', 'front_desk', 'coach')",
        )
