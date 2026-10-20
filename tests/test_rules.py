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


def _numbers_in(text: str) -> set[int]:
    """條文中出現的數字：阿拉伯數字，以及接在單位前的中文數字（二十二學分、八十分、四學期、二門）。"""
    numbers = {int(n) for n in re.findall(r"\d+", text)}
    numbers |= {cn2int(n) for n in re.findall(r"([一二三四五六七八九十]+)個?(?:學分|分|學期|門)", text)}
    return numbers


@pytest.mark.parametrize("rule", list_rules(), ids=lambda r: r["rule_id"])
def test_threshold_appears_in_source_article(rule):
    """規則的門檻數字必須真的出現在出處條文裡；有 derivation 的，算式裡每個數字都要出現。"""
    source, article = rule["source"].split()
    text = CHUNKS[f"{source}-{article}"]
    numbers = _numbers_in(text)
    if "derivation" in rule:
        parts = [int(n) for n in re.findall(r"\d+", rule["derivation"])]
        missing = [n for n in parts if n not in numbers]
        assert not missing, f"{rule['rule_id']} 的 derivation 數字 {missing} 不在 {source}{article} 原文中"
    else:
        assert rule["threshold"] in numbers, f"{rule['rule_id']} 的門檻 {rule['threshold']} 不在 {source}{article} 原文中"


def test_all_rules_have_category_and_input():
    for r in list_rules():
        assert r["category"].strip() and r["input"].strip(), r["rule_id"]


def test_derived_threshold_rules():
    assert check_credit_rule("semester_max_credits_minor", 26)["passed"] is True
    assert check_credit_rule("semester_max_credits_minor", 27)["passed"] is False
    assert check_credit_rule("semester_max_credits_double_major_or_honors", 28)["passed"] is True


def test_minor_min_credits():
    r = check_credit_rule("minor_min_credits", 18)
    assert r["passed"] is False
    assert "低於最低 20 學分" in r["explanation"]
    assert "warning" not in r


# 每種 operator：門檻本身是否通過、往「不該通過」的方向差 1 是否不通過
_BOUNDARY = {">=": (True, -1), "<=": (True, +1), ">": (False, +1), "<": (False, -1), "==": (True, +1)}


@pytest.mark.parametrize("rule", list_rules(), ids=lambda r: r["rule_id"])
def test_boundary_values(rule):
    """邊界值：門檻值、門檻 ±1，確認比較方向沒寫反（例如上限誤寫成 >=）。"""
    t, op = rule["threshold"], rule["operator"]
    at_threshold, step = _BOUNDARY[op]
    assert check_credit_rule(rule["rule_id"], t)["passed"] is at_threshold
    if op in (">=", "<="):
        assert check_credit_rule(rule["rule_id"], t + step)["passed"] is False
        assert check_credit_rule(rule["rule_id"], t - step)["passed"] is True
    # 「上限」「至多」類規則必須是 <=，「最低」「至少」「以上」類必須是 >=。
    # 只看括號前的主句，括號裡的補充說明（例如「最高編入三年級」）不算
    d = rule["description"].split("（")[0]
    if any(w in d for w in ("上限", "至多", "最高", "最多")):
        assert op == "<=", f"{rule['rule_id']} 是上限類規則，operator 卻是 {op}"
    if any(w in d for w in ("最低", "至少", "以上")) and not any(w in d for w in ("上限", "最高")):
        assert op == ">=", f"{rule['rule_id']} 是下限類規則，operator 卻是 {op}"


def test_all_rules_verified():
    unverified = [r["rule_id"] for r in list_rules() if not r["verified"]]
    assert not unverified, f"尚未核對的規則：{unverified}（核對後記錄在 docs/規則核對表.md）"


def test_score_unit_rule():
    r = check_credit_rule("officer_exam_military_training_avg_score", 68)
    assert r["passed"] is False
    assert r["explanation"].startswith("你填的 68 分低於最低 70 分的規定")


def test_advance_standing():
    assert check_credit_rule("advance_to_y2_1_min_credits", 40)["passed"] is True
    assert check_credit_rule("advance_to_y3_1_min_credits", 40)["passed"] is False


def _load_with(tmp_path, monkeypatch, extra: str):
    path = tmp_path / "rules.yaml"
    base = """- rule_id: r1
  category: c
  description: d
  input: i
  operator: "<="
  threshold: 26
  unit: 學分
  source: 選課辦法 第三條
  verified: false
"""
    path.write_text(base + extra, encoding="utf-8")
    monkeypatch.setattr(rules, "RULES_PATH", path)
    return rules._load_rules()


def test_derivation_must_equal_threshold(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="不等於 threshold"):
        _load_with(tmp_path, monkeypatch, '  derivation: "22 + 6"\n')


def test_derivation_format(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="格式錯誤"):
        _load_with(tmp_path, monkeypatch, '  derivation: "__import__(\'os\')"\n')


def test_missing_category_rejected(tmp_path, monkeypatch):
    path = tmp_path / "rules.yaml"
    path.write_text("- rule_id: r1\n  description: d\n  input: i\n  operator: '<='\n  threshold: 1\n"
                    "  unit: 學分\n  source: 選課辦法 第三條\n  verified: false\n", encoding="utf-8")
    monkeypatch.setattr(rules, "RULES_PATH", path)
    with pytest.raises(ValueError, match="category"):
        rules._load_rules()
