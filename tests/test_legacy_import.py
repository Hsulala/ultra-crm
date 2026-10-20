"""舊資料匯入（scripts/legacy/convert.py ＋ 後台「匯入舊資料」）。

需要 TEST_DATABASE_URL 指向「可被清空的測試資料庫」，沒設定就略過資料庫的部分。
用的都是假資料，不放任何客人真實資料。"""

import datetime as dt
import io
import json
import os

import pytest

from scripts.legacy.convert import norm_coach, parse_date

URL = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("110.8.4", dt.date(2021, 8, 4)),
        ("10.8.24", dt.date(2021, 8, 24)),  # 少打開頭的 1
        ("111.8..8", dt.date(2022, 8, 8)),
        ("111.11.10.", dt.date(2022, 11, 10)),
        ("2024/11/23", dt.date(2024, 11, 23)),
        ("0205/5/30", dt.date(2025, 5, 30)),
        ("0113/10/1", dt.date(2024, 10, 1)),
        ("202412/27", dt.date(2024, 12, 27)),
        ("2025/5 /6", dt.date(2025, 5, 6)),
        (dt.datetime(2025, 3, 1), dt.date(2025, 3, 1)),
    ],
)
def test_parse_date_fixes_common_typos(raw, expected):
    assert parse_date(raw)[0] == expected


@pytest.mark.parametrize("raw", ["110.8.32", "110.9.31", "112.8.214", dt.datetime(1900, 1, 3)])
def test_parse_date_keeps_impossible_dates_as_unparsed(raw):
    d, looks = parse_date(raw)
    assert d is None and looks


def test_norm_coach_aliases_and_first_of_pair():
    assert norm_coach("elas")[0] == "ELSA"
    assert norm_coach("NICK/WEILIN") == ("NICK", "NICK/WEILIN")
    assert norm_coach(None)[0] == ""


def _bundle():
    return {
        "format": "ultra-legacy-v1",
        "staff_coaches": ["NICK", "YOKO"],
        "venue_coaches": ["ELSA"],
        "contracts": [
            {"contract_no": "00001", "course_type": "strength", "students": ["甲學員"], "coach": "NICK",
             "purchase_date": "2021-08-02", "unit_price": 1000, "total_sessions": 3, "status": "active", "note": None,
             "sessions": [{"no": 1, "date": "2021-08-04"}, {"no": 2, "date": "2021-08-06"}, {"no": 3, "date": None, "raw": "110.8.32"}]},
            {"contract_no": "00002", "course_type": "strength", "students": ["甲學員", "乙學員"], "coach": "NICK",
             "purchase_date": "2021-09-01", "unit_price": 1560, "total_sessions": 10, "status": "active", "note": None,
             "sessions": [{"no": 1, "date": "2021-09-02"}]},
            {"contract_no": "00003", "course_type": "pilates", "students": ["丙學員"], "coach": "ELSA",
             "purchase_date": "2023-03-28", "unit_price": 450, "total_sessions": 12, "status": "refunded", "note": "已退費",
             "sessions": []},
            {"contract_no": "00004", "course_type": "strength", "students": ["丁學員"], "coach": "NICK",
             "purchase_date": "2021-10-01", "unit_price": 1420, "total_sessions": 11, "status": "active", "note": None,
             "sessions": [{"no": i, "date": f"2021-10-{i:02d}"} for i in range(1, 13)]},
        ],
        "revenue": [
            {"entry_date": "2025-04-01", "item_category": "coaching", "item_name": "1V2PT*10", "customer_name": "甲學員/乙學員",
             "coach": "NICK", "payment_method": "匯款", "amount": 15600, "note": "2"},
            {"entry_date": "2025-04-02", "item_category": "venue_rental", "item_name": "場租*10", "customer_name": None,
             "coach": "ELSA", "payment_method": "現金", "amount": 4500, "note": None},
        ],
        "issues": [{"where": "x", "kind": "測試", "value": "y"}],
    }


@pytest.fixture(scope="module")
def client():
    if not URL:
        pytest.skip("未設定 TEST_DATABASE_URL")
    os.environ["DATABASE_URL"] = URL
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    eng = create_engine(URL)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    command.upgrade(Config("alembic.ini"), "head")

    from app.auth.admin import hash_password

    with eng.begin() as conn:
        conn.execute(text("INSERT INTO admin_users (id, username, password_hash, role, is_active) VALUES "
                          "(1, 'boss', :p, 'super_admin', true), (2, 'desk', :p, 'front_desk', true)"), {"p": hash_password("pw")})
        # 測試資料（之後要被清掉）
        conn.execute(text("INSERT INTO members (id, member_no, name, role, is_active) VALUES (900, 'UF0001', '示範學員', 'student', true), (901, 'COACH-NICK', 'NICK', 'coach', true)"))
        conn.execute(text("UPDATE admin_users SET linked_member_id = 901 WHERE id = 2"))
        conn.execute(text("INSERT INTO contracts (id, coach_id, course_type, purchase_date, unit_price, total_sessions, used_sessions, status) VALUES (900, 901, 'strength', '2026-10-01', 1500, 10, 0, 'active')"))
        conn.execute(text("INSERT INTO contract_members (contract_id, member_id) VALUES (900, 900)"))
        conn.execute(text("INSERT INTO revenue_details (entry_date, item_category, item_name, payment_method, amount, entered_by_id) VALUES ('2026-10-01', 'beverage', '水', '現金', 20, 1)"))
    eng.dispose()

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def _login(c, user):
    c.post("/admin/logout")
    r = c.post("/admin/login", data={"username": user, "password": "pw"}, follow_redirects=False)
    assert r.status_code in (302, 303)


