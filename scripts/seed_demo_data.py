"""正式環境開機時自動跑一次（跟 bootstrap_admin.py 同一套模式）：
設了 SEED_DEMO_DATA=true，而且目前完全沒有任何會員資料，就塞一批
「看起來像真的」的示範資料——教練/學員名字跟課程樣式都比照客戶現行
Google Sheets 裡真實出現過的樣子，方便客戶在正式環境檢視畫面時，
看的是貼近實際情境的資料，而不是空的。之後跑正式的歷史資料遷移、
或客戶自己開始建真資料之後，這支腳本因為「已經有會員資料」就不會
再動，安全地留在開機流程裡不會有重複塞資料的問題。"""

import os
from datetime import date, time, timedelta

from app.database import SessionLocal
from app.models import AdminUser, Member, VenueRentalCoach
from app.services.booking_service import create_booking
from app.services.class_record_service import create_class_record
from app.services.contract_service import create_contract
from app.services.revenue_service import create_revenue_entry
from app.services.schedule_service import assign_shift
from app.services.venue_booking_service import create_venue_booking


def seed_venue_coach_demo(db) -> None:
    """場租教練跟一般會員是不同的表，各自獨立判斷是否已經 seed 過，
    不會因為主要示範資料已經跑過就永遠跳過這塊。

    名字取自客戶「課堂報表」合約總表裡「教練」欄位、扣掉店內 6 位正職教練後
    出現頻率最高的幾個外聘教練代號（ELSIE/ELSA/HANK），確認是真的會跟他們
    租場地帶自己客人的場租教練，不是虛構的示範名字。"""
    if db.query(VenueRentalCoach).count() > 0:
        print("已經有場租教練資料，略過場租教練示範資料。")
        return

    coaches = []
    for name in ("ELSIE", "ELSA", "HANK"):
        coach = VenueRentalCoach(name=name)
        db.add(coach)
        coaches.append(coach)
    db.commit()

    today = date.today()
    create_venue_booking(
        db, venue_coach_id=coaches[0].id, customer_name="李先生", customer_phone=None,
        party_size=1, slot_date=today, slot_start_time=time(16, 0), area="strength",
    )
    create_venue_booking(
        db, venue_coach_id=coaches[0].id, customer_name="陳小姐", customer_phone=None,
        party_size=1, slot_date=today, slot_start_time=time(16, 0), area="strength",
    )
    create_venue_booking(
        db, venue_coach_id=coaches[1].id, customer_name="黃先生", customer_phone=None,
        party_size=2, slot_date=today, slot_start_time=time(19, 0), area="strength",
    )
    print("已建立示範場租教練資料：3 位場租教練、今天 3 筆預約（含同時段多筆示範）。")


