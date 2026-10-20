import json
import sqlite3

import pytest

from core import db
from core.logging_db import log_interaction
from core import routing
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
    assert r["window"] == "課程與選課"
    assert r["unit"] == "教務處課務窗口"
    assert "curr001@mail.shu.edu.tw" in r["contact"]
    assert "停修" in r["scope"]
    assert set(r) == {"case_no", "category", "window", "unit", "scope", "contact", "next_step"}
    assert "A0001" in r["next_step"] and r["contact"] in r["next_step"]
    assert _rows(temp_db, "SELECT case_no, category, unit, status FROM cases") == [
        ("A0001", "教務", "教務處課務窗口", "open")
    ]


@pytest.mark.parametrize("category, summary, window, contact_part", [
    ("學務", "學生詢問宿舍什麼時候可以申請", "宿舍服務", "82076"),
    ("學務", "清寒獎學金要怎麼申請", "獎助學金", "82080"),
    ("學務", "想辦理兵役緩徵", "學生兵役", "houct@"),
    ("總務", "機車停車證要去哪裡辦", "停車業務", "82115"),
    ("總務", "宿舍冷氣卡要怎麼儲值", "冷氣卡儲值", "82128"),   # 要排在「空調及消防設施」前面
    ("總務", "教室冷氣壞了", "空調及消防設施", "82106"),
    ("教務", "專案服役要怎麼申請", "專案服役", "82044"),
    ("國際兩岸", "港澳生居留證到期", "入臺證與居留證", "63831"),
])
def test_window_matching(category, summary, window, contact_part):
    r = route_case(category, summary)
    assert r["window"] == window
    assert contact_part in r["contact"]


def test_no_window_uses_category_default():
    r = route_case("總務", "學餐晚上開到幾點")
    assert r["window"] is None
    assert r["unit"] == "總務處"
    assert "(02)2236-8225" in r["contact"]


def test_next_step_does_not_claim_forwarding():
    # 分流單不會自動送到承辦單位，不能讓學生以為有人會主動聯絡
    r = route_case("學務", "宿舍申請")
    assert "請聯絡" in r["next_step"]
    assert "將由" not in r["next_step"]


def test_routing_yaml_has_no_todo():
    for name in routing.list_categories():
        info = routing._CATEGORIES[name]
        assert "TODO" not in info["contact"], name
        for w in info.get("windows") or []:
            assert "TODO" not in w["contact"], (name, w["name"])


def test_todo_contact_rejected(tmp_path, monkeypatch):
    path = tmp_path / "routing.yaml"
    path.write_text("categories:\n  綜合服務:\n    unit: 總機\n    scope: 其他\n    contact: TODO\n", encoding="utf-8")
    monkeypatch.setattr(routing, "ROUTING_PATH", path)
    with pytest.raises(ValueError, match="TODO"):
        routing._load_categories()


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
