"""venue_bookings.area is always strength

場租教練租的是一樓重訓區場地，跟二樓皮拉提斯（器械床位、有獨立名額上限）
是完全不同的空間——場租教練本來就不該能選皮拉提斯，之前開放挑 area 是
設計錯誤，這裡收回來，順便把可能存在的舊 'pilates' 資料轉正（目前這個
功能才剛上線，預期不會有真的資料，只是防呆）。

Revision ID: d25bdd21cc9d
Revises: 88c7e9d3097f
Create Date: 2026-09-27 00:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "d25bdd21cc9d"
down_revision = "88c7e9d3097f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE venue_bookings SET area = 'strength' WHERE area = 'pilates'"))

    with op.batch_alter_table("venue_bookings") as batch_op:
        batch_op.drop_constraint("ck_venue_bookings_area", type_="check")
        batch_op.create_check_constraint("ck_venue_bookings_area", "area = 'strength'")


def downgrade() -> None:
    with op.batch_alter_table("venue_bookings") as batch_op:
        batch_op.drop_constraint("ck_venue_bookings_area", type_="check")
        batch_op.create_check_constraint("ck_venue_bookings_area", "area IN ('strength', 'pilates')")
