"""正式環境開機時自動跑一次：品項目錄是空的話，塞一批預設品項/單價。
這不是示範資料，是真的操作用的參考清單，所以跟 SEED_DEMO_DATA 分開、
不用環境變數開關，永遠跑，只是「已經有品項就跳過」保證不會重複塞。

單價來源：現行「XXX年X月銷售總表」裡實際出現過的真實成交價格
（教練課/會籍/飲料都是從真實歷史交易紀錄裡查到的客戶價，不是用猜的；
飲料另外還有員工價但這裡先只放客戶價，員工價之後要用再加）。"""

from app.database import SessionLocal
from app.models import ItemCatalogEntry

SEED_ITEMS = [
    ("coaching", "1V1PT*12", 18900),
    ("coaching", "1V1PT*16", 27552),
    ("coaching", "1V1PT*24", 39312),
    ("coaching", "1V1PL*12", 22680),
    ("coaching", "1V2PT*24", 41328),
    ("membership", "單次會籍", 250),
    ("membership", "單月會籍", 1500),
    ("membership", "單月會籍(BR)", 1000),
    ("membership", "半年會籍", 4800),
    ("membership", "年繳會籍", 7200),
    ("membership", "製卡費", 100),
    ("service_venue", "場租(1V1)", 8400),
    ("beverage", "運動飲料", 20),
    ("beverage", "魔爪", 55),
    ("beverage", "冷翠蒸綠茶(小)", 30),
    ("beverage", "原萃日式綠茶(大)", 23),
    ("beverage", "水", 20),
]


def main() -> None:
    db = SessionLocal()
    try:
        if db.query(ItemCatalogEntry).count() > 0:
            print("品項目錄已經有資料，略過預設品項 seed。")
            return

        for category, name, price in SEED_ITEMS:
            db.add(ItemCatalogEntry(item_category=category, item_name=name, default_price=price))
        db.commit()
        print(f"已建立 {len(SEED_ITEMS)} 筆預設品項。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
