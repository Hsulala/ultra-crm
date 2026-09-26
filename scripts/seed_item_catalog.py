"""正式環境開機時每次都會跑：把品項目錄同步成客戶「XXX年X月銷售總表」Settings
分頁 D~G 欄（品項/內容/堂數/金額）裡的真實資料，那份分頁本身就是這間店拿來當
品項下拉選單來源用的表，所以直接照搬，不是用猜的。

這裡不是「已經有資料就整個跳過」，而是：
1. 先移除最早那批用型態猜出來、不是表格原文的 17 筆佔位品項（如果店家自己在
   後台把它們改過名字/價格，就不會符合精確比對，會被當成使用者資料留著不動）。
2. 用「品項分類＋內容」當 key，缺的才補進去，已經存在（不管是這次補的、
   還是店家自己在後台新增的）一律不動，所以在正式環境重複執行是安全的。"""

from app.database import SessionLocal
from app.models import ItemCatalogEntry

# 最早那批用型態猜測拼出來的佔位品項（不是 Settings 分頁裡的原文字串），
# 只有在後台資料還完全等於這一筆時才會被移除，店家自己改過就不會動到。
OLD_PLACEHOLDER_ITEMS = [
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

# 客戶「XXX年X月銷售總表」Settings 分頁 D(品項)/E(內容)/G(金額) 欄的真實資料，
# 品項分類對照：教練課→coaching、飲料→beverage、會籍→membership；
# 原本 Settings 分頁裡都叫「服務」的，內容含「場租」兩個字的算 venue_rental（場租），
# 其餘算 service（服務），這是客戶要求把場租獨立出來後才拆出來的兩個分類。
SEED_ITEMS = [
    ("service", "1V1*20", 8400),
    ("venue_rental", "1V1場租*20(含稅)", 8400),
    ("venue_rental", "1V1場租*30", 12000),
    ("venue_rental", "1V2場租*20", 11000),
    ("venue_rental", "皮拉場租*1", 600),
    ("service", "物理治療60h", 15000),
    ("venue_rental", "場租*1", 450),
    ("venue_rental", "場租*10", 4500),
    ("venue_rental", "場租*12", 5400),
    ("venue_rental", "場租*13", 5850),
    ("venue_rental", "場租*14", 6300),
    ("venue_rental", "場租*16", 7200),
    ("venue_rental", "場租*11", 4950),
    ("venue_rental", "場租*23", 9200),
    ("venue_rental", "場租*37", 14800),
    ("venue_rental", "場租*16(1V2)", 9600),
    ("venue_rental", "場租*20", 8000),
    ("venue_rental", "場租*20(450)", 9000),
    ("venue_rental", "場租*24", 9600),
    ("venue_rental", "場租*25", 10000),
    ("venue_rental", "場租*8", 3600),
    ("venue_rental", "場租1V2*10", 6000),
    ("venue_rental", "場租1V2*10(加稅)", 6300),
    ("service", "量INBODY", 250),
    ("venue_rental", "嘟嘟場租", 38000),
    ("venue_rental", "PT場租1V2", 600),
    ("venue_rental", "PL場租1V2", 600),
    ("venue_rental", "場租20(特殊)", 7550),
    ("service", "承上補差額", 450),
    ("coaching", "1V1PL*10(1764)", 17640),
    ("coaching", "1V1PL*12", 22680),
    ("coaching", "1V1PL*12(1764)", 21168),
    ("coaching", "1V1PL*20", 35280),
    ("coaching", "1V1PT*1(1575)", 1575),
    ("coaching", "1V1PT*10(1000)", 10000),
    ("coaching", "1V1PT*8(1420)", 11360),
    ("coaching", "1V1PT*12(1420)", 17040),
    ("coaching", "1V1PT*12(1575)", 18900),
    ("coaching", "1V1PT*16", 27552),
    ("coaching", "1V1PT*16(1420)", 22720),
    ("coaching", "1V1PT*16(1420) 尾款", 5680),
    ("coaching", "1V1PT*16(1420) 訂金", 17040),
    ("coaching", "1V1PT*16(1575)", 25200),
    ("coaching", "1V1PT*16(1575)訂金", 19000),
    ("coaching", "1V1PT*2(1575)", 3150),
    ("coaching", "1V1PT*20(1575)", 31500),
    ("coaching", "1V1PT*24", 39312),
    ("coaching", "1V1PT*24(1575)", 37800),
    ("coaching", "1V1PT*24(1420)", 34080),
    ("coaching", "1V1PL*6(1764)", 10584),
    ("coaching", "1V1PT*25", 37500),
    ("coaching", "1v1PT*3", 4725),
    ("coaching", "1V1PT*36", 56700),
    ("coaching", "1V1PT*36(1420)", 51120),
    ("coaching", "1V1PT*5", 7100),
    ("coaching", "1V1PT*50", 75000),
    ("coaching", "1V1PT*8", 12600),
    ("coaching", "1V2PL*12", 32160),
    ("coaching", "1V2PL*12(2480)", 29760),
    ("coaching", "1V2PL*20", 49600),
    ("coaching", "1V2PT*10", 15600),
    ("coaching", "1V2PT*16", 30240),
    ("coaching", "1V2PT*16(1638)", 26208),
    ("coaching", "1V2PT*24", 41328),
    ("coaching", "1V2PT*36", 58968),
    ("coaching", "PL體驗", 900),
    ("coaching", "PT體驗", 500),
    ("coaching", "PT體驗1V2", 1000),
    ("coaching", "1V2PT*3(1638)", 4914),
    ("coaching", "1V2PT*4(1638)", 6552),
    ("beverage", "(員工)冷翠蒸綠茶(小)", 26),
    ("beverage", "(員工)原萃日式綠茶(大)", 19),
    ("beverage", "(員工)運動飲料", 17),
    ("beverage", "(員工)魔爪", 47),
    ("beverage", "水", 20),
    ("beverage", "冷翠蒸綠茶(小)", 30),
    ("beverage", "原萃日式綠茶(大)", 23),
    ("beverage", "運動飲料", 20),
    ("beverage", "魔爪", 55),
    ("membership", "半年會籍", 4800),
    ("membership", "年繳會籍", 7200),
    ("membership", "單月會籍", 1500),
    ("membership", "單月會籍(BR)", 1000),
    ("membership", "單次會籍", 250),
    ("membership", "製卡費", 100),
    ("venue_rental", "場租*36(PL1V2)", 21600),
    ("service", "補差額", 305),
    ("venue_rental", "場租*4", 1800),
    ("service", "PL體驗1V2", 1800),
    ("coaching", "1V1 PT*12(1638)", 19656),
    ("venue_rental", "場租*24(450)", 10800),
    ("venue_rental", "場租*36", 14400),
    ("coaching", "1V1補1V2差額", 218),
    ("coaching", "1V2PL補差額", 660),
    ("service", "1V1補1V2", 200),
    ("coaching", "1V1PT*16(1000)", 16000),
    ("service", "1V2*12", 7200),
    ("coaching", "1V1PT*20(1420)", 28400),
    ("coaching", "1V1PT*6(1575)", 9450),
    ("coaching", "1V2PT*6(1638)", 9828),
    ("coaching", "5月活動(PL)", 450),
    ("coaching", "5月活動(PL)1v2", 900),
    ("coaching", "5月活動(PT)", 250),
    ("coaching", "補差額(PL體驗)", 378),
    ("venue_rental", "場租1V1*23", 9200),
    ("coaching", "1V1改1V2補差額", 3165),
    ("coaching", "1V2PL*6", 14880),
    ("coaching", "1v1*25(1500)", 37500),
    ("venue_rental", "場租*10(一半現金)", 4000),
    ("venue_rental", "場租*10(一半匯款)", 4000),
    ("coaching", "1v2*18(1638)", 29484),
    ("coaching", "1v1PL*12(1200)親屬價", 14400),
    ("service", "增購2堂", 900),
    ("coaching", "皮拉1764*2", 3528),
    ("coaching", "重訓1575*2", 3150),
    ("coaching", "PL1764*3", 5292),
    ("coaching", "皮拉改重訓補差額", 1170),
    ("coaching", "PL體驗1V2", 1800),
    ("coaching", "PT體驗1V2(現金)", 500),
    ("coaching", "PT體驗1V2(匯款)", 500),
    ("service", "1V2PL*24", 14400),
    ("venue_rental", "場租*24(1V2)", 13200),
    ("venue_rental", "1V2場租*24(600)", 14400),
    ("venue_rental", "場租*9", 4050),
    ("service", "1V1改1V2補差價", 2850),
    ("coaching", "教練課訂金", 6700),
    ("coaching", "1V1*18(1575)", 28350),
    ("service", "空瑜掛布", 500),
    ("coaching", "1V1PT*36(尾款)", 50000),
    ("coaching", "1V1PT*36(訂金)", 6700),
    ("venue_rental", "場租*16分開付(匯款)", 6000),
    ("venue_rental", "場租*16分開付(現金)", 1200),
    ("coaching", "團課10堂(4000)", 4000),
    ("coaching", "1V1PT*25(1000)", 25000),
    ("venue_rental", "場租*5", 2250),
    ("coaching", "1V2*16(1638)一半", 13104),
    ("coaching", "1V1PT*10(1420)", 14200),
    ("venue_rental", "場租*26", 10400),
    ("venue_rental", "場租*19(1V2)", 11400),
    ("venue_rental", "場租*33", 13200),
    ("venue_rental", "場租*8(1420)", 11360),
    ("coaching", "1V2PT*24(1638)", 39312),
    ("coaching", "1V1PT*16(訂金)", 10000),
    ("coaching", "1V1PT*16(1722)", 17552),
    ("coaching", "1V1PT*36(50000匯款)", 50000),
    ("coaching", "1V1PT*36(6700現金)", 6700),
]


def main() -> None:
    db = SessionLocal()
    try:
        # 有幾筆舊的猜測品項剛好跟 Settings 分頁的真實資料同名同價，
        # 這種不用刪了又補、直接當作已經是真實資料看待就好。
        real_keys = {(category, name) for category, name, _ in SEED_ITEMS}

        removed = 0
        for category, name, price in OLD_PLACEHOLDER_ITEMS:
            if (category, name) in real_keys:
                continue
            entry = (
                db.query(ItemCatalogEntry)
                .filter(
                    ItemCatalogEntry.item_category == category,
                    ItemCatalogEntry.item_name == name,
                    ItemCatalogEntry.default_price == price,
                    ItemCatalogEntry.is_active == True,  # noqa: E712
                )
                .first()
            )
            if entry is not None:
                db.delete(entry)
                removed += 1
        if removed:
            db.commit()
            print(f"已移除 {removed} 筆舊的猜測品項。")

        existing = {
            (e.item_category, e.item_name)
            for e in db.query(ItemCatalogEntry.item_category, ItemCatalogEntry.item_name).all()
        }
        added = 0
        for category, name, price in SEED_ITEMS:
            if (category, name) in existing:
                continue
            db.add(ItemCatalogEntry(item_category=category, item_name=name, default_price=price))
            existing.add((category, name))
            added += 1
        if added:
            db.commit()
        print(f"已補上 {added} 筆真實品項（來自客戶銷售總表 Settings 分頁）。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
