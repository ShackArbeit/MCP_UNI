"""互動紀錄：每次問答都寫進 logs.db 的 interactions 表，供成效指標與補洞報告使用。"""
from __future__ import annotations

import json
from datetime import datetime

from core import db
from core.pii import mask_pii


def log_interaction(question: str, answered: bool, sources: list[str], latency_ms: int = 0) -> None:
    """記錄一次問答。

    Args:
        question: 使用者的問題；存進資料庫前會先遮蔽個資。
        answered: 是否有根據條文回答（轉分流或答不出來為 False）。
        sources: 引用的出處，例如 ["選課辦法 第七條"]；存成 JSON 字串。
        latency_ms: 回答耗時（毫秒），不知道就填 0。
    """
    conn = db.get_conn()
    try:
        with conn:
            conn.execute(
                "INSERT INTO interactions (ts, question, answered, sources, latency_ms) VALUES (?, ?, ?, ?, ?)",
                (
                    datetime.now().isoformat(timespec="seconds"),
                    mask_pii(question),
                    int(answered),
                    json.dumps(sources, ensure_ascii=False),
                    int(latency_ms),
                ),
            )
    finally:
        conn.close()
