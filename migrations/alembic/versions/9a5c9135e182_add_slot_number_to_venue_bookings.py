"""add slot_number to venue_bookings

場租教練總覽頁改成比照客戶原本紙本班表：欄位是「自由教練1/2/3」這種固定
共用檔期，不是綁死某一位場租教練專屬一欄——同一時段最多 3 組場租客人，
哪一組用哪個檔期跟教練是誰無關。這裡加 slot_number（1~3）記錄每筆預約
佔用哪個檔期，並用 partial unique index 擋掉同時段同檔期被約兩次。

既有資料用 (slot_date, slot_start_time) 分組、依 id 排序輪流補 1/2/3
（就只是給舊資料一個顯示用的檔期，不代表原本真的有這種區分）。

Revision ID: 9a5c9135e182
Revises: f3a9c1d2b6e4
Create Date: 2026-09-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "9a5c9135e182"
down_revision = "f3a9c1d2b6e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("venue_bookings", sa.Column("slot_number", sa.Integer(), nullable=True))

    conn = op.get_bind()
    # 分組輪流補 1/2/3：同一個 (slot_date, slot_start_time) 群組內依序遞增。
    grouped = conn.execute(
        sa.text("SELECT id, slot_date, slot_start_time FROM venue_bookings ORDER BY slot_date, slot_start_time, id")
    ).fetchall()
    group_counters = {}
    for row_id, slot_date, slot_start_time in grouped:
        key = (slot_date, slot_start_time)
        n = group_counters.get(key, 0)
        slot_number = (n % 3) + 1
        group_counters[key] = n + 1
        conn.execute(
            sa.text("UPDATE venue_bookings SET slot_number = :sn WHERE id = :id"),
            {"sn": slot_number, "id": row_id},
        )

    with op.batch_alter_table("venue_bookings") as batch_op:
        batch_op.alter_column("slot_number", nullable=False)
        batch_op.create_check_constraint(
            "ck_venue_bookings_slot_number",
            "slot_number IN (1, 2, 3)",
        )

    op.create_index(
        "ux_venue_bookings_slot_active",
        "venue_bookings",
        ["slot_date", "slot_start_time", "slot_number"],
        unique=True,
        postgresql_where=sa.text("status = 'booked'"),
        sqlite_where=sa.text("status = 'booked'"),
    )


def downgrade() -> None:
    op.drop_index("ux_venue_bookings_slot_active", table_name="venue_bookings")
    with op.batch_alter_table("venue_bookings") as batch_op:
        batch_op.drop_constraint("ck_venue_bookings_slot_number", type_="check")
        batch_op.drop_column("slot_number")
