"""split service_venue item_category into service / venue_rental

客戶要求品項分類把「服務」跟「場租」分開，不要合在同一個 service_venue
裡——原本這兩種本來就是不同性質（服務是量INBODY/物理治療這種，場租是
真的租場地）。用品項名稱字串含不含「場租」兩個字判斷：含的歸類到
venue_rental，其餘留在 service（其他分類 membership/beverage/coaching/
custom 不受影響）。item_catalog_entries 跟 revenue_details 兩張表的
CHECK constraint 跟既有資料都要一起改。

Revision ID: 88c7e9d3097f
Revises: 9a5c9135e182
Create Date: 2026-09-27 00:05:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "88c7e9d3097f"
down_revision = "9a5c9135e182"
branch_labels = None
depends_on = None

NEW_CATEGORY_LIST = "'service', 'venue_rental', 'membership', 'beverage', 'coaching', 'custom'"
OLD_CATEGORY_LIST = "'service_venue', 'membership', 'beverage', 'coaching', 'custom'"
# CHECK constraint 不是 deferred，資料改分類前先放寬允許值，兩批都放得進去，
# 改完資料再收回成最終的分類清單（NEW_CATEGORY_LIST）。
TRANSITIONAL_CATEGORY_LIST = "'service_venue', 'service', 'venue_rental', 'membership', 'beverage', 'coaching', 'custom'"


def _reclassify(conn, table: str, name_column: str) -> None:
    conn.execute(
        sa.text(
            f"UPDATE {table} SET item_category = 'venue_rental' "
            f"WHERE item_category = 'service_venue' AND {name_column} LIKE '%場租%'"
        )
    )
    conn.execute(
        sa.text(
            f"UPDATE {table} SET item_category = 'service' "
            f"WHERE item_category = 'service_venue'"
        )
    )


def upgrade() -> None:
    conn = op.get_bind()

    with op.batch_alter_table("item_catalog_entries") as batch_op:
        batch_op.drop_constraint("ck_item_catalog_entries_category", type_="check")
        batch_op.create_check_constraint(
            "ck_item_catalog_entries_category", f"item_category IN ({TRANSITIONAL_CATEGORY_LIST})"
        )
    with op.batch_alter_table("revenue_details") as batch_op:
        batch_op.drop_constraint("ck_revenue_details_item_category", type_="check")
        batch_op.create_check_constraint(
            "ck_revenue_details_item_category", f"item_category IN ({TRANSITIONAL_CATEGORY_LIST})"
        )

    _reclassify(conn, "item_catalog_entries", "item_name")
    _reclassify(conn, "revenue_details", "item_name")

    with op.batch_alter_table("item_catalog_entries") as batch_op:
        batch_op.drop_constraint("ck_item_catalog_entries_category", type_="check")
        batch_op.create_check_constraint("ck_item_catalog_entries_category", f"item_category IN ({NEW_CATEGORY_LIST})")

    with op.batch_alter_table("revenue_details") as batch_op:
        batch_op.drop_constraint("ck_revenue_details_item_category", type_="check")
        batch_op.create_check_constraint("ck_revenue_details_item_category", f"item_category IN ({NEW_CATEGORY_LIST})")


def downgrade() -> None:
    conn = op.get_bind()

    with op.batch_alter_table("item_catalog_entries") as batch_op:
        batch_op.drop_constraint("ck_item_catalog_entries_category", type_="check")
        batch_op.create_check_constraint(
            "ck_item_catalog_entries_category", f"item_category IN ({TRANSITIONAL_CATEGORY_LIST})"
        )
    with op.batch_alter_table("revenue_details") as batch_op:
        batch_op.drop_constraint("ck_revenue_details_item_category", type_="check")
        batch_op.create_check_constraint(
            "ck_revenue_details_item_category", f"item_category IN ({TRANSITIONAL_CATEGORY_LIST})"
        )

    conn.execute(
        sa.text(
            "UPDATE item_catalog_entries SET item_category = 'service_venue' "
            "WHERE item_category IN ('service', 'venue_rental')"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE revenue_details SET item_category = 'service_venue' "
            "WHERE item_category IN ('service', 'venue_rental')"
        )
    )

    with op.batch_alter_table("item_catalog_entries") as batch_op:
        batch_op.drop_constraint("ck_item_catalog_entries_category", type_="check")
        batch_op.create_check_constraint("ck_item_catalog_entries_category", f"item_category IN ({OLD_CATEGORY_LIST})")

    with op.batch_alter_table("revenue_details") as batch_op:
        batch_op.drop_constraint("ck_revenue_details_item_category", type_="check")
        batch_op.create_check_constraint("ck_revenue_details_item_category", f"item_category IN ({OLD_CATEGORY_LIST})")
