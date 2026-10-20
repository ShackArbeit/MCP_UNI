"""學分門檻判斷：規則寫在 rules.yaml，比大小由 Python 計算，不讓 LLM 自己比。"""
from __future__ import annotations

import operator
import re
from pathlib import Path

import yaml

RULES_PATH = Path(__file__).resolve().parent.parent / "rules.yaml"

# rules.yaml 裡 operator 字串 → 實際做比較的 Python 函式
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
# 每條規則都必須有的欄位
_REQUIRED = ("rule_id", "category", "description", "input", "operator", "threshold", "unit", "source", "verified")
# derivation 只允許「整數 + 整數 + …」，例如 "22 + 4"
_DERIVATION_RE = re.compile(r"^\s*\d+(?:\s*\+\s*\d+)*\s*$")
# verified: false 的規則，判斷結果會附上這句警告
UNVERIFIED_WARNING = "此規則尚未經人工確認"


def _load_rules() -> dict[str, dict]:
    """讀取 rules.yaml 並檢查格式，回傳以 rule_id 為 key 的規則字典。

    主要功能：在模組載入時把所有規則讀進記憶體，並提早擋下寫錯的規則，
    讓 server 啟動就失敗，而不是等到學生問問題時才出錯。檢查項目：
    - 必填欄位（_REQUIRED）都有
    - operator 是支援的比較符號（_OPERATORS）
    - 有 derivation 時，格式只能是「整數 + 整數」，且加總要等於 threshold
    - rule_id 沒有重複

    Raises:
        ValueError: 任何一項檢查不通過，訊息會指出是哪條規則、哪裡錯。
    """
    rules = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or []
    by_id: dict[str, dict] = {}
    for r in rules:
        # 檢查必填欄位
        missing = [k for k in _REQUIRED if k not in r]
        if missing:
            raise ValueError(f"rules.yaml 的規則 {r.get('rule_id', r)} 缺少欄位：{missing}")
        # 檢查比較符號
        if r["operator"] not in _OPERATORS:
            raise ValueError(f"規則 {r['rule_id']} 的 operator「{r['operator']}」不支援，可用：{list(_OPERATORS)}")
        # 檢查推算門檻：例如輔系生上限 26 = 22 + 4，算式要能對回 threshold
        if "derivation" in r:
            d = str(r["derivation"])
            if not _DERIVATION_RE.match(d):
                raise ValueError(f"規則 {r['rule_id']} 的 derivation「{d}」格式錯誤，只能是「整數 + 整數」")
            if sum(int(n) for n in re.findall(r"\d+", d)) != r["threshold"]:
                raise ValueError(f"規則 {r['rule_id']} 的 derivation「{d}」算出來不等於 threshold {r['threshold']}")
        # 檢查 rule_id 不重複
        if r["rule_id"] in by_id:
            raise ValueError(f"rules.yaml 有重複的 rule_id：{r['rule_id']}")
        by_id[r["rule_id"]] = r
    return by_id


# 模組載入時讀一次，之後每次判斷都直接查這個字典
_RULES = _load_rules()


def _fmt(n: float) -> str:
    """把數字轉成說明文字用的字串：整數不顯示小數點。

    主要功能：讓 explanation 讀起來自然，例如寫「16 學分」而不是「16.0 學分」。
    16.0 → "16"，16.5 → "16.5"。
    """
    return str(int(n)) if float(n).is_integer() else str(n)


def list_rules() -> list[dict]:
    """列出所有可用的規則，依 rules.yaml 的順序排列。

    主要功能：讓 server.py 的 list_credit_rules 工具把規則清單交給 LLM，
    LLM 依學生身分挑出正確的 rule_id 後，再呼叫 check_credit_rule。
    每筆含 rule_id、分類、說明、value 要填什麼、門檻、出處、是否已核對。
    回傳的是複本，呼叫端修改不會影響 _RULES。
    """
    return [dict(r) for r in _RULES.values()]


def check_credit_rule(rule_id: str, value: float) -> dict:
    """判斷一個數值是否符合某條規則，回傳是否通過、給學生看的中文說明與出處。

    主要功能：數字比大小一律由程式計算，避免 LLM 自己比錯（例如答出「16 > 22」）。
    流程：用 rule_id 找到規則 → 用 operator 比較 value 與 threshold →
    組出「你填的 14 學分低於最低 16 學分的規定（…）」這類說明 → 未核對的規則附上警告。

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
    # 實際比大小：例如 operator ">=" 就是 value >= threshold
    passed = _OPERATORS[op](value, threshold)
    # 依通過與否挑說法，例如「低於最低 16 學分」
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
