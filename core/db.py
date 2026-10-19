"""SQLite 儲存：互動紀錄（interactions）與分流單（cases），檔案在專案根目錄的 logs.db。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

# 測試時用 monkeypatch 改成 tmp_path 底下的檔案，不可以寫入真正的 logs.db
DB_PATH = Path(__file__).resolve().parent.parent / "logs.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY,
    ts TEXT,
    question TEXT,
    answered INTEGER,
    sources TEXT,
    latency_ms INTEGER,
    is_demo INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY,
    case_no TEXT,
    ts TEXT,
    category TEXT,
    unit TEXT,
    summary TEXT,
    status TEXT DEFAULT 'open',
    is_demo INTEGER DEFAULT 0
);
"""


def init_db(conn: sqlite3.Connection) -> None:
    """建立 interactions 與 cases 兩張表（已存在就略過）。"""
    conn.executescript(_SCHEMA)


def get_conn() -> sqlite3.Connection:
    """開啟 DB_PATH 的連線，第一次連線時自動建表。用完請 close()。"""
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    return conn
