"""學分門檻判斷：規則寫在 rules.yaml，比大小由 Python 計算，不讓 LLM 自己比。"""
from __future__ import annotations

import operator
from pathlib import Path

import yaml

RULES_PATH = Path(__file__).resolve().parent.parent / "rules.yaml"

_OPERATORS = {
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "==": operator.eq,
}
# (通過時的說法, 不通過時的說法)
_PHRASES = {
    ">=": ("符合最低 {t} {u}", "低於最低 {t} {u}"),
    "<=": ("未超過上限 {t} {u}", "超過上限 {t} {u}"),
    ">": ("高於 {t} {u}", "未高於 {t} {u}"),
    "<": ("低於 {t} {u}", "未低於 {t} {u}"),
    "==": ("等於 {t} {u}", "不等於 {t} {u}"),
}
_REQUIRED = ("rule_id", "description", "operator", "threshold", "unit", "source", "verified")
UNVERIFIED_WARNING = "此規則尚未經人工確認"


def _load_rules() -> dict[str, dict]:
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or []
    by_id: dict[str, dict] = {}
    for r in rules:
        missing = [k for k in _REQUIRED if k not in r]
        if missing:
            raise ValueError(f"rules.yaml 的規則 {r.get('rule_id', r)} 缺少欄位：{missing}")
        if r["operator"] not in _OPERATORS:
            raise ValueError(f"規則 {r['rule_id']} 的 operator「{r['operator']}」不支援，可用：{list(_OPERATORS)}")
        if r["rule_id"] in by_id:
            raise ValueError(f"rules.yaml 有重複的 rule_id：{r['rule_id']}")
        by_id[r["rule_id"]] = r
    return by_id


_RULES = _load_rules()


def _fmt(n: float) -> str:
    """16.0 → "16"，16.5 → "16.5"。"""
    return str(int(n)) if float(n).is_integer() else str(n)


def list_rules() -> list[dict]:
    """列出所有可用的學分規則（rule_id、說明、門檻、出處、是否已人工確認）。"""
    return [dict(r) for r in _RULES.values()]


def check_credit_rule(rule_id: str, value: float) -> dict:
    """用程式判斷一個數值是否符合學分規則，避免 LLM 自己比大小出錯。

    Args:
        rule_id: 規則代號，可用 list_rules() 查詢，例如 "semester_min_credits_y1_3"。
        value: 要檢查的數值，例如這學期修的學分數。

    Returns:
        {"rule_id", "passed", "value", "operator", "threshold", "unit", "explanation", "source"}；
        規則尚未人工確認時多一個 "warning"。

    Raises:
        ValueError: rule_id 不存在（訊息中列出所有可用的 rule_id）。
    """
    rule = _RULES.get(rule_id)
    if rule is None:
        raise ValueError(f"找不到規則「{rule_id}」，可用的 rule_id：{', '.join(_RULES)}")

    op, threshold, unit = rule["operator"], rule["threshold"], rule["unit"]
    passed = _OPERATORS[op](value, threshold)
    phrase = _PHRASES[op][0 if passed else 1].format(t=_fmt(threshold), u=unit)
    result = {
        "rule_id": rule_id,
        "passed": passed,
        "value": value,
        "operator": op,
        "threshold": threshold,
        "unit": unit,
        "explanation": f"你填的 {_fmt(value)} {unit}{phrase}的規定（{rule['description']}）",
        "source": rule["source"],
    }
    if not rule["verified"]:
        result["warning"] = UNVERIFIED_WARNING
    return result
