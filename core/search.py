"""規章條文檢索：BM25（字元 bigram）排序 + jieba 斷詞算覆蓋率。

模組載入時讀一次 kb/chunks.json 並建好索引，之後每次查詢只算分數。

兩種斷詞各管一件事：
- 排序用字元 bigram：不怕 jieba 切錯，條文裡的詞一定找得到。
- 覆蓋率用 jieba 斷出的「詞」：bigram 會把口語切出「費會」「會退」這類跨詞雜訊，
  拉低覆蓋率（「停修後學費會退嗎」正確條文排第 1 卻只有 36%）；用詞計算就沒有這個問題，
  而「宿舍」「獎學金」這種規章沒有的詞會留在分母，擋下無關問題。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import jieba
from rank_bm25 import BM25Okapi

KB_DIR = Path(__file__).resolve().parent.parent / "kb"
CHUNKS_PATH = KB_DIR / "chunks.json"
# jieba 內建詞典是簡體，繁體會被切成單字；改用官方繁體詞典 dict.txt.big
# （github.com/fxsjy/jieba extra_dict），再加上規章用語的自訂詞
JIEBA_DICT_PATH = KB_DIR / "dict" / "dict.txt.big"
USER_DICT_PATH = KB_DIR / "dict" / "user_dict.txt"
MIN_SCORE = 1.0
# 條文至少要包含查詢中這個比例的「詞」（jieba 斷詞，單字詞不算）。只靠分數門檻擋不住
# 「學生餐廳營業時間」這種只命中常見詞的查詢，卻會擋掉「轉系」（3.02 分）。
MIN_COVERAGE = 0.5

# 口語 → 規章用語。查詢裡出現 key 時，條文含任一個 value 就算命中這個詞，
# value 也會加進 BM25 查詢。只放規章確實使用、口語又一定不會這樣說的詞。
QUERY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "大一": ("一年級", "第一學年"),
    "大二": ("二年級", "第二學年"),
    "大三": ("三年級", "第三學年"),
    "大四": ("四年級", "第四學年"),
    "當兵": ("服役", "入伍"),
}

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
_CJK_CHAR_RE = re.compile(r"[㐀-鿿豈-﫿]")

jieba.setLogLevel(logging.WARNING)  # 載入訊息寫在 stderr，但不需要每次都印
_JIEBA = jieba.Tokenizer(dictionary=str(JIEBA_DICT_PATH))
_JIEBA.load_userdict(str(USER_DICT_PATH))


def query_terms(query: str) -> list[tuple[str, ...]]:
    """把查詢斷成計算覆蓋率用的詞，每個詞附上同義詞，例如「我已經大二了還能轉系嗎」→
    [("已經",), ("二年級", "第二學年"), ("轉系",)]。

    疑問詞先拿掉；單字詞（「我」「了」「課」）與標點不算，重複的詞只算一次。
    關掉 jieba 的 HMM：它會把繁體未登錄詞黏成「停修後學費會」這種長串。
    """
    terms: list[tuple[str, ...]] = []
    for w in _JIEBA.lcut(_STOPWORD_RE.sub(" ", query), HMM=False):
        is_word = (len(w) >= 2 and _CJK_CHAR_RE.match(w)) or (w.isascii() and w.isalnum())
        if not is_word:
            continue
        alts = QUERY_SYNONYMS.get(w, (w,))
        if alts not in terms:
            terms.append(alts)
    return terms


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
_FULL_TEXTS = [c["source"] + c["article"] + c["text"] for c in _CHUNKS]


def coverage(terms: list[tuple[str, ...]], chunk_index: int) -> float:
    """條文包含了幾成的查詢詞（同義詞任一個出現就算）。"""
    text = _FULL_TEXTS[chunk_index]
    return sum(any(a in text for a in alts) for alts in terms) / len(terms)


def search_regulations(query: str, top_k: int = 3) -> list[dict]:
    """用關鍵字搜尋世新大學規章條文，回傳最相關的條文段落與出處。

    Args:
        query: 查詢文字，例如「停修」「轉系 申請期限」。
        top_k: 最多回傳幾筆，預設 3。

    Returns:
        依 score 由高到低排序的 list，每筆含 id、source（辦法名稱）、article（條號）、
        text（條文全文）、score（BM25 分數）。分數低於 MIN_SCORE、或條文涵蓋的查詢詞
        少於 MIN_COVERAGE 的不回傳；找不到相關條文、或查詢裡沒有任何兩字以上的詞時回傳空 list。
    """
    terms = query_terms(query)
    if not terms or top_k <= 0:
        return []
    synonyms = " ".join(a for alts in terms for a in alts if a not in query)
    tokens = tokenize(_STOPWORD_RE.sub(" ", query) + " " + synonyms)
    scores = _BM25.get_scores(tokens)
    ranked = sorted(range(len(_CHUNKS)), key=lambda i: scores[i], reverse=True)
    results = []
    for i in ranked:
        if len(results) >= top_k or scores[i] < MIN_SCORE:
            break
        if coverage(terms, i) < MIN_COVERAGE:
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
