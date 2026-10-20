"""案件分流：查不到或需要人工判斷的問題，依類別開分流單並存進 logs.db。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from core import db
from core.pii import mask_pii


# 取得專案根目錄下 routing.yaml 的完整路徑。
# __file__ 是目前 Python 檔案的位置；
# 第一個 parent 是 core/，第二個 parent 是專案根目錄。
ROUTING_PATH = Path(__file__).resolve().parent.parent / "routing.yaml"

# 使用者提供的類別不存在時，改用這個預設類別。
FALLBACK_CATEGORY = "綜合服務"

# 每個類別、每個業務窗口都必須有的欄位。
_CATEGORY_FIELDS = ("unit", "scope", "contact")
_WINDOW_FIELDS = ("name", "keywords", "unit", "contact")


# 功能：檢查 routing.yaml 的類別與窗口是否缺欄位、contact 是否還是 TODO。
# 有問題就直接報錯，讓 server 啟動就失敗，而不是等學生被分流時才給出空的聯絡方式。
def _validate(categories: dict[str, dict]) -> None:
    for name, info in categories.items():
        missing = [k for k in _CATEGORY_FIELDS if not info.get(k)]
        if missing:
            raise ValueError(f"routing.yaml 的類別「{name}」缺少欄位：{missing}")
        for w in info.get("windows") or []:
            missing = [k for k in _WINDOW_FIELDS if not w.get(k)]
            if missing:
                raise ValueError(f"routing.yaml 類別「{name}」的窗口 {w.get('name', w)} 缺少欄位：{missing}")
        contacts = [info["contact"]] + [w["contact"] for w in info.get("windows") or []]
        if any("TODO" in str(c) for c in contacts):
            raise ValueError(f"routing.yaml 的類別「{name}」還有 contact 是 TODO")


# 功能：讀取 routing.yaml，取得所有分流類別及其承辦資訊。
# 同時確認設定中存在「綜合服務」，讓未知類別有預設去處。
# 回傳：以類別名稱為 key、承辦資訊字典為 value 的字典。
# 例如：{"教務": {"unit": "教務處", "windows": [...], ...}, ...}
def _load_categories() -> dict[str, dict]:
    # 以 UTF-8 讀取 YAML，再轉成 Python 資料結構。
    # 如果 YAML 是空檔案，safe_load() 會回傳 None，改用空字典。
    data = yaml.safe_load(
        ROUTING_PATH.read_text(encoding="utf-8")
    ) or {}

    # 取出 YAML 中 categories 欄位的內容。
    # 欄位不存在或內容為空時，改用空字典。
    categories = data.get("categories") or {}

    # 確認預設類別存在，避免後續處理未知類別時無法取得承辦資訊。
    if FALLBACK_CATEGORY not in categories:
        raise ValueError(
            f"routing.yaml 必須有「{FALLBACK_CATEGORY}」類別"
        )

    _validate(categories)
    return categories


# 模組被載入時就讀取一次設定，後續函式共用這份資料。
# 修改 routing.yaml 後，需要重新載入模組或重新啟動程式才會更新。
_CATEGORIES = _load_categories()


# 功能：取得目前設定中所有可使用的分流類別名稱。
# 回傳：類別名稱清單，例如 ["教務", "學務", "總務", "綜合服務"]。
def list_categories() -> list[str]:
    # 將字典轉成 list，會取得字典的 keys，也就是各類別名稱。
    return list(_CATEGORIES)


# 功能：在類別的業務窗口中，找出摘要提到的那一個。
# 依 routing.yaml 的順序比對 keywords，摘要含任一關鍵字就回傳該窗口；都沒對到回傳 None。
# 例如類別「學務」、摘要「宿舍什麼時候可以申請」→ 宿舍服務窗口（學務處宿管中心）。
def _match_window(category: str, summary: str) -> dict | None:
    for w in _CATEGORIES[category].get("windows") or []:
        if any(k in summary for k in w["keywords"]):
            return w
    return None


# 功能：根據類別建立分流單，將遮蔽個資後的案件摘要存入資料庫，
# 並回傳分流單號、承辦單位、業務範圍、聯絡方式及下一步說明。
# 有對到業務窗口時，承辦單位與聯絡方式用窗口的（例如「學務處宿管中心 分機 82076」）；
# 沒對到就用類別層級的預設單位與總機。
# 注意：這個函式只建立本地資料庫紀錄，沒有寄信或通知承辦單位。
def route_case(category: str, summary: str) -> dict:
    # 如果傳入的類別不在設定中，改用預設類別。
    if category not in _CATEGORIES:
        category = FALLBACK_CATEGORY

    # 取得該類別的承辦資訊，包含 unit、scope、contact 等欄位。
    info = _CATEGORIES[category]
    # 先遮蔽個資：比對窗口與寫入資料庫都用遮蔽後的摘要。
    masked = mask_pii(summary)
    # 找具體業務窗口；找不到就用類別預設的單位與聯絡方式。
    window = _match_window(category, masked)
    unit = window["unit"] if window else info["unit"]
    contact = window["contact"] if window else info["contact"]

    # 取得 SQLite 資料庫連線。
    conn = db.get_conn()

    try:
        # 使用資料庫交易：
        # 區塊正常結束時提交變更；發生例外時回滾交易。
        # with conn 不會自動關閉連線，因此仍需 finally 中的 close()。
        with conn:
            # 新增案件紀錄。
            # ? 是 SQL 參數佔位符，實際資料由第二個參數傳入。
            cur = conn.execute(
                "INSERT INTO cases (ts, category, unit, summary) "
                "VALUES (?, ?, ?, ?)",
                (
                    # 產生精確到秒的時間字串，例如 2026-10-20T09:28:14。
                    datetime.now().isoformat(timespec="seconds"),

                    # 存入確認後的分流類別。
                    category,

                    # 存入承辦單位（有對到窗口就是窗口的單位）。
                    unit,

                    # 存入遮蔽個資後的摘要。
                    masked,
                ),
            )

            # lastrowid 是剛新增資料的資料列 ID。
            # :04d 表示以十進位整數顯示，至少四位，不足時在左側補 0。
            # 例如 ID 為 1，單號就是 A0001；超過四位時不會截斷。
            case_no = f"A{cur.lastrowid:04d}"

            # 新增後才取得 ID，因此再更新同一筆資料的 case_no 欄位。
            conn.execute(
                "UPDATE cases SET case_no = ? WHERE id = ?",
                (case_no, cur.lastrowid),
            )

    finally:
        # 不論交易成功或發生例外，都關閉資料庫連線。
        conn.close()

    # 回傳分流結果，供呼叫端顯示給使用者。
    # 分流單只存在本地資料庫、不會自動送到承辦單位，
    # 所以 next_step 要請學生自己聯絡，不能寫成「將由某單位處理」。
    return {
        "case_no": case_no,
        "category": category,
        "window": window["name"] if window else None,
        "unit": unit,
        "scope": info["scope"],
        "contact": contact,
        "next_step": (
            f"已記錄分流單 {case_no}。"
            f"請聯絡{unit}（{contact}），"
            "並提供這個單號以便承辦人員了解你的問題。"
        ),
    }