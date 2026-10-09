"""add cash reconciliation tables (app_settings, cash_movements, cash_closings)

班次交接現金對帳：cash_closings 存每次結帳的快照（期初、區間現金收款、異動、
應有、實點、差額），cash_movements 記抽屜現金的非銷售異動（零用金、退費、
代墊），app_settings 放每天固定留的零用金。都是新表，不動既有資料。

Revision ID: a7c3e9f10b42
Revises: dc3a00598277
Create Date: 2026-10-10 02:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "a7c3e9f10b42"
down_revision = "dc3a00598277"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "cash_movements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("movement_type", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("counterparty", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("entered_by_id", sa.Integer(), nullable=False),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_by_id", sa.Integer(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "movement_type IN ('petty_cash', 'refund', 'coach_advance', 'advance_return')",
            name="ck_cash_movements_type",
        ),
        sa.CheckConstraint("direction IN ('in', 'out')", name="ck_cash_movements_direction"),
        sa.CheckConstraint("amount > 0", name="ck_cash_movements_amount_positive"),
        sa.ForeignKeyConstraint(["entered_by_id"], ["admin_users.id"]),
        sa.ForeignKeyConstraint(["voided_by_id"], ["admin_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cash_movements_created_at", "cash_movements", ["created_at"])

    op.create_table(
        "cash_closings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("shift", sa.String(), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opening_cash", sa.Numeric(10, 2), nullable=False),
        sa.Column("cash_sales", sa.Numeric(10, 2), nullable=False),
        sa.Column("movements_in", sa.Numeric(10, 2), nullable=False),
        sa.Column("movements_out", sa.Numeric(10, 2), nullable=False),
        sa.Column("expected_cash", sa.Numeric(10, 2), nullable=False),
        sa.Column("counted_cash", sa.Numeric(10, 2), nullable=False),
        sa.Column("denominations", sa.JSON(), nullable=False),
        sa.Column("variance", sa.Numeric(10, 2), nullable=False),
        sa.Column("collected_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("remaining_cash", sa.Numeric(10, 2), nullable=False),
        sa.Column("cash_float_snapshot", sa.Numeric(10, 2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("closed_by_id", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_by_id", sa.Integer(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("shift IN ('morning', 'afternoon', 'evening')", name="ck_cash_closings_shift"),
        sa.CheckConstraint("counted_cash >= 0", name="ck_cash_closings_counted_nonnegative"),
        sa.CheckConstraint("collected_amount >= 0", name="ck_cash_closings_collected_nonnegative"),
        sa.ForeignKeyConstraint(["closed_by_id"], ["admin_users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["admin_users.id"]),
        sa.ForeignKeyConstraint(["voided_by_id"], ["admin_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_cash_closings_date_shift_active",
        "cash_closings",
        ["business_date", "shift"],
        unique=True,
        postgresql_where=sa.text("voided_at IS NULL"),
        sqlite_where=sa.text("voided_at IS NULL"),
    )
    # 對帳區間用 created_at 篩營收流水帳，補一個 index 避免之後資料變多變慢
    op.create_index("ix_revenue_details_created_at", "revenue_details", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_revenue_details_created_at", table_name="revenue_details")
    op.drop_index(
        "ux_cash_closings_date_shift_active",
        table_name="cash_closings",
        postgresql_where=sa.text("voided_at IS NULL"),
        sqlite_where=sa.text("voided_at IS NULL"),
    )
    op.drop_table("cash_closings")
    op.drop_index("ix_cash_movements_created_at", table_name="cash_movements")
    op.drop_table("cash_movements")
    op.drop_table("app_settings")
