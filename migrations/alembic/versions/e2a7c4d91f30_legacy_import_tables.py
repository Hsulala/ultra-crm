"""legacy import: contract_sessions table + import_batch / note columns

匯入客戶舊 Google Sheets（課堂報表、銷售總表）用。只新增，不改既有欄位：
- contract_sessions：每一堂的上課日期（課堂報表 H～AF 欄），原本系統只有
  contracts.used_sessions 一個數字，沒有地方放「哪天上了第幾堂」。
- contracts.note：原表上「已退費」「換約」「原表單價：5000振興」這類文字。
- import_batch：members／contracts／revenue_details／venue_rental_coaches 標記
  是哪一批匯入的，要整批撤回時可以只刪這一批，不動店家自己新增的資料。
- revenue_details.customer_name／coach_name：銷售總表的「姓名」「教練」原文
  （場租教練不在 members 表，coach_id 放不進去）。

Revision ID: e2a7c4d91f30
Revises: b4d8f2a61c07
Create Date: 2026-10-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2a7c4d91f30"
down_revision: Union[str, None] = "b4d8f2a61c07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contract_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("contracts.id"), nullable=False),
        sa.Column("session_no", sa.Integer(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=True),
        sa.Column("raw_value", sa.String(), nullable=True),
        sa.Column("import_batch", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_contract_sessions_contract_id", "contract_sessions", ["contract_id"])
    op.create_index("ix_contract_sessions_session_date", "contract_sessions", ["session_date"])

    op.add_column("contracts", sa.Column("note", sa.Text(), nullable=True))
    for table in ("members", "contracts", "revenue_details", "venue_rental_coaches"):
        op.add_column(table, sa.Column("import_batch", sa.String(), nullable=True))
    op.add_column("revenue_details", sa.Column("customer_name", sa.String(), nullable=True))
    op.add_column("revenue_details", sa.Column("coach_name", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("revenue_details") as batch:
        batch.drop_column("coach_name")
        batch.drop_column("customer_name")
    for table in ("venue_rental_coaches", "revenue_details", "contracts", "members"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("import_batch")
    with op.batch_alter_table("contracts") as batch:
        batch.drop_column("note")
    op.drop_index("ix_contract_sessions_session_date", table_name="contract_sessions")
    op.drop_index("ix_contract_sessions_contract_id", table_name="contract_sessions")
    op.drop_table("contract_sessions")
