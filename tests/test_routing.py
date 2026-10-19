import json
import sqlite3

import pytest

from core import db
from core.logging_db import log_interaction
from core.routing import route_case


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """每個測試都用暫存的資料庫，不寫入真正的 logs.db。"""
    path = tmp_path / "test_logs.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def _rows(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_route_known_category(temp_db):
    r = route_case("教務", "想申請超修學分")
    assert r["case_no"] == "A0001"
    assert r["unit"] == "教務處註冊課務組"
    assert "停修" in r["scope"]
    assert set(r) == {"case_no", "unit", "scope", "contact", "next_step"}
    assert "A0001" in r["next_step"]
    assert _rows(temp_db, "SELECT case_no, category, unit, status FROM cases") == [
        ("A0001", "教務", "教務處註冊課務組", "open")
    ]


def test_unknown_category_falls_back(temp_db):
    r = route_case("圖書館", "借書可以借多久")
    assert r["unit"] == "學校總機轉接"
    assert _rows(temp_db, "SELECT category FROM cases") == [("綜合服務",)]


def test_summary_phone_is_masked(temp_db):
    route_case("學務", "宿舍申請問題，手機 0912-345-678 請回電")
    (summary,), = _rows(temp_db, "SELECT summary FROM cases")
    assert "0912" not in summary
    assert "[PHONE]" in summary


def test_case_no_increments():
    nos = [route_case("總務", f"報修 {i}")["case_no"] for i in range(3)]
    assert nos == ["A0001", "A0002", "A0003"]


def test_real_db_untouched(temp_db):
    route_case("教務", "測試")
    assert temp_db.exists()
    assert db.DB_PATH == temp_db


def test_log_interaction_masks_and_serializes(temp_db):
    log_interaction("學號 A110123456 想問停修", True, ["選課辦法 第七條"], 120)
    (question, answered, sources, latency), = _rows(
        temp_db, "SELECT question, answered, sources, latency_ms FROM interactions"
    )
    assert "A110123456" not in question
    assert answered == 1
    assert json.loads(sources) == ["選課辦法 第七條"]
    assert latency == 120
