"""allow venue coaches to hold pilates contracts/bookings

客戶「課堂報表」合約資料(皮拉提斯)分頁教練欄同時有店內正職（YOKO）跟場租
教練（ELSA），代表皮拉提斯合約本來就可能是場租教練開的，不是只有店內
正職——重訓合約才維持只能是店內正職。contracts / bookings 兩張表都加
venue_coach_id，跟原本的 coach_id 兩者恰好擇一。

Revision ID: dc3a00598277
Revises: d25bdd21cc9d
Create Date: 2026-09-27 00:15:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "dc3a00598277"
down_revision = "d25bdd21cc9d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("contracts") as batch_op:
        batch_op.add_column(sa.Column("venue_coach_id", sa.Integer(), nullable=True))
        batch_op.alter_column("coach_id", existing_type=sa.Integer(), nullable=True)
        batch_op.create_foreign_key(
            "fk_contracts_venue_coach_id", "venue_rental_coaches", ["venue_coach_id"], ["id"]
        )
        batch_op.create_check_constraint(
            "ck_contracts_coach_xor_venue_coach",
            "(coach_id IS NOT NULL AND venue_coach_id IS NULL) OR (coach_id IS NULL AND venue_coach_id IS NOT NULL)",
        )

    with op.batch_alter_table("bookings") as batch_op:
        batch_op.add_column(sa.Column("venue_coach_id", sa.Integer(), nullable=True))
        batch_op.alter_column("coach_id", existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column("created_by_id", existing_type=sa.Integer(), nullable=True)
        batch_op.create_foreign_key(
            "fk_bookings_venue_coach_id", "venue_rental_coaches", ["venue_coach_id"], ["id"]
        )
        batch_op.create_check_constraint(
            "ck_bookings_coach_xor_venue_coach",
            "(coach_id IS NOT NULL AND venue_coach_id IS NULL) OR (coach_id IS NULL AND venue_coach_id IS NOT NULL)",
        )
        batch_op.drop_index("ux_bookings_coach_slot_active")
        batch_op.create_index(
            "ux_bookings_coach_slot_active",
            ["coach_id", "slot_date", "slot_start_time"],
            unique=True,
            postgresql_where=sa.text("status = 'booked' AND coach_id IS NOT NULL"),
            sqlite_where=sa.text("status = 'booked' AND coach_id IS NOT NULL"),
        )
        batch_op.create_index(
            "ux_bookings_venue_coach_slot_active",
            ["venue_coach_id", "slot_date", "slot_start_time"],
            unique=True,
            postgresql_where=sa.text("status = 'booked' AND venue_coach_id IS NOT NULL"),
            sqlite_where=sa.text("status = 'booked' AND venue_coach_id IS NOT NULL"),
        )


def downgrade() -> None:
    with op.batch_alter_table("bookings") as batch_op:
        batch_op.drop_index("ux_bookings_venue_coach_slot_active")
        batch_op.drop_index("ux_bookings_coach_slot_active")
        batch_op.create_index(
            "ux_bookings_coach_slot_active",
            ["coach_id", "slot_date", "slot_start_time"],
            unique=True,
            postgresql_where=sa.text("status = 'booked'"),
            sqlite_where=sa.text("status = 'booked'"),
        )
        batch_op.drop_constraint("ck_bookings_coach_xor_venue_coach", type_="check")
        batch_op.drop_constraint("fk_bookings_venue_coach_id", type_="foreignkey")
        batch_op.alter_column("coach_id", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("created_by_id", existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column("venue_coach_id")

    with op.batch_alter_table("contracts") as batch_op:
        batch_op.drop_constraint("ck_contracts_coach_xor_venue_coach", type_="check")
        batch_op.drop_constraint("fk_contracts_venue_coach_id", type_="foreignkey")
        batch_op.alter_column("coach_id", existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column("venue_coach_id")
