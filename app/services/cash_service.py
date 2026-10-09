"""班次交接現金對帳。

核心想法：每次結帳都是下一次的起點（鏈）。
    應有現金 = 期初現金 + 區間內現金收款 + 現金收入異動 − 現金支出異動
    差額     = 實點 − 應有
哪一段時間少錢、少多少，一定落在某一次結帳的區間裡；再配合結帳不能修改、異動只能作廢
（留下原因）、事後帳目被動過會跟快照比對出來，就能追到「是哪個班、哪一段、為什麼」。

區間用資料的 created_at（系統寫入時間）切，而不是 entry_date（業務日期）：抽屜裡的
現金是照實際收錢的順序進出，補登的帳要算在「補登的那一刻」才對得上抽屜。補登的收款
會在明細裡被標示出來。
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AdminUser, AppSetting, CashClosing, CashMovement, Member, RevenueDetail, VenueRentalCoach
from app.models.cash import MOVEMENT_DIRECTIONS, MOVEMENT_TYPE_LABELS
from app.models.schedule import SHIFT_LABELS

TAIPEI = timezone(timedelta(hours=8))  # 台灣沒有日光節約時間，固定 +8 就好，不用依賴系統時區資料庫
CENT = Decimal("0.01")

FLOAT_KEY = "cash_float"
SHIFT_ORDER = ("morning", "afternoon", "evening")
SHIFT_END_HOUR = {"morning": 13, "afternoon": 18, "evening": 22}

# 面額（台幣）。伺服器自己用「面額 × 張數」算實點金額，不信任前端傳來的合計
DENOMINATIONS = (2000, 1000, 500, 200, 100, 50, 10, 5, 1)
MAX_COUNT_PER_DENOMINATION = 100000

# 付款方式 = 這些（去空白、不分大小寫）才算現金；其他非標準寫法會在明細裡提醒
CASH_METHOD_ALIASES = ("現金", "cash")
STANDARD_PAYMENT_METHODS = ("現金", "匯款", "信用卡", "linepay")


class CashError(ValueError):
    """可以直接顯示給使用者看的業務錯誤訊息。"""


# ---------- 基本工具 ----------


def money(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0)).quantize(CENT)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite 讀出來是 naive（存的就是 UTC），Postgres 是 aware，統一成 aware UTC。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_taipei(dt: Optional[datetime]) -> Optional[datetime]:
    return as_utc(dt).astimezone(TAIPEI) if dt else None


def taipei_today() -> date:
    return datetime.now(TAIPEI).date()


def current_shift(now: Optional[datetime] = None) -> str:
    hour = (now or datetime.now(TAIPEI)).astimezone(TAIPEI).hour
    if hour < SHIFT_END_HOUR["morning"]:
        return "morning"
    if hour < SHIFT_END_HOUR["afternoon"]:
        return "afternoon"
    return "evening"


def day_start_utc(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=TAIPEI).astimezone(timezone.utc)


# ---------- 設定：每天固定留的零用金 ----------


def get_cash_float(db: Session) -> Optional[Decimal]:
    row = db.get(AppSetting, FLOAT_KEY)
    return money(row.value) if row else None


def set_cash_float(db: Session, amount: Any) -> Decimal:
    value = money(amount)
    if value < 0:
        raise CashError("固定零用金不能是負數")
    row = db.get(AppSetting, FLOAT_KEY)
    if row:
        row.value = str(value)
        row.updated_at = now_utc()
    else:
        db.add(AppSetting(key=FLOAT_KEY, value=str(value)))
    db.commit()
    return value


# ---------- 區間與金額計算 ----------


def _is_cash_payment():
    return func.lower(func.trim(RevenueDetail.payment_method)).in_(CASH_METHOD_ALIASES)


def latest_active_closing(db: Session) -> Optional[CashClosing]:
    return (
        db.query(CashClosing)
        .filter(CashClosing.voided_at.is_(None))
        .order_by(CashClosing.closed_at.desc(), CashClosing.id.desc())
        .first()
    )


def get_open_interval(db: Session, business_date: date) -> Tuple[datetime, Decimal]:
    """目前這一段的起點與期初現金。有上一筆有效結帳就接在它後面；
    整個系統第一次結帳則從結帳那天 00:00 起算，期初 = 固定零用金。"""
    prev = latest_active_closing(db)
    if prev:
        return as_utc(prev.closed_at), money(prev.remaining_cash)
    flt = get_cash_float(db)
    if flt is None:
        raise CashError("請店長先在「對帳」頁設定每天固定留在抽屜的零用金，才能開始結帳")
    return day_start_utc(business_date), flt


def cash_sale_entries(db: Session, start: datetime, end: datetime) -> List[RevenueDetail]:
    return (
        db.query(RevenueDetail)
        .filter(RevenueDetail.created_at > start, RevenueDetail.created_at <= end, _is_cash_payment())
        .order_by(RevenueDetail.created_at, RevenueDetail.id)
        .all()
    )


def sum_cash_sales(db: Session, start: datetime, end: datetime) -> Decimal:
    total = (
        db.query(func.coalesce(func.sum(RevenueDetail.amount), 0))
        .filter(RevenueDetail.created_at > start, RevenueDetail.created_at <= end, _is_cash_payment())
        .scalar()
    )
    return money(total)


def movement_totals(db: Session, start: datetime, end: datetime) -> Tuple[Decimal, Decimal]:
    """(現金收入異動合計, 現金支出異動合計)，不含已作廢的。"""
    rows = (
        db.query(CashMovement.direction, func.coalesce(func.sum(CashMovement.amount), 0))
        .filter(
            CashMovement.created_at > start,
            CashMovement.created_at <= end,
            CashMovement.voided_at.is_(None),
        )
        .group_by(CashMovement.direction)
        .all()
    )
    totals = {direction: money(total) for direction, total in rows}
    return totals.get("in", Decimal("0.00")), totals.get("out", Decimal("0.00"))


# ---------- 結帳 ----------


def parse_denominations(raw: Optional[Dict[str, Any]]) -> Tuple[Dict[str, int], Decimal]:
    allowed = {str(d) for d in DENOMINATIONS}
    clean: Dict[str, int] = {}
    total = 0
    for key, count in (raw or {}).items():
        key = str(key)
        if key not in allowed:
            raise CashError(f"不支援的面額：{key}")
        if isinstance(count, bool) or (isinstance(count, float) and not count.is_integer()):
            raise CashError("張數必須是整數")
        try:
            n = int(count)
        except (TypeError, ValueError):
            raise CashError("張數必須是整數")
        if n < 0 or n > MAX_COUNT_PER_DENOMINATION:
            raise CashError("張數必須介於 0 到 100000")
        if n:
            clean[key] = n
            total += int(key) * n
    return clean, Decimal(total).quantize(CENT)


def create_closing(
    db: Session,
    *,
    business_date: date,
    shift: str,
    denominations: Optional[Dict[str, Any]],
    collected_amount: Any,
    note: Optional[str],
    closed_by_id: int,
) -> CashClosing:
    if shift not in SHIFT_LABELS:
        raise CashError("班次不正確")
    if business_date > taipei_today():
        raise CashError("不能替未來的日期結帳")

    counted_map, counted = parse_denominations(denominations)
    collected = money(collected_amount)
    if collected < 0:
        raise CashError("收走金額不能是負數")
    if collected > counted:
        raise CashError("收走金額不能大於實點金額")

    already = (
        db.query(CashClosing.id)
        .filter(
            CashClosing.business_date == business_date,
            CashClosing.shift == shift,
            CashClosing.voided_at.is_(None),
        )
        .first()
    )
    if already:
        raise CashError("這個班次已經結過帳了；如果點錯，請店長作廢後重新結帳")

    closed_at = now_utc()
    start, opening = get_open_interval(db, business_date)
    cash_sales = sum_cash_sales(db, start, closed_at)
    m_in, m_out = movement_totals(db, start, closed_at)
    expected = opening + cash_sales + m_in - m_out
    flt = get_cash_float(db)

    closing = CashClosing(
        business_date=business_date,
        shift=shift,
        interval_start=start,
        closed_at=closed_at,
        opening_cash=opening,
        cash_sales=cash_sales,
        movements_in=m_in,
        movements_out=m_out,
        expected_cash=expected,
        counted_cash=counted,
        denominations=counted_map,
        variance=counted - expected,
        collected_amount=collected,
        remaining_cash=counted - collected,
        cash_float_snapshot=flt if flt is not None else Decimal("0.00"),
        note=(note or "").strip() or None,
        closed_by_id=closed_by_id,
    )
    db.add(closing)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise CashError("這個班次已經結過帳了；如果點錯，請店長作廢後重新結帳")
    db.refresh(closing)
    return closing


def variance_status(closing: CashClosing) -> str:
    v = money(closing.variance)
    if v == 0:
        return "balanced"
    return "short" if v < 0 else "over"


def float_mismatch(closing: CashClosing) -> bool:
    """有收走現金的那一班（通常是晚班）：留在抽屜的應該剛好等於固定零用金。"""
    if money(closing.collected_amount) <= 0:
        return False
    return money(closing.remaining_cash) != money(closing.cash_float_snapshot)


def recompute_live(db: Session, closing: CashClosing) -> Dict[str, Any]:
    """用「現在」的帳重算同一個區間，跟結帳當下存的快照比對。
    不一致 = 結帳之後這段時間的帳被動過（例如異動被作廢）。"""
    start, end = as_utc(closing.interval_start), as_utc(closing.closed_at)
    live_sales = sum_cash_sales(db, start, end)
    live_in, live_out = movement_totals(db, start, end)
    live_expected = money(closing.opening_cash) + live_sales + live_in - live_out
    changed = abs(live_expected - money(closing.expected_cash)) >= CENT
    return {
        "cash_sales": live_sales,
        "movements_in": live_in,
        "movements_out": live_out,
        "expected_cash": live_expected,
        "changed": changed,
        "delta": live_expected - money(closing.expected_cash),
    }


def set_note(db: Session, closing_id: int, user: AdminUser, note: str) -> CashClosing:
    """結帳後才看得到差額，所以讓結帳的人事後補充說明；一旦寫了只有店長能改。"""
    closing = db.get(CashClosing, closing_id)
    if not closing or closing.voided_at:
        raise CashError("找不到這筆結帳")
    is_manager = user.role in ("manager", "super_admin")
    if not is_manager and (closing.closed_by_id != user.id or closing.note):
        raise CashError("沒有權限修改說明")
    text_value = (note or "").strip()
    if not text_value:
        raise CashError("說明不能是空白")
    closing.note = text_value
    closing.updated_at = now_utc()
    db.commit()
    return closing


def review_closing(db: Session, closing_id: int, user_id: int, note: Optional[str]) -> CashClosing:
    closing = db.get(CashClosing, closing_id)
    if not closing or closing.voided_at:
        raise CashError("找不到這筆結帳")
    closing.reviewed_at = now_utc()
    closing.reviewed_by_id = user_id
    closing.review_note = (note or "").strip() or None
    closing.updated_at = now_utc()
    db.commit()
    return closing


def void_closing(db: Session, closing_id: int, user_id: int, reason: str) -> CashClosing:
    closing = db.get(CashClosing, closing_id)
    if not closing:
        raise CashError("找不到這筆結帳")
    if closing.voided_at:
        raise CashError("這筆結帳已經作廢了")
    reason = (reason or "").strip()
    if not reason:
        raise CashError("作廢必須填寫原因")
    # 只能作廢「最新一筆」：後面的結帳是接在它後面算的，抽掉中間一筆會讓後面的期初對不上
    latest = latest_active_closing(db)
    if not latest or latest.id != closing.id:
        raise CashError("只能作廢最新的一筆結帳（之後的結帳是接在它後面算的）")
    closing.voided_at = now_utc()
    closing.voided_by_id = user_id
    closing.void_reason = reason
    closing.updated_at = now_utc()
    db.commit()
    return closing


# ---------- 現金異動 ----------


def create_movement(
    db: Session,
    *,
    entry_date: date,
    movement_type: str,
    amount: Any,
    counterparty: Optional[str],
    description: str,
    entered_by_id: int,
) -> CashMovement:
    if movement_type not in MOVEMENT_DIRECTIONS:
        raise CashError("異動類型不正確")
    value = money(amount)
    if value <= 0:
        raise CashError("金額必須大於 0")
    desc = (description or "").strip()
    if not desc:
        raise CashError("請填寫用途或原因（日後查帳要用）")
    if entry_date > taipei_today():
        raise CashError("日期不能是未來")
    movement = CashMovement(
        entry_date=entry_date,
        movement_type=movement_type,
        direction=MOVEMENT_DIRECTIONS[movement_type],
        amount=value,
        counterparty=(counterparty or "").strip() or None,
        description=desc,
        entered_by_id=entered_by_id,
    )
    db.add(movement)
    db.commit()
    db.refresh(movement)
    return movement


def void_movement(db: Session, movement_id: int, user_id: int, reason: str) -> CashMovement:
    movement = db.get(CashMovement, movement_id)
    if not movement:
        raise CashError("找不到這筆異動")
    if movement.voided_at:
        raise CashError("這筆異動已經作廢了")
    reason = (reason or "").strip()
    if not reason:
        raise CashError("作廢必須填寫原因")
    movement.voided_at = now_utc()
    movement.voided_by_id = user_id
    movement.void_reason = reason
    movement.updated_at = now_utc()
    db.commit()
    return movement


def list_movements_for_date(db: Session, d: date) -> List[CashMovement]:
    return (
        db.query(CashMovement)
        .filter(CashMovement.entry_date == d)
        .order_by(CashMovement.created_at.desc(), CashMovement.id.desc())
        .all()
    )


def counterparty_suggestions(db: Session) -> List[str]:
    coaches = [m.name for m in db.query(Member).filter(Member.role == "coach").all()]
    venue = [v.name for v in db.query(VenueRentalCoach).filter(VenueRentalCoach.is_active.is_(True)).all()]
    return list(dict.fromkeys(coaches + venue))


# ---------- 明細與總覽 ----------


def usernames(db: Session) -> Dict[int, str]:
    return {u.id: u.username for u in db.query(AdminUser).all()}


def closing_detail(db: Session, closing: CashClosing) -> Dict[str, Any]:
    start, end = as_utc(closing.interval_start), as_utc(closing.closed_at)

    sales = cash_sale_entries(db, start, end)
    sale_rows = []
    for e in sales:
        created_local = to_taipei(e.created_at)
        sale_rows.append(
            {
                "entry": e,
                "created_local": created_local,
                # 收款日期跟實際輸入日期不同天 = 補登或改過日期，查帳時要特別留意
                "backfilled": created_local is not None and e.entry_date != created_local.date(),
            }
        )

    movements = (
        db.query(CashMovement)
        .filter(CashMovement.created_at > start, CashMovement.created_at <= end)
        .order_by(CashMovement.created_at, CashMovement.id)
        .all()
    )
    movement_rows = [
        {
            "movement": m,
            "created_local": to_taipei(m.created_at),
            "voided_after_close": bool(m.voided_at and as_utc(m.voided_at) > end),
        }
        for m in movements
    ]

    # 區間內出現的非現金付款方式：若有非標準寫法（例如打成「現 金」「cash2」），
    # 其實是現金的話就會讓應有現金少算，列出來讓人檢查
    other_methods: Dict[str, int] = {}
    rows = (
        db.query(RevenueDetail.payment_method, func.count(RevenueDetail.id))
        .filter(RevenueDetail.created_at > start, RevenueDetail.created_at <= end)
        .group_by(RevenueDetail.payment_method)
        .all()
    )
    for method, count in rows:
        norm = (method or "").strip().lower()
        if norm not in CASH_METHOD_ALIASES:
            other_methods[method] = count
    nonstandard = sorted(
        m for m in other_methods if (m or "").strip().lower() not in STANDARD_PAYMENT_METHODS
    )

    return {
        "sale_rows": sale_rows,
        "movement_rows": movement_rows,
        "non_cash_methods": other_methods,
        "nonstandard_methods": nonstandard,
        "live": recompute_live(db, closing),
        "float_mismatch": float_mismatch(closing),
    }


def get_day_status(db: Session, d: date) -> Dict[str, Optional[CashClosing]]:
    rows = (
        db.query(CashClosing)
        .filter(CashClosing.business_date == d, CashClosing.voided_at.is_(None))
        .all()
    )
    by_shift = {c.shift: c for c in rows}
    return {shift: by_shift.get(shift) for shift in SHIFT_ORDER}


def get_overview(db: Session, start_date: date, end_date: date) -> Dict[str, Any]:
    """店長用總覽：每天三個班的結帳狀態與差額、未結帳的班次、結帳後帳目有被動過的班次。"""
    closings = (
        db.query(CashClosing)
        .filter(
            CashClosing.business_date >= start_date,
            CashClosing.business_date <= end_date,
            CashClosing.voided_at.is_(None),
        )
        .order_by(CashClosing.business_date.desc(), CashClosing.closed_at)
        .all()
    )
    by_day: Dict[date, Dict[str, CashClosing]] = {}
    for c in closings:
        by_day.setdefault(c.business_date, {})[c.shift] = c

    revenue_days = {
        row[0]
        for row in db.query(RevenueDetail.entry_date)
        .filter(RevenueDetail.entry_date >= start_date, RevenueDetail.entry_date <= end_date)
        .distinct()
        .all()
    }

    now_local = datetime.now(TAIPEI)
    today = now_local.date()
    days: List[Dict[str, Any]] = []
    total_short = Decimal("0.00")
    total_over = Decimal("0.00")
    unbalanced = 0
    missing = 0
    changed = 0
    unreviewed = 0

    d = end_date
    while d >= start_date:
        if d in by_day or d in revenue_days:
            shifts: Dict[str, Dict[str, Any]] = {}
            for shift in SHIFT_ORDER:
                c = by_day.get(d, {}).get(shift)
                if c is not None:
                    live = recompute_live(db, c)
                    v = money(c.variance)
                    if v < 0:
                        total_short += -v
                    elif v > 0:
                        total_over += v
                    if v != 0:
                        unbalanced += 1
                        if not c.reviewed_at:
                            unreviewed += 1
                    if live["changed"]:
                        changed += 1
                    shifts[shift] = {"closing": c, "status": variance_status(c), "live_changed": live["changed"]}
                else:
                    # 有收款紀錄的日子，該班時間已過卻沒結帳 = 漏點
                    due = d < today or (d == today and now_local.hour >= SHIFT_END_HOUR[shift])
                    is_missing = d in revenue_days and due
                    if is_missing:
                        missing += 1
                    shifts[shift] = {"closing": None, "status": "missing" if is_missing else "none", "live_changed": False}
            days.append({"date": d, "shifts": shifts})
        d -= timedelta(days=1)

    return {
        "days": days,
        "total_short": total_short,
        "total_over": total_over,
        "unbalanced_count": unbalanced,
        "missing_count": missing,
        "changed_count": changed,
        "unreviewed_count": unreviewed,
    }
