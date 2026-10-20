"""匯入客戶舊 Google Sheets 資料（bundle 由 scripts/legacy/convert.py 產生）。

整個匯入在同一個交易裡：試跑（commit=False）跟正式匯入走完全一樣的程式，
只差最後是 rollback 還是 commit，所以試跑看到的數字就是正式匯入會寫進去的數字。

clear_existing=True 會先清掉會員、合約、預約、營收、班表、現金對帳等營運資料
（系統還沒交給店家前的測試資料）；後台帳號、品項目錄、系統設定保留。"""

import datetime as dt
from collections import Counter, OrderedDict
from typing import Dict, List, Optional

from sqlalchemy import func, insert, text
from sqlalchemy.orm import Session

from app.models import (
    AdminUser,
    Contract,
    ContractMember,
    ContractSession,
    Member,
    RevenueDetail,
    VenueRentalCoach,
)

BUNDLE_FORMAT = "ultra-legacy-v1"

# 清除順序：先刪參照別人的表。admin_users.linked_member_id 另外設成 NULL。
CLEAR_TABLES = [
    "notification_logs",
    "bookings",
    "class_records",
    "contract_sessions",
    "revenue_details",
    "contract_members",
    "binding_codes",
    "schedules",
    "coach_unavailabilities",
    "venue_bookings",
    "cash_movements",
    "cash_closings",
    "contracts",
    "members",
    "venue_rental_coaches",
]


class LegacyImportError(Exception):
    pass


def _d(s: Optional[str]) -> Optional[dt.date]:
    return dt.date.fromisoformat(s) if s else None


def clear_operational_data(db: Session) -> Dict[str, int]:
    counts = {}
    db.execute(text("UPDATE admin_users SET linked_member_id = NULL"))
    for table in CLEAR_TABLES:
        counts[table] = db.execute(text(f"DELETE FROM {table}")).rowcount or 0
    return counts


def _member_no_start(db: Session) -> int:
    import re

    max_no = 0
    for (no,) in db.query(Member.member_no).filter(Member.member_no.like("UF%")).all():
        m = re.fullmatch(r"UF(\d+)", no or "")
        if m:
            max_no = max(max_no, int(m.group(1)))
    return max_no + 1


