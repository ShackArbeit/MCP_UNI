"""把 kb/*.pdf 轉成條文切段：輸出 kb/md/<原檔名>.md 與 kb/chunks.json。

用法：python scripts/ingest.py

PDF 文字層的已知問題與處理方式（以 pymupdf rawdict 實際觀察）：
- 條號格式：「第一條」「第 九 條」「第十一條」；專案服役那份用「一、」當條（輸出為「第一點」）。
  只認「行首」且「號碼剛好是下一條」的才算新條，內文引用（例如「第一條第一項」）不會被切開。
- pymupdf 讀出來每行都獨立，沒有 pdftotext 那種多個條號擠在同一行的情況。
- 部分 PDF 含 CJK 相容字（例如「年」U+F98E），它們附近的文字會重複或漏字，
  處理方式見 extract_lines()。
- 標題與第一條之間的「XX 年 X 月 X 日教務會議修訂通過」存成 history。
- 條內的「一、」「（一）」是款／目，只拿來分段落，不切開。
"""
from __future__ import annotations

import json
import random
import re
import sys
import unicodedata
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "kb"
MD_DIR = KB_DIR / "md"
CHUNKS_PATH = KB_DIR / "chunks.json"

EXPECTED_COUNTS = {"選課辦法": 14}
MIN_TEXT_LEN = 10

CN_DIGITS = "零一二三四五六七八九"
CN_NUM = r"[一二三四五六七八九十百]+"
ARTICLE_RE = re.compile(rf"^\s*第\s*({CN_NUM})\s*條\s*(.*)$")
POINT_RE = re.compile(rf"^\s*({CN_NUM})\s*、\s*(.*)$")
ITEM_RE = re.compile(rf"^\s*(?:{CN_NUM}\s*、|[(（]\s*{CN_NUM}\s*[)）])")
PAGE_NO_RE = re.compile(r"^\s*\d+\s*$")
HISTORY_HINT_RE = re.compile(r"\d+\s*(年|學年度)")

# 中日韓文字與全形標點；它們旁邊的空白都是排版造成的，直接拿掉
CJK = r"　-〿㐀-鿿＀-￯"
SPACE_NEAR_CJK_RE = re.compile(rf"\s+(?=[{CJK}])|(?<=[{CJK}])\s+")


def cn2int(s: str) -> int:
    """中文數字轉整數（支援到 999）。"""
    if s == "十":
        return 10
    total, cur = 0, 0
    for ch in s:
        if ch == "百":
            total += (cur or 1) * 100
            cur = 0
        elif ch == "十":
            total += (cur or 1) * 10
            cur = 0
        else:
            cur = CN_DIGITS.index(ch)
    return total + cur


def int2cn(n: int) -> str:
    """整數轉中文數字（1–999），例如 13 → 十三、20 → 二十。"""
    if not 0 < n < 1000:
        raise ValueError(f"條號超出範圍：{n}")
    out = ""
    h, rest = divmod(n, 100)
    t, u = divmod(rest, 10)
    if h:
        out += CN_DIGITS[h] + "百"
        if t == 0 and u:
            out += "零"
    if t:
        out += ("" if t == 1 and not h else CN_DIGITS[t]) + "十"
    if u:
        out += CN_DIGITS[u]
    return out


def normalize(text: str) -> str:
    """去掉換行與多餘空白：中文旁的空白全拿掉，其餘連續空白縮成一個。"""
    text = SPACE_NEAR_CJK_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _overlap(a: str, b: str) -> int:
    """a 的尾巴與 b 的開頭重疊幾個字（取最長）。"""
    for k in range(min(len(a), len(b)), 0, -1):
        if a.endswith(b[:k]):
            return k
    return 0


def _is_compat(ch: str) -> bool:
    return "豈" <= ch <= "﫿"


