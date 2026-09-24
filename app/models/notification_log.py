from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class NotificationLog(Base):
    """到期前一個月提醒等推播的寄送紀錄，防止夜間排程重複發送。"""

    __tablename__ = "notification_logs"
    __table_args__ = (
        Index(
            "ux_notification_logs_dedup",
            "member_id",
            "notif_type",
            "contract_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    notif_type: Mapped[str] = mapped_column(String, nullable=False)
    contract_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contracts.id"), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
