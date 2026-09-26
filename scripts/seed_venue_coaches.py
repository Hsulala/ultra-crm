"""正式環境開機時每次都會跑：把真實場租教練的名字補進 venue_rental_coaches。

名單來源：客戶「XXX年X月銷售總表」(手動輸入)銷售總表分頁「教練」欄裡，
扣掉店內 6 位正職（NICK/WEILIN/YOKO/DK/NINA/MUMU）之後實際出現過的名字/代號——
不是猜的，是那個月真的有場租/上課紀錄的人。

只「補」不「刪」：用姓名（不分大小寫）比對，已經存在的不動，所以正式環境上
如果本來就有一筆佔位資料（例如舊的「自由教練1」），這支腳本不會去動它、
也不會自動刪除，需要的話請店家自己在後台「場租教練」管理頁改名或停用。"""

from app.database import SessionLocal
from app.models import VenueRentalCoach

# 客戶 115年9月銷售總表「教練」欄裡出現過、扣掉店內 6 位正職教練後的真實名字/代號。
SEED_NAMES = [
    "HANK",
    "BEAR",
    "建鋐",
    "SABRINA",
    "ELSIE",
    "RITA",
    "MYRIAM",
    "CHRIS",
    "ELSA",
    "JACKY",
    "BRIAN",
    "REGINA",
    "EGO",
    "AJ",
    "MEGGY",
]


def main() -> None:
    db = SessionLocal()
    try:
        existing_lower = {
            name.strip().lower()
            for (name,) in db.query(VenueRentalCoach.name).all()
        }
        added = 0
        for name in SEED_NAMES:
            if name.strip().lower() in existing_lower:
                continue
            db.add(VenueRentalCoach(name=name))
            existing_lower.add(name.strip().lower())
            added += 1
        if added:
            db.commit()
        print(f"已補上 {added} 位真實場租教練（來自客戶銷售總表）。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