def _fix_compat(text: str) -> str:
    """CJK 相容字（長得一樣、碼位不同）轉回標準字，否則搜「年」會找不到。"""
    return "".join(unicodedata.normalize("NFKC", ch) if _is_compat(ch) else ch for ch in text)


def _page_line_x1(page: pymupdf.Page) -> list[tuple[str, float]]:
    """dict 模式的每一行（文字, 右緣 x1），用來判斷一行有沒有寫滿。"""
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if spans:
                out.append(("".join(s["text"] for s in line["spans"]).strip(), spans[-1]["bbox"][2]))
    return out


def extract_lines(pdf_path: Path) -> list[dict]:
    """依閱讀順序取出每一行 {"text", "x1"}，去除頁碼與相容字造成的重複文字。

    用 "text" 模式而不是 "dict"：dict 會漏掉相容字附近的字（例如「以四、五年級」的「五年」），
    text 模式字是全的，但下一行會重複前一行的尾巴，例如：
        「…持修業年限少於…以同等學力資格入學」+「限少於…以同等學力資格入學」
    重疊 >= 4 字才去重；1–3 字的重疊要緊鄰相容字才算，避免誤刪真正的換行（例如「入學\n學年度」）。
    每一次去重都會印出來，方便人工確認。

    x1（行的右緣）從 dict 模式對應同一行取得，給 split_articles 判斷段落；
    對不到的行（只出現在 text 模式的補字行）x1 為 None。
    """
    lines: list[dict] = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            geo, gi = _page_line_x1(page), 0
            for text in page.get_text("text").splitlines():
                text = text.rstrip()
                if not text.strip():
                    continue
                # text 與 dict 的行順序相同，往後找 3 行內完全相同的那一行
                x1 = None
                for i in range(gi, min(gi + 3, len(geo))):
                    if geo[i][0] == text.strip():
                        x1, gi = geo[i][1], i + 1
                        break
                if PAGE_NO_RE.match(text):
                    continue
                if lines:
                    a, b = lines[-1]["text"].rstrip(), text.strip()
                    k = _overlap(a, b)
                    if k >= 4 or (k and len(a) > k and _is_compat(a[-k - 1])):
                        print(f"  [去重] {pdf_path.stem}：刪除重複的「{b[:k]}」（…{a[-12:]} | {b[:20]}…）")
                        # 剩下的部分和前一行同一列，直接接上；右緣以後面那段為準
                        lines[-1] = {"text": a + b[k:], "x1": x1 or lines[-1]["x1"]}
                        continue
                lines.append({"text": text, "x1": x1})
    for l in lines:
        l["text"] = _fix_compat(l["text"])
    return lines


def _right_margin(lines: list[dict]) -> float:
    """版面右邊界：取各行右緣的第 90 百分位（寫滿的行大多貼齊這裡）。"""
    xs = sorted(l["x1"] for l in lines if l["x1"] is not None)
    if not xs:
        raise ValueError("取不到任何行的座標，無法判斷段落")
    return xs[int(len(xs) * 0.9)]


