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


# 【tokenize】把文字切成 BM25 排序用的 token（字元 bigram）。
# 主要功能：建索引時切條文、查詢時切問題，兩邊用同一種切法，BM25 才能比對分數。
# 用 bigram 而不用 jieba 排序，是因為 bigram 不會切錯，條文裡的詞一定比對得到。
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


# 【query_terms】把學生的問題斷成「詞」，並換上規章用語的同義詞。
# 主要功能：產生計算覆蓋率用的詞清單，用來判斷條文是否真的和問題相關。
# 用 jieba 斷詞，可以避免 bigram 切出「費會」「會退」這類跨詞雜訊拉低覆蓋率；
# 同義詞讓口語（大二、當兵）也能對到條文用語（第二學年、服役）。
def query_terms(query: str) -> list[tuple[str, ...]]:
    terms: list[tuple[str, ...]] = []
    for w in _JIEBA.lcut(_STOPWORD_RE.sub(" ", query), HMM=False):
        is_word = (len(w) >= 2 and _CJK_CHAR_RE.match(w)) or (w.isascii() and w.isalnum())
        if not is_word:
            continue
        alts = QUERY_SYNONYMS.get(w, (w,))
        if alts not in terms:
            terms.append(alts)
    return terms


# 【_load_chunks】讀取 kb/chunks.json 的所有條文（模組載入時執行一次）。
# 主要功能：提供檢索的資料來源；檔案不存在或內容是空的就直接報錯，
# 並提示先執行 scripts/ingest.py，避免 server 在沒有知識庫的情況下啟動。
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


# 【coverage】計算某條條文包含了幾成的查詢詞（0～1），同義詞任一個出現就算命中。
# 主要功能：當作第二道門檻，擋下「分數不低、其實不相關」的條文。
# 例如「學生宿舍什麼時候可以申請」只命中「申請」，覆蓋率太低，就不會回傳。
def coverage(terms: list[tuple[str, ...]], chunk_index: int) -> float:
    text = _FULL_TEXTS[chunk_index]
    return sum(any(a in text for a in alts) for alts in terms) / len(terms)


# 【search_regulations】對外的檢索入口：輸入學生的問題，回傳最相關的條文與出處。
# 主要功能：串起整個檢索流程——
#   1. query_terms 斷詞並加上同義詞
#   2. tokenize 後交給 BM25 算每條條文的分數，由高到低排序
#   3. 依序檢查：分數 ≥ MIN_SCORE，且 coverage ≥ MIN_COVERAGE 才收進結果
#   4. 收滿 top_k 筆就停止；一筆都沒有就回傳空 list（server.py 會改叫 route_case 分流）
def search_regulations(query: str, top_k: int = 3) -> list[dict]:
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