def run_import(
    db: Session,
    bundle: dict,
    *,
    batch: str,
    clear_existing: bool,
    commit: bool,
) -> dict:
    if bundle.get("format") != BUNDLE_FORMAT:
        raise LegacyImportError("檔案格式不對，請用 scripts/legacy/convert.py 產生的檔案")

    report: dict = {"batch": batch, "committed": False, "cleared": {}}
    try:
        if clear_existing:
            report["cleared"] = clear_operational_data(db)
        elif db.query(Member).filter(Member.import_batch.isnot(None)).first():
            raise LegacyImportError("已經匯入過舊資料；要重新匯入請勾選「先清除目前的資料」")

        admin = (
            db.query(AdminUser)
            .filter(AdminUser.role == "super_admin", AdminUser.is_active == True)  # noqa: E712
            .order_by(AdminUser.id)
            .first()
        )
        if admin is None:
            raise LegacyImportError("找不到啟用中的超級管理者帳號，營收需要登記人")

        contracts_in: List[dict] = bundle.get("contracts", [])
        revenue_in: List[dict] = bundle.get("revenue", [])

        # ---- 教練 ----
        staff_ids: Dict[str, int] = {}
        for name in bundle.get("staff_coaches", []):
            m = (
                db.query(Member)
                .filter(Member.role == "coach", func.upper(Member.name) == name.upper())
                .first()
            )
            if m is None:
                m = Member(member_no=f"COACH-{name}", name=name, role="coach", import_batch=batch)
                db.add(m)
                db.flush()
            staff_ids[name.upper()] = m.id

        venue_ids: Dict[str, int] = {}
        existing_vc = {vc.name.strip().upper(): vc for vc in db.query(VenueRentalCoach).all()}
        venue_names = list(bundle.get("venue_coaches", []))
        if any(not c.get("coach") for c in contracts_in):
            venue_names.append("原表未填教練")
        for name in venue_names:
            key = name.strip().upper()
            vc = existing_vc.get(key)
            if vc is None:
                vc = VenueRentalCoach(name=name, import_batch=batch)
                db.add(vc)
                db.flush()
                existing_vc[key] = vc
            venue_ids[key] = vc.id

        # ---- 學員：同名視為同一人，依第一次購買日期排會員編號 ----
        first_seen: "OrderedDict[str, str]" = OrderedDict()
        for c in sorted(contracts_in, key=lambda c: (c["purchase_date"], c["contract_no"])):
            for n in c["students"]:
                first_seen.setdefault(n, c["purchase_date"])
        next_no = _member_no_start(db)
        student_ids: Dict[str, int] = {}
        rows = []
        for i, name in enumerate(first_seen):
            rows.append(
                {
                    "member_no": f"UF{next_no + i:04d}",
                    "name": name,
                    "role": "student",
                    "is_active": True,
                    "import_batch": batch,
                }
            )
        if rows:
            db.execute(insert(Member), rows)
        for mid, name in db.query(Member.id, Member.name).filter(
            Member.import_batch == batch, Member.role == "student"
        ):
            student_ids[name] = mid

        # ---- 合約 ----
        contract_rows = []
        for c in contracts_in:
            coach = (c.get("coach") or "").upper()
            coach_id = staff_ids.get(coach)
            venue_id = None if coach_id else venue_ids.get(coach or "原表未填教練")
            if coach_id is None and venue_id is None:
                raise LegacyImportError(f"合約 {c['contract_no']} 的教練 {coach} 對不到")
            contract_rows.append(
                {
                    "contract_no": c["contract_no"],
                    "coach_id": coach_id,
                    "venue_coach_id": venue_id,
                    "course_type": c["course_type"],
                    "purchase_date": _d(c["purchase_date"]),
                    "unit_price": c["unit_price"],
                    "total_sessions": c["total_sessions"],
                    "used_sessions": min(len(c["sessions"]), c["total_sessions"]),
                    "status": c["status"],
                    "note": c.get("note"),
                    "import_batch": batch,
                }
            )
        ids = (
            db.execute(insert(Contract).returning(Contract.id), contract_rows).scalars().all()
            if contract_rows
            else []
        )
        if len(ids) != len(contracts_in):
            raise LegacyImportError("合約寫入筆數不符")

        link_rows, session_rows = [], []
        contract_by_no: Dict[str, List[int]] = {}
        for cid, c in zip(ids, contracts_in):
            contract_by_no.setdefault(c["contract_no"], []).append(cid)
            for n in dict.fromkeys(c["students"]):
                link_rows.append({"contract_id": cid, "member_id": student_ids[n]})
            for s in c["sessions"]:
                session_rows.append(
                    {
                        "contract_id": cid,
                        "session_no": s["no"],
                        "session_date": _d(s.get("date")),
                        "raw_value": s.get("raw"),
                        "import_batch": batch,
                    }
                )
        if link_rows:
            db.execute(insert(ContractMember), link_rows)
        for i in range(0, len(session_rows), 5000):
            db.execute(insert(ContractSession), session_rows[i : i + 5000])

        # ---- 營收 ----
        rev_rows = []
        linked = 0
        for r in revenue_in:
            coach = (r.get("coach") or "").upper()
            note = r.get("note")
            contract_id = None
            if note and note.isdigit():
                matches = contract_by_no.get(note.zfill(5), [])
                if len(matches) == 1:
                    contract_id = matches[0]
                    linked += 1
            content = None if contract_id else (f"備註：{note}" if note else None)
            rev_rows.append(
                {
                    "entry_date": _d(r["entry_date"]),
                    "item_category": r["item_category"],
                    "item_name": r["item_name"],
                    "coach_id": staff_ids.get(coach),
                    "coach_name": r.get("coach"),
                    "customer_name": r.get("customer_name"),
                    "content": content,
                    "payment_method": r["payment_method"],
                    "amount": r["amount"],
                    "contract_id": contract_id,
                    "entered_by_id": admin.id,
                    "import_batch": batch,
                }
            )
        for i in range(0, len(rev_rows), 2000):
            db.execute(insert(RevenueDetail), rev_rows[i : i + 2000])

        db.flush()

        # ---- 寫完再從資料庫數一次，跟檔案比對 ----
        q = lambda model: db.query(func.count()).select_from(model).filter(model.import_batch == batch).scalar()  # noqa: E731
        db_revenue_sum = (
            db.query(func.coalesce(func.sum(RevenueDetail.amount), 0))
            .filter(RevenueDetail.import_batch == batch)
            .scalar()
        )
        status_counts = Counter(c["status"] for c in contracts_in)
        report.update(
            {
                "file": {
                    "contracts": len(contracts_in),
                    "sessions": sum(len(c["sessions"]) for c in contracts_in),
                    "students": len(first_seen),
                    "revenue_rows": len(revenue_in),
                    "revenue_sum": round(sum(r["amount"] for r in revenue_in), 2),
                },
                "db": {
                    "contracts": q(Contract),
                    "sessions": q(ContractSession),
                    "students": db.query(func.count())
                    .select_from(Member)
                    .filter(Member.import_batch == batch, Member.role == "student")
                    .scalar(),
                    "revenue_rows": q(RevenueDetail),
                    "revenue_sum": round(float(db_revenue_sum), 2),
                },
                "staff_coaches": len(staff_ids),
                "venue_coaches": len(venue_ids),
                "contract_status": dict(status_counts),
                "revenue_linked_to_contract": linked,
                "issues": len(bundle.get("issues", [])),
            }
        )
        report["matches"] = report["file"] == report["db"]
        if not report["matches"]:
            raise LegacyImportError(f"寫入後比對不符：檔案 {report['file']}，資料庫 {report['db']}")

        if commit:
            db.commit()
            report["committed"] = True
        else:
            db.rollback()
        return report
    except Exception:
        db.rollback()
        raise
