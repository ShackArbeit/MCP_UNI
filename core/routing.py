"""案件分流：查不到或需要人工判斷的問題，依類別開分流單並存進 logs.db。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from core import db
from core.pii import mask_pii

ROUTING_PATH = Path(__file__).resolve().parent.parent / "routing.yaml"
FALLBACK_CATEGORY = "綜合服務"


def _load_categories() -> dict[str, dict]:
    data = yaml.safe_load(ROUTING_PATH.read_text(encoding="utf-8")) or {}
    categories = data.get("categories") or {}
    if FALLBACK_CATEGORY not in categories:
        raise ValueError(f"routing.yaml 必須有「{FALLBACK_CATEGORY}」類別")
    return categories


_CATEGORIES = _load_categories()


def list_categories() -> list[str]:
    """列出所有分流類別名稱。"""
    return list(_CATEGORIES)


def route_case(category: str, summary: str) -> dict:
    """依類別開一張分流單，回傳單號與承辦單位。

    Args:
        category: 分流類別（教務／學務／總務／綜合服務）；不在 routing.yaml 的一律歸到「綜合服務」。
        summary: 問題摘要；存進資料庫前會先遮蔽個資。

    Returns:
        {"case_no", "unit", "scope", "contact", "next_step"}，case_no 格式為 A0001、A0002……
    """
    if category not in _CATEGORIES:
        category = FALLBACK_CATEGORY
    info = _CATEGORIES[category]

    conn = db.get_conn()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO cases (ts, category, unit, summary) VALUES (?, ?, ?, ?)",
                (datetime.now().isoformat(timespec="seconds"), category, info["unit"], mask_pii(summary)),
            )
            case_no = f"A{cur.lastrowid:04d}"
            conn.execute("UPDATE cases SET case_no = ? WHERE id = ?", (case_no, cur.lastrowid))
    finally:
        conn.close()

    return {
        "case_no": case_no,
        "unit": info["unit"],
        "scope": info["scope"],
        "contact": info["contact"],
        "next_step": f"已幫你開立分流單 {case_no}，將由{info['unit']}協助處理；聯絡承辦單位時請提供這個單號。",
    }
