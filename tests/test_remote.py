"""遠端管理介面（店家總覽用）。需要 TEST_DATABASE_URL 指向「可被清空的測試資料庫」，沒設定就略過。

執行：TEST_DATABASE_URL=postgresql+psycopg2://... python -m pytest tests/test_remote.py
"""

import os
from datetime import date, time

import pytest

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="未設定 TEST_DATABASE_URL")

R, W = "r" * 40, "w" * 40


@pytest.fixture(scope="module")
def client():
    os.environ["DATABASE_URL"] = URL
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    eng = create_engine(URL)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    command.upgrade(Config("alembic.ini"), "head")

    from fastapi.testclient import TestClient

    from app.main import app

    with eng.begin() as conn:
        conn.execute(text("INSERT INTO members (id, member_no, name, role, is_active) VALUES (1, 'M001', '王小美', 'student', true), (2, 'C001', '阿哲教練', 'coach', true)"))
        conn.execute(text("INSERT INTO admin_users (id, username, password_hash, role, is_active) VALUES (1, 'boss', 'x', 'super_admin', true)"))
        conn.execute(text("INSERT INTO venue_rental_coaches (id, name, is_active) VALUES (1, 'ELSA', true)"))
        conn.execute(text(
            "INSERT INTO contracts (id, coach_id, course_type, purchase_date, unit_price, total_sessions, used_sessions, status) VALUES "
            "(1, 2, 'strength', '2030-01-05', 1500, 10, 0, 'active'), (2, 2, 'strength', '2029-12-20', 1500, 10, 0, 'active')"))
        for i, (d, st) in enumerate([("2030-01-06", "booked"), ("2030-01-07", "completed"), ("2030-01-08", "cancelled"), ("2030-02-01", "booked")], start=1):
            conn.execute(text("INSERT INTO bookings (id, coach_id, contract_id, slot_date, slot_start_time, area, status) VALUES (:i, 2, 1, :d, :t, 'strength', :s)"),
                         {"i": i, "d": d, "t": time(9 + i), "s": st})
        conn.execute(text("INSERT INTO venue_bookings (venue_coach_id, customer_name, party_size, slot_date, slot_start_time, slot_number, area, status) VALUES "
                          "(1, '客A', 1, '2030-01-10', '10:00', 1, 'strength', 'booked'), (1, '客B', 2, '2030-01-11', '10:00', 1, 'strength', 'cancelled')"))
        conn.execute(text("INSERT INTO revenue_details (entry_date, item_category, item_name, payment_method, amount, entered_by_id) VALUES "
                          "('2030-01-05', 'coaching', '教練課 10 堂', '現金', 15000, 1), ('2030-01-20', 'beverage', '高蛋白', '現金', 120.5, 1), ('2030-02-01', 'beverage', '水', '現金', 20, 1)"))
    eng.dispose()

    os.environ.pop("REMOTE_READ_KEY", None)
    os.environ.pop("REMOTE_WRITE_KEY", None)
    with TestClient(app) as c:
        yield c


def auth(key):
    return {"Authorization": f"Bearer {key}"}


def test_no_keys_means_404(client):
    assert client.get("/api/remote/stats").status_code == 404
    os.environ["REMOTE_READ_KEY"] = "short"
    assert client.get("/api/remote/stats", headers=auth("short")).status_code == 404


def test_keys_and_stats(client):
    os.environ["REMOTE_READ_KEY"], os.environ["REMOTE_WRITE_KEY"] = R, W
    r = client.get("/api/remote/stats?month=2030-01")
    assert r.status_code == 401 and r.json() == {"error": "金鑰不正確"}
    assert client.get("/api/remote/stats?month=2030-01", headers=auth("x" * 40)).status_code == 401
    r = client.get("/api/remote/stats?month=2030-01", headers=auth(R))
    assert r.status_code == 200
    body = r.json()
    assert body["system"] == "gym" and body["month"] == "2030-01"
    assert body["bookings"] == {"total": 2, "cancelled": 1}
    assert body["gym"] == {"courseBookings": 2, "courseCancelled": 1, "venueBookings": 1, "venueCancelled": 1, "newContracts": 1, "revenue": 15120.5}
    assert client.get("/api/remote/stats?month=2030-13", headers=auth(R)).json() == {"error": "月份格式不正確"}
    assert client.get("/api/remote/stats", headers=auth(W)).status_code == 200


def test_config(client):
    r = client.get("/api/remote/config", headers=auth(R))
    assert r.json() == {"system": "gym", "modules": {}}


def test_backup_needs_write_key_and_changes_nothing(client):
    r = client.get("/api/remote/backup", headers=auth(R))
    assert r.status_code == 403 and r.json() == {"error": "下載備份需要寫入金鑰"}
    r = client.get("/api/remote/backup", headers=auth(W))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    tables = r.json()["tables"]
    for name in ["members", "contracts", "bookings", "venue_bookings", "revenue_details", "admin_users", "alembic_version"]:
        assert name in tables
    assert len(tables["bookings"]) == 4
    assert tables["revenue_details"][1]["amount"] == "120.50"
    assert tables["bookings"][0]["slot_date"] == "2030-01-06"
    again = client.get("/api/remote/backup", headers=auth(W)).json()["tables"]
    assert again == tables


def test_too_many_failures_locks_out(client):
    from app.routers import remote

    remote._fails.clear()
    for _ in range(10):
        client.get("/api/remote/config", headers=auth("bad" * 20))
    assert client.get("/api/remote/config", headers=auth(R)).status_code == 429
    remote._fails.clear()