def split_articles(lines: list[dict], source: str) -> dict:
    """把行切成 title / history / articles。找不到任何「第X條」時改用「一、」當條（點）。

    段落（項、款）只影響 Markdown 排版，不影響 chunks.json 的 text。新段落的判斷：
    - 行首是款／目編號（「一、」「（一）」）；或
    - 前一行以「。」「：」結尾，而且沒寫滿到右邊界（差超過 1.5 個字寬）。
    前一行剛好寫滿又以「。」結尾時無法判斷，一律當作同一段。
    """
    if not lines:
        raise ValueError(f"{source}：PDF 沒有可抽取的文字（可能是掃描檔，本專案不做 OCR）")
    right = _right_margin(lines)
    title = normalize(lines[0]["text"])
    body = lines[1:]

    use_points = not any(
        (m := ARTICLE_RE.match(l["text"])) and cn2int(m.group(1)) == 1 for l in body
    )
    pattern, unit = (POINT_RE, "點") if use_points else (ARTICLE_RE, "條")

    def ends_paragraph(prev: dict) -> bool:
        return (
            prev["text"].rstrip().endswith(("。", "："))
            and prev["x1"] is not None
            and prev["x1"] < right - 18
        )

    history: list[str] = []
    articles: list[dict] = []
    prev: dict | None = None
    for item in body:
        line = item["text"]
        last, prev = prev, item
        m = pattern.match(line)
        if m:
            num = cn2int(m.group(1))
            expected = len(articles) + 1
            if num == expected:
                articles.append({"num": num, "paragraphs": [m.group(2)]})
                continue
            if not use_points:
                # 行首出現「第X條」但號碼不連續：當內文處理，但要讓人知道
                print(f"  [警告] {source}：行首出現「第{m.group(1)}條」但預期第{int2cn(expected)}條，當作內文處理：{normalize(line)[:40]}")
        if not articles:
            history.append(line)
            continue
        paras = articles[-1]["paragraphs"]
        if ITEM_RE.match(line) or not paras[-1].strip() or ends_paragraph(last):
            paras.append(line)
        else:
            paras[-1] += line

    history = [normalize(h) for h in history if normalize(h)]
    for h in history:
        if not HISTORY_HINT_RE.search(h):
            print(f"  [警告] {source}：第一條之前有不像沿革的內容：{h[:40]}")

    result = []
    for a in articles:
        paras = [normalize(p) for p in a["paragraphs"] if normalize(p)]
        article = f"第{int2cn(a['num'])}{unit}"
        result.append({
            "id": f"{source}-{article}",
            "source": source,
            "article": article,
            "paragraphs": paras,
            "text": "".join(paras),
        })
    return {"title": title, "history": history, "articles": result}


def write_markdown(doc: dict, path: Path) -> None:
    out = [f"# {doc['title']}", ""]
    if doc["history"]:
        out.append("> 沿革：")
        out += [f"> - {h}" for h in doc["history"]]
        out.append("")
    for a in doc["articles"]:
        out += [f"## {a['article']}", ""]
        out += [p + "\n" for p in a["paragraphs"]]
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    pdfs = sorted(KB_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"[錯誤] {KB_DIR} 底下沒有 PDF")
        return 1
    MD_DIR.mkdir(parents=True, exist_ok=True)

    chunks: list[dict] = []
    warnings = 0
    for pdf in pdfs:
        source = pdf.stem
        doc = split_articles(extract_lines(pdf), source)
        n = len(doc["articles"])
        print(f"{source}：{n} 條（沿革 {len(doc['history'])} 筆）")

        if n == 0:
            print(f"  [警告] {source} 切出 0 條")
            warnings += 1
        if source in EXPECTED_COUNTS and n != EXPECTED_COUNTS[source]:
            print(f"  [警告] {source} 預期 {EXPECTED_COUNTS[source]} 條，實際 {n} 條")
            warnings += 1
        for a in doc["articles"]:
            if len(a["text"]) < MIN_TEXT_LEN:
                print(f"  [警告] {a['id']} 內文只有 {len(a['text'])} 字：{a['text']}")
                warnings += 1

        write_markdown(doc, MD_DIR / f"{source}.md")
        chunks += [{k: a[k] for k in ("id", "source", "article", "text")} for a in doc["articles"]]

    ids = [c["id"] for c in chunks]
    dups = {i for i in ids if ids.count(i) > 1}
    if dups:
        print(f"[警告] 重複的 id：{sorted(dups)}")
        warnings += 1

    CHUNKS_PATH.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n共 {len(chunks)} 條 → {CHUNKS_PATH.relative_to(ROOT)}；Markdown → {MD_DIR.relative_to(ROOT)}/")
    print(f"警告 {warnings} 個")

    print("\n===== 隨機抽 3 條，請對照原 PDF =====")
    for c in random.sample(chunks, min(3, len(chunks))):
        print(f"\n[{c['id']}]\n{c['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