def _post(c, mode, clear, confirm="", bundle=None):
    raw = json.dumps(bundle or _bundle(), ensure_ascii=False).encode()
    return c.post(
        "/admin/legacy-import",
        files={"bundle": ("bundle.json", io.BytesIO(raw), "application/json")},
        data={"mode": mode, "clear_existing": "true" if clear else "false", "confirm": confirm},
    )


def test_only_super_admin(client):
    _login(client, "desk")
    assert _post(client, "dryrun", False).status_code == 403
    assert client.get("/admin/legacy-import/page").status_code == 403


def test_dryrun_writes_nothing(client):
    _login(client, "boss")
    r = _post(client, "dryrun", True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["committed"] is False and body["matches"] is True
    assert body["file"] == {"contracts": 4, "sessions": 16, "students": 4, "revenue_rows": 2, "revenue_sum": 20100.0}
    page = client.get("/admin/legacy-import/page").text
    assert "會員 2 位、合約 1 筆、營收 1 筆" in page


def test_commit_requires_confirm_word(client):
    _login(client, "boss")
    assert _post(client, "commit", True, confirm="").status_code == 400


def test_commit_clears_demo_and_imports(client):
    _login(client, "boss")
    r = _post(client, "commit", True, confirm="匯入")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["committed"] is True
    assert body["cleared"]["members"] == 2 and body["cleared"]["contracts"] == 1
    assert body["revenue_linked_to_contract"] == 1

    from sqlalchemy import create_engine, text

    eng = create_engine(URL)
    with eng.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM members WHERE name='示範學員'")).scalar() == 0
        assert conn.execute(text("SELECT linked_member_id FROM admin_users WHERE id=2")).scalar() is None
        # 1 對 2：同一張合約兩位學員；甲學員兩張合約只建一位會員
        assert conn.execute(text("SELECT count(*) FROM members WHERE name='甲學員'")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM contract_members cm JOIN contracts c ON c.id=cm.contract_id WHERE c.contract_no='00002'")).scalar() == 2
        # 已上堂數：日期打錯的那堂也算；超過合約堂數的上限是合約堂數
        assert conn.execute(text("SELECT used_sessions FROM contracts WHERE contract_no='00001'")).scalar() == 3
        assert conn.execute(text("SELECT used_sessions FROM contracts WHERE contract_no='00004'")).scalar() == 11
        assert conn.execute(text("SELECT count(*) FROM contract_sessions s JOIN contracts c ON c.id=s.contract_id WHERE c.contract_no='00004'")).scalar() == 12
        assert conn.execute(text("SELECT raw_value FROM contract_sessions WHERE session_date IS NULL")).scalar() == "110.8.32"
        # 場租教練的合約掛在 venue_coach_id
        assert conn.execute(text("SELECT venue_coach_id IS NOT NULL AND coach_id IS NULL FROM contracts WHERE contract_no='00003'")).scalar()
        assert conn.execute(text("SELECT coach_name FROM revenue_details WHERE item_name='場租*10'")).scalar() == "ELSA"
    eng.dispose()


def test_second_import_without_clear_is_refused(client):
    _login(client, "boss")
    r = _post(client, "dryrun", False)
    assert r.status_code == 400 and "已經匯入過" in r.json()["detail"]


def test_contracts_page_filters_and_sessions(client):
    _login(client, "boss")
    open_page = client.get("/admin/contracts/page").text
    assert "#00002" in open_page and "#00004" not in open_page  # 00004 已上完
    done = client.get("/admin/contracts/page?view=done").text
    assert "#00004" in done and "已上完" in done and "2021-10-12" in done
    assert "#00003" in client.get("/admin/contracts/page?view=refunded").text
    hit = client.get("/admin/contracts/page?view=all&q=乙學員").text
    assert "#00002" in hit and "#00001" not in hit
    assert "原表：110.8.32" in client.get("/admin/contracts/page?view=done&q=00001").text


def test_members_and_revenue_pages_render(client):
    _login(client, "boss")
    assert "甲學員" in client.get("/admin/members/page").text
    page = client.get("/admin/revenue/page?year=2025&month=4").text
    assert "114 年 4 月收款明細（共 2 筆）" in page and "甲學員/乙學員" in page and "ELSA" in page
    assert "$20,100" in page
    # 舊課堂報表的上課紀錄算進教練堂數（2021-10：00004 有 12 堂掛在 NICK）
    oct21 = client.get("/admin/revenue/page?ym=2021-10").text
    assert "<td>NICK</td><td>12 堂</td>" in oct21
