"""drop venue_bookings single-slot uniqueness

場租教練同一個時段可以同時接多組客人，不像一般教練綁死一對一/一對二，
所以移除這個原本誤加的「同時段只能一筆」限制。

Revision ID: 65ed456087fc
Revises: 135f5cc8a7de
Create Date: 2026-09-26 00:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "65ed456087fc"
down_revision = "135f5cc8a7de"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ux_venue_bookings_coach_slot_active", table_name="venue_bookings")


def downgrade() -> None:
    op.create_index(
        "ux_venue_bookings_coach_slot_active",
        "venue_bookings",
        ["venue_coach_id", "slot_date", "slot_start_time"],
        unique=True,
        postgresql_where="status = 'booked'",
        sqlite_where="status = 'booked'",
    )
