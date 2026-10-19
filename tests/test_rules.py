import json
import re
from pathlib import Path

import pytest

from core import rules
from core.rules import check_credit_rule, list_rules

CHUNKS = {c["id"]: c["text"] for c in json.loads(
    (Path(__file__).resolve().parent.parent / "kb" / "chunks.json").read_text(encoding="utf-8")
)}
CN_DIGITS = "零一二三四五六七八九"


def cn2int(s: str) -> int:
    """中文數字轉整數（到 99），例如 二十二 → 22、十六 → 16、八 → 8。"""
    if "十" not in s:
        return CN_DIGITS.index(s)
    tens, _, ones = s.partition("十")
    return (CN_DIGITS.index(tens) if tens else 1) * 10 + (CN_DIGITS.index(ones) if ones else 0)


def test_below_minimum_fails():
    r = check_credit_rule("semester_min_credits_y1_3", 14)
    assert r["passed"] is False
    assert r["explanation"].startswith("你填的 14 學分低於最低 16 學分的規定")
    # 一般學生的下限出自選課辦法第三條，不是專案服役辦法
    assert r["source"] == "選課辦法 第三條"


def test_minimum_boundary_passes():
    assert check_credit_rule("semester_min_credits_y1_3", 16)["passed"] is True


def test_above_maximum_fails():
    r = check_credit_rule("semester_max_credits", 26)
    assert r["passed"] is False
    assert "超過上限 22 學分" in r["explanation"]
    assert r["source"] == "選課辦法 第三條"


def test_general_max_is_22_not_25():
    # 一般學生修 24 學分超過選課辦法的 22 學分上限；專案役男的 25 學分上限則可以
    assert check_credit_rule("semester_max_credits", 22)["passed"] is True
    assert check_credit_rule("semester_max_credits", 24)["passed"] is False
    assert check_credit_rule("semester_max_credits_military", 24)["passed"] is True


def test_military_max_credits():
    r = check_credit_rule("semester_max_credits_military", 26)
    assert r["passed"] is False
    assert "超過上限 25 學分" in r["explanation"]
    assert r["source"] == "專案服役彈性修業辦法 第四點"


def test_unknown_rule_lists_available_ids():
    with pytest.raises(ValueError) as e:
        check_credit_rule("no_such_rule", 10)
    for rule_id in ("semester_min_credits_y1_3", "semester_max_credits",
                    "semester_max_credits_military",
                    "semester_min_credits_y4", "military_training_max_credits"):
        assert rule_id in str(e.value)


def test_min_credits_y4_source():
    assert check_credit_rule("semester_min_credits_y4", 8)["source"] == "選課辦法 第三條"


def test_result_fields():
    r = check_credit_rule("semester_min_credits_y4", 8)
    assert set(r) == {"rule_id", "passed", "value", "operator", "threshold",
                      "unit", "explanation", "source"}


def test_unverified_rule_has_warning(monkeypatch):
    fake = dict(rules._RULES["semester_min_credits_y4"], verified=False)
    monkeypatch.setitem(rules._RULES, "semester_min_credits_y4", fake)
    assert check_credit_rule("semester_min_credits_y4", 8)["warning"] == rules.UNVERIFIED_WARNING


@pytest.mark.parametrize("rule", list_rules(), ids=lambda r: r["rule_id"])
def test_threshold_appears_in_source_article(rule):
    """規則的門檻數字必須真的出現在出處條文裡（阿拉伯數字或中文數字）。"""
    source, article = rule["source"].split()
    text = CHUNKS[f"{source}-{article}"]
    t = rule["threshold"]
    numbers = {int(n) for n in re.findall(r"\d+", text)}
    numbers |= {cn2int(n) for n in re.findall(r"([一二三四五六七八九十]+)個?學分", text)}
    assert t in numbers, f"{rule['rule_id']} 的門檻 {t} 不在 {source}{article} 原文中"
