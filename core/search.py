"""規章條文檢索：BM25 + 字元 bigram 斷詞。

模組載入時讀一次 kb/chunks.json 並建好索引，之後每次查詢只算分數。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

CHUNKS_PATH = Path(__file__).resolve().parent.parent / "kb" / "chunks.json"
MIN_SCORE = 1.0
# 條文至少要包含查詢中這個比例的 token。只靠分數門檻擋不住「學生餐廳營業時間」這種
# 只命中「學生」「時間」等常見詞的查詢（4.94 分），卻會擋掉「轉系」（3.02 分）。
MIN_COVERAGE = 0.5

# 連續的中文字一段、連續的英數字一段；標點與空白都當分隔
_CJK_RUN = r"[㐀-鿿豈-﫿]+"
_ALNUM_RUN = r"[A-Za-z0-9]+"
_TOKEN_RE = re.compile(f"{_CJK_RUN}|{_ALNUM_RUN}")


def tokenize(text: str) -> list[str]:
    """中文切字元 bigram（「停修課程」→ 停修、修課、課程），英數字串整串當一個 token。

    bigram 不跨越標點：「學分，課程」不會產生「分課」。單獨一個中文字就用那個字本身。
    """
    tokens: list[str] = []
    for run in _TOKEN_RE.findall(text):
        if run[0].isascii():
            tokens.append(run.lower())
        elif len(run) == 1:
            tokens.append(run)
        else:
            tokens += [run[i:i + 2] for i in range(len(run) - 1)]
    return tokens


# 口語問句裡的疑問詞／語助詞。只在「查詢」時拿掉（換成空白，bigram 不會跨過去），
# 否則「轉系要什麼條件」會因為「什麼」「麼條」等 bigram 拉低覆蓋率而被擋掉。
# 刻意不放單字「要」「能」等，避免拆壞「要件」「功能」這類詞。
QUERY_STOPWORDS = ("可不可以", "能不能", "是不是", "請問", "想問", "什麼", "怎麼", "怎樣", "如何",
                   "可以", "是否", "哪些", "哪裡", "多少", "嗎", "呢", "吗")
_STOPWORD_RE = re.compile("|".join(QUERY_STOPWORDS))


def _load_chunks() -> list[dict]:
    if not CHUNKS_PATH.exists():
        raise FileNotFoundError(f"找不到 {CHUNKS_PATH}，請先執行 python scripts/ingest.py")
    chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
    if not chunks:
        raise ValueError(f"{CHUNKS_PATH} 是空的，請檢查 scripts/ingest.py 的輸出")
    return chunks


_CHUNKS = _load_chunks()
_CORPUS = [tokenize(c["source"] + c["article"] + c["text"]) for c in _CHUNKS]
_BM25 = BM25Okapi(_CORPUS)
_TOKEN_SETS = [set(doc) for doc in _CORPUS]


def search_regulations(query: str, top_k: int = 3) -> list[dict]:
    """用關鍵字搜尋世新大學規章條文，回傳最相關的條文段落與出處。

    Args:
        query: 查詢文字，例如「停修」「轉系 申請期限」。
        top_k: 最多回傳幾筆，預設 3。

    Returns:
        依 score 由高到低排序的 list，每筆含 id、source（辦法名稱）、article（條號）、
        text（條文全文）、score（BM25 分數）。分數低於 MIN_SCORE、或條文涵蓋的查詢詞
        少於 MIN_COVERAGE 的不回傳；找不到相關條文時回傳空 list。
    """
    tokens = tokenize(_STOPWORD_RE.sub(" ", query))
    if not tokens or top_k <= 0:
        return []
    query_set = set(tokens)
    scores = _BM25.get_scores(tokens)
    ranked = sorted(range(len(_CHUNKS)), key=lambda i: scores[i], reverse=True)
    results = []
    for i in ranked:
        if len(results) >= top_k or scores[i] < MIN_SCORE:
            break
        if len(query_set & _TOKEN_SETS[i]) / len(query_set) < MIN_COVERAGE:
            continue
        c = _CHUNKS[i]
        results.append({
            "id": c["id"],
            "source": c["source"],
            "article": c["article"],
            "text": c["text"],
            "score": round(float(scores[i]), 4),
        })
    return results
