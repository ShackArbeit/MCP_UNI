"""個資遮蔽：寫進 log 或分流單之前，先把 Email、身分證、手機、學號換成標記。"""
from __future__ import annotations

import re

# 前後不能緊鄰英數字，避免從較長的字串中間切出一段（中文字旁邊可以直接相連）
_L = r"(?<![A-Za-z0-9])"
_R = r"(?![A-Za-z0-9])"

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
NATIONAL_ID_PATTERN = re.compile(_L + r"[A-Za-z][12]\d{8}" + _R)
# 0912345678、0912-345-678、0912 345 678
PHONE_PATTERN = re.compile(_L + r"09\d{2}([-\s]?)\d{3}\1\d{3}" + _R)
# 待向校方確認實際學號格式
# 目前假設：A／B／N 開頭 + 9 位數字，或純 9 位數字
STUDENT_ID_PATTERN = re.compile(_L + r"(?:[ABNabn]\d{9}|\d{9})" + _R)

# 身分證字首字母對應的兩位數（內政部編碼）
_ID_LETTER_CODES = dict(zip("ABCDEFGHJKLMNPQRSTUVXYWZIO", range(10, 36)))


def _is_valid_national_id(s: str) -> bool:
    """檢查身分證字號的檢查碼。學號（例如 A110123456）長得和身分證一樣，只能靠檢查碼區分。"""
    code = _ID_LETTER_CODES[s[0].upper()]
    digits = [code // 10, code % 10] + [int(c) for c in s[1:]]
    weights = [1, 9, 8, 7, 6, 5, 4, 3, 2, 1, 1]
    return sum(d * w for d, w in zip(digits, weights)) % 10 == 0


def mask_pii(text: str) -> str:
    """遮蔽文字中的個資，回傳遮蔽後的文字。

    依序處理：Email → [EMAIL]、身分證字號 → [ID]、手機 → [PHONE]、學號 → [STUDENT_ID]。
    身分證要通過檢查碼才算；不通過的（例如 A110123456）留給學號規則判斷。
    「16 學分」「110 學年度」「2026 年」這類數字不會被遮蔽。
    """
    text = EMAIL_PATTERN.sub("[EMAIL]", text)
    text = NATIONAL_ID_PATTERN.sub(
        lambda m: "[ID]" if _is_valid_national_id(m.group()) else m.group(), text
    )
    text = PHONE_PATTERN.sub("[PHONE]", text)
    text = STUDENT_ID_PATTERN.sub("[STUDENT_ID]", text)
    return text