def main() -> None:
    if os.environ.get("SEED_DEMO_DATA") != "true":
        print("未設定 SEED_DEMO_DATA=true，略過示範資料。")
        return

    db = SessionLocal()
    try:
        seed_venue_coach_demo(db)

        if db.query(Member).count() > 0:
            print("已經有會員資料存在，略過示範資料 seed。")
            return

        today = date.today()

        # 教練：沿用客戶現行班表上真實出現過的代號
        coach_names = ["NICK", "WEILIN", "YOKO", "DK", "NINA", "MUMU"]
        coaches = {}
        for i, name in enumerate(coach_names, start=1):
            coach = Member(member_no=f"COACH-{name}", name=name, role="coach")
            db.add(coach)
            db.flush()
            coaches[name] = coach

        # 學員：一般 solo + 一組 1對2
        student_defs = [
            ("UF0001", "林貞如"),
            ("UF0002", "劉嘉容"),
            ("UF0003", "王小明"),
            ("UF0004", "陳雨佳"),
            ("UF0005", "張智凱"),
        ]
        students = {}
        for member_no, name in student_defs:
            student = Member(member_no=member_no, name=name, role="student")
            db.add(student)
            db.flush()
            students[name] = student

        db.commit()

        # 合約：solo 重訓、1對2 皮拉提斯、單月會籍學員
        c1 = create_contract(
            db, coach_id=coaches["DK"].id, member_ids=[students["林貞如"].id], course_type="strength",
            purchase_date=today - timedelta(days=20), unit_price=18900, total_sessions=12, contract_no="00123",
        )
        c1.used_sessions = 3
        db.add(c1)

        c2 = create_contract(
            db, coach_id=coaches["YOKO"].id, member_ids=[students["劉嘉容"].id, students["王小明"].id],
            course_type="pilates", purchase_date=today - timedelta(days=35), unit_price=22680, total_sessions=12,
            contract_no="00098",
        )
        c2.used_sessions = 5
        db.add(c2)

        c3 = create_contract(
            db, coach_id=coaches["NICK"].id, member_ids=[students["陳雨佳"].id], course_type="strength",
            purchase_date=today - timedelta(days=10), unit_price=13500, total_sessions=10, contract_no="00077",
        )
        c3.used_sessions = 2
        db.add(c3)

        db.commit()

        # 單月會籍（不算合約，直接掛在會員身上）
        member_only = students["張智凱"]
        member_only.membership_start_date = today - timedelta(days=5)
        member_only.membership_active_until = today + timedelta(days=25)
        db.commit()

        # 課程紀錄：示範「實際帶課教練」跟合約登記教練不同的代課情境
        create_class_record(
            db, contract_id=c1.id, actual_teaching_coach_id=coaches["DK"].id,
            class_date=today - timedelta(days=3), content_summary="深蹲、硬舉，重量都有進步。",
            logged_by_id=coaches["DK"].id,
        )
        create_class_record(
            db, contract_id=c1.id, actual_teaching_coach_id=coaches["NICK"].id,
            class_date=today - timedelta(days=1), content_summary="DK請假由NICK代課，練上肢。",
            logged_by_id=coaches["NICK"].id,
        )
        create_class_record(
            db, contract_id=c2.id, actual_teaching_coach_id=coaches["YOKO"].id,
            class_date=today - timedelta(days=2), content_summary="皮拉提斯核心訓練，兩位一起上。",
            logged_by_id=coaches["YOKO"].id,
        )

        # 今天的班表：早/中/晚各排一位，其餘未排班（=OFF）
        assign_shift(db, work_date=today, shift="morning", coach_id=coaches["WEILIN"].id)
        assign_shift(db, work_date=today, shift="afternoon", coach_id=coaches["DK"].id)
        assign_shift(db, work_date=today, shift="evening", coach_id=coaches["NINA"].id)

        # 今天的約課：示範網格畫面（含一筆皮拉提斯，會反映在容量欄位）
        create_booking(
            db, coach_id=coaches["DK"].id, contract_id=c1.id, slot_date=today,
            slot_start_time=time(14, 0), area="strength", created_by_id=coaches["DK"].id,
        )
        create_booking(
            db, coach_id=coaches["YOKO"].id, contract_id=c2.id, slot_date=today,
            slot_start_time=time(15, 0), area="pilates", created_by_id=coaches["YOKO"].id,
        )

        # 今日營收：比照現行銷售分類
        first_admin = db.query(AdminUser).order_by(AdminUser.id).first()
        if first_admin is None:
            print("找不到任何後台帳號，略過營收示範資料（其餘資料已建立）。")
            return
        admin_user_id = first_admin.id
        create_revenue_entry(
            db, entry_date=today, item_category="coaching", item_name="1V1PT*12",
            payment_method="現金", amount=18900, coach_id=coaches["DK"].id, entered_by_id=admin_user_id,
        )
        create_revenue_entry(
            db, entry_date=today, item_category="membership", item_name="單月會籍",
            payment_method="匯款", amount=1500, entered_by_id=admin_user_id,
        )
        create_revenue_entry(
            db, entry_date=today, item_category="beverage", item_name="運動飲料",
            payment_method="現金", amount=50, entered_by_id=admin_user_id,
        )

        print("已建立示範資料：6 位教練、5 位學員、3 份合約、3 筆課程紀錄、今日班表與約課、3 筆營收。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
