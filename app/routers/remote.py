"""遠端管理介面：給店家總覽（beauty-crm）呼叫，格式與禾域、妍序、戀鳳爪、麻辣醬一致。

    GET /api/remote/stats?month=YYYY-MM   本月課程預約、場租預約、新合約、營收
    GET /api/remote/config                功能模組狀態（目前沒有可遠端開關的模組）
    GET /api/remote/backup                下載整份資料備份（需寫入金鑰）

金鑰：REMOTE_READ_KEY（讀）、REMOTE_WRITE_KEY（寫，也能讀），各至少 32 字元；
都沒設定時整組介面回 404。這組介面只讀資料，不改任何東西；店家後台登入不能用在這裡。
"""

import base64
import hashlib
import hmac
import os
import time as time_module
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Optional

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.models.booking import Booking
from app.models.contract import Contract
from app.models.revenue_detail import RevenueDetail
from app.models.venue_booking import VenueBooking

router = APIRouter(prefix="/api/remote", tags=["remote"])
log = logging.getLogger("remote")

SYSTEM = "gym"  # 會員場館型：店家總覽依此顯示課程預約、新合約與營收
MIN_KEY_LENGTH = 32
TAIPEI = timezone(timedelta(hours=8))
_fails: dict[str, list[float]] = {}  # ip → 失敗時間


def _good(key: Optional[str]) -> bool:
    return isinstance(key, str) and len(key) >= MIN_KEY_LENGTH


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(hashlib.sha256(a.encode()).digest(), hashlib.sha256(b.encode()).digest())


class RemoteError(Exception):
    """這組介面的錯誤一律回 {"error": "..."}（跟其他店家一致），不把細節（SQL、路徑）給呼叫端。"""

    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message


async def remote_error_handler(_request: Request, exc: RemoteError):
    return JSONResponse({"error": exc.message}, status_code=exc.status)


def _error(status: int, message: str):
    raise RemoteError(status, message)


def remote_role(request: Request) -> str:
    # 每次都讀環境變數，Railway 換金鑰重新部署後立刻生效；測試也能直接改。
    read, write = os.environ.get("REMOTE_READ_KEY"), os.environ.get("REMOTE_WRITE_KEY")
    if not _good(read) and not _good(write):
        _error(404, "找不到這個功能")
    ip = request.client.host if request.client else "?"
    now = time_module.time()
    if len(_fails) > 1000:
        _fails.clear()
    recent = [t for t in _fails.get(ip, []) if now - t < 300]
    _fails[ip] = recent
    if len(recent) >= 10:
        _error(429, "嘗試次數過多，請 5 分鐘後再試")
    header = request.headers.get("authorization", "")
    token = header[7:] if header.startswith("Bearer ") and " " not in header[7:] else None
    role = None
    if token:
        if _good(write) and _same(token, write):
            role = "write"
        elif _good(read) and _same(token, read):
            role = "read"
    if not role:
        recent.append(now)
        _error(401, "金鑰不正確")
    return role


def _taipei_month() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m")


def _month_range(month: str) -> tuple[date, date]:
    y, m = int(month[:4]), int(month[5:7])
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    return start, end


@router.get("/stats")
def stats(month: Optional[str] = None, role: str = Depends(remote_role), db: Session = Depends(get_db)):
    month = month or _taipei_month()
    if len(month) != 7 or month[4] != "-" or not (month[:4].isdigit() and month[5:].isdigit()) or not 1 <= int(month[5:]) <= 12:
        _error(400, "月份格式不正確")
    start, end = _month_range(month)
    try:
        return _stats(db, month, start, end)
    except Exception as exc:  # noqa: BLE001
        log.error("[remote] 統計錯誤：%s", exc)
        _error(500, "店家系統發生錯誤")


def _stats(db: Session, month: str, start: date, end: date):
    def count_by_status(model):
        rows = db.execute(
            select(model.status, func.count())
            .where(model.slot_date >= start, model.slot_date < end)
            .group_by(model.status)
        ).all()
        counts = {status: n for status, n in rows}
        cancelled = counts.get("cancelled", 0)
        return sum(counts.values()) - cancelled, cancelled

    course_total, course_cancelled = count_by_status(Booking)
    venue_total, venue_cancelled = count_by_status(VenueBooking)
    new_contracts = db.scalar(
        select(func.count()).select_from(Contract).where(Contract.purchase_date >= start, Contract.purchase_date < end)
    ) or 0
    revenue = db.scalar(
        select(func.coalesce(func.sum(RevenueDetail.amount), 0)).where(
            RevenueDetail.entry_date >= start, RevenueDetail.entry_date < end
        )
    ) or 0
    # bookings 沿用總覽既有格式（主要數字＝課程預約）；gym 是這一型專用的完整數字
    return {
        "system": SYSTEM,
        "month": month,
        "bookings": {"total": course_total, "cancelled": course_cancelled},
        "gym": {
            "courseBookings": course_total,
            "courseCancelled": course_cancelled,
            "venueBookings": venue_total,
            "venueCancelled": venue_cancelled,
            "newContracts": int(new_contracts),
            "revenue": float(revenue),
        },
    }


@router.get("/config")
def config(role: str = Depends(remote_role)):
    return {"system": SYSTEM, "modules": {}}


def _plain(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"base64": base64.b64encode(bytes(value)).decode()}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    return value


@router.get("/backup")
def backup(role: str = Depends(remote_role), db: Session = Depends(get_db)):
    """每張資料表原樣輸出（只讀），出問題時才能還原。內容含會員個資與帳號資料，所以只有寫入金鑰可以下載。"""
    if role != "write":
        _error(403, "下載備份需要寫入金鑰")
    try:
        tables = _dump_tables(db)
    except Exception as exc:  # noqa: BLE001
        log.error("[remote] 備份錯誤：%s", exc)
        _error(500, "店家系統發生錯誤")
    return JSONResponse(
        {"system": SYSTEM, "exportedAt": datetime.now(timezone.utc).isoformat(), "tables": tables},
        headers={"Cache-Control": "no-store"},
    )


def _dump_tables(db: Session) -> dict:
    tables = {}
    for name in sorted(inspect(engine).get_table_names()):
        quoted = '"' + name.replace('"', '""') + '"'
        result = db.execute(text(f"SELECT * FROM {quoted}"))
        tables[name] = [{key: _plain(value) for key, value in row._mapping.items()} for row in result]
    return tables
