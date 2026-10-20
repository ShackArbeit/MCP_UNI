"""評估測試集：直接呼叫 core/ 的函式（不經過 LLM），結果可以重現。

執行：python eval/run_eval.py
輸出：終端機表格 + 三類通過率，並寫入 docs/測試報告.md。
報告也會附上單元測試（pytest）的結果，讓一份報告就能看到兩種測試。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import search  # noqa: E402
from core.routing import list_categories  # noqa: E402
from core.rules import check_credit_rule  # noqa: E402
from core.search import search_regulations  # noqa: E402

QUESTIONS_PATH = ROOT / "eval" / "questions.yaml"
REPORT_PATH = ROOT / "docs" / "測試報告.md"
TOP_K = 3
TARGETS = {"answerable": 0.80, "should_route": 0.75}
TYPE_NAMES = {"answerable": "可回答", "calculation": "計算", "should_route": "應分流"}
# 報告中每個單元測試檔的說明
UNIT_DESC = {
    "tests/test_pii.py": "個資遮蔽：學號、身分證、手機、Email；一般數字不誤遮",
    "tests/test_routing.py": "分流與紀錄：窗口比對、單號遞增、個資遮蔽、只寫暫存資料庫",
    "tests/test_rules.py": "學分規則：門檻數字對得上原文、邊界值、比較方向、格式檢查",
    "tests/test_search.py": "條文檢索：斷詞、同義詞、無關問題查無、單一關鍵字查詢",
}


# 將查詢詞及其同義詞組合成適合顯示的文字。
# 同義詞以「／」連接，不同詞組以「、」連接。
def _fmt_terms(terms: list[tuple[str, ...]]) -> str:
    return "、".join("／".join(alts) for alts in terms)


# 診斷可回答題的預期條文為何沒有出現在搜尋結果中。
# 重新計算預期條文的 BM25 排名、分數和查詢詞覆蓋率，
# 用來判斷問題是分數未達門檻、覆蓋率不足，還是排名被擠出 top_k。
def _diagnose_answerable(question: str, expected_ids: list[str]) -> str:
    terms = search.query_terms(question)
    if not terms:
        return "去掉疑問詞與單字詞後沒有任何查詢詞"
    synonyms = " ".join(a for alts in terms for a in alts if a not in question)
    scores = search._BM25.get_scores(search.tokenize(search._STOPWORD_RE.sub(" ", question) + " " + synonyms))
    ranked = sorted(range(len(search._CHUNKS)), key=lambda i: scores[i], reverse=True)
    notes = []
    for rank, i in enumerate(ranked, 1):
        cid = search._CHUNKS[i]["id"]
        if cid not in expected_ids:
            continue
        text = search._FULL_TEXTS[i]
        hit = [alts for alts in terms if any(a in text for a in alts)]
        miss = [alts for alts in terms if alts not in hit]
        cov = search.coverage(terms, i)
        reasons = []
        if scores[i] < search.MIN_SCORE:
            reasons.append(f"分數 {scores[i]:.2f} < 門檻 {search.MIN_SCORE}")
        if cov < search.MIN_COVERAGE:
            reasons.append(f"覆蓋率 {cov:.0%} < {search.MIN_COVERAGE:.0%}")
        if not reasons:
            reasons.append(f"排名第 {rank}，被前面的條文擠出 top {TOP_K}")
        notes.append(
            f"{cid}：BM25 排名第 {rank}、分數 {scores[i]:.2f}、覆蓋率 {cov:.0%}"
            f"（命中 {_fmt_terms(hit) or '無'}；未命中 {_fmt_terms(miss) or '無'}）→ {'；'.join(reasons)}"
        )
    return f"查詢詞：{_fmt_terms(terms)}<br>" + "<br>".join(notes)


# 診斷應分流題為何錯誤地命中了規章條文。
# 列出每筆誤命中結果的分數、命中的查詢詞和覆蓋率，
# 協助判斷檢索器為何沒有將問題排除。
def _diagnose_route(question: str, hits: list[dict]) -> str:
    terms = search.query_terms(question)
    parts = []
    for h in hits:
        i = next(k for k, c in enumerate(search._CHUNKS) if c["id"] == h["id"])
        hit = [alts for alts in terms if any(a in search._FULL_TEXTS[i] for a in alts)]
        parts.append(f"{h['id']}（分數 {h['score']:.2f}，命中 {_fmt_terms(hit)}，覆蓋率 {search.coverage(terms, i):.0%}）")
    return f"查詢詞：{_fmt_terms(terms)}<br>誤命中：" + "；".join(parts)


# 讀取測試題目並逐題執行評估。
# 依題目類型分別測試規章檢索、學分規則計算和應分流問題，
# 回傳包含預期結果、實際結果、是否通過及失敗診斷的清單。
def evaluate() -> list[dict]:
    questions = yaml.safe_load(QUESTIONS_PATH.read_text(encoding="utf-8"))["questions"]
    categories = set(list_categories())
    results = []
    for q in questions:
        r = {"id": q["id"], "type": q["type"], "question": q["question"], "diagnosis": ""}
        if q["type"] == "answerable":
            hits = search_regulations(q["question"], top_k=TOP_K)
            hit_ids = [h["id"] for h in hits]
            r["passed"] = any(i in q["expected_ids"] for i in hit_ids)
            r["actual"] = "、".join(hit_ids) or "（無結果）"
            r["expected"] = "、".join(q["expected_ids"])
            if not r["passed"]:
                r["diagnosis"] = _diagnose_answerable(q["question"], q["expected_ids"])
        elif q["type"] == "calculation":
            try:
                out = check_credit_rule(q["expected_rule_id"], q["value"])
            except Exception as e:  # noqa: BLE001 — 評估要記錄任何錯誤，不中斷
                r.update(passed=False, actual=f"錯誤：{e}", diagnosis=str(e))
            else:
                r["passed"] = out["passed"] == q["expected_passed"]
                r["actual"] = f"{'通過' if out['passed'] else '不通過'}：{out['explanation']}（{out['source']}）"
                if not r["passed"]:
                    r["diagnosis"] = f"預期 passed={q['expected_passed']}，實際 {out['passed']}"
            r["expected"] = f"{q['expected_rule_id']}({q['value']}) → {'通過' if q['expected_passed'] else '不通過'}"
        elif q["type"] == "should_route":
            if q["expected_category"] not in categories:
                raise ValueError(f"{q['id']} 的 expected_category「{q['expected_category']}」不在 routing.yaml")
            hits = search_regulations(q["question"], top_k=TOP_K)
            r["passed"] = not hits
            r["actual"] = "、".join(h["id"] for h in hits) or "（無結果，應分流）"
            r["expected"] = f"無結果 → route_case({q['expected_category']})"
            if not r["passed"]:
                r["diagnosis"] = _diagnose_route(q["question"], hits)
        else:
            raise ValueError(f"{q['id']} 的 type「{q['type']}」不支援")
        results.append(r)
    return results


# 依題目類型統計通過題數與總題數。
# 回傳字典以題目類型為 key，value 為「通過數、總題數」。
def summarize(results: list[dict]) -> dict[str, tuple[int, int]]:
    summary = {}
    for t in TYPE_NAMES:
        group = [r for r in results if r["type"] == t]
        summary[t] = (sum(r["passed"] for r in group), len(group))
    return summary


# 執行一次 pytest，回傳每個測試檔的 passed／failed／xfailed／skipped 數量。
# 用 --junitxml 讓 pytest 把結果寫成 XML 再解析，不必解析終端機文字。
# 回傳：{"tests/test_rules.py": Counter({"passed": 86}), ...}；pytest 無法執行時回傳 None。
def run_unit_tests() -> dict[str, Counter] | None:
    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "pytest.xml"
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml_path}"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if not xml_path.exists():
            print(proc.stdout[-2000:], proc.stderr[-2000:], sep="\n")
            return None
        root = ET.parse(xml_path).getroot()
    by_file: dict[str, Counter] = {}
    for case in root.iter("testcase"):
        file = case.get("classname", "").replace(".", "/") + ".py"
        if case.find("failure") is not None or case.find("error") is not None:
            status = "failed"
        elif (sk := case.find("skipped")) is not None:
            status = "xfailed" if sk.get("type") == "pytest.xfail" or "xfail" in (sk.get("message") or "") else "skipped"
        else:
            status = "passed"
        by_file.setdefault(file, Counter())[status] += 1
    return by_file


# 把各檔案的數量加總成一行摘要，例如「141 passed、2 xfailed」。
def _unit_total(by_file: dict[str, Counter]) -> str:
    total = sum(by_file.values(), Counter())
    return "、".join(f"{total[k]} {k}" for k in ("passed", "failed", "xfailed", "skipped") if total[k])


# 在終端機列印逐題測試結果和各類型通過率。
def print_table(results: list[dict], summary: dict[str, tuple[int, int]]) -> None:
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"{r['id']}  {TYPE_NAMES[r['type']]:<3}  {mark}  {r['question']}")
        print(f"      實際：{r['actual']}")
    print()
    for t, (p, n) in summary.items():
        target = f"（目標 {TARGETS[t]:.0%}）" if t in TARGETS else ""
        print(f"{TYPE_NAMES[t]}：{p}/{n} = {p / n:.0%}{target}")


# 將測試摘要、逐題結果和失敗診斷寫入 Markdown 報告。
# 若報告目錄不存在，會先建立目錄，再以 UTF-8 編碼寫入報告。
def write_report(results: list[dict], summary: dict[str, tuple[int, int]],
                 unit: dict[str, Counter] | None) -> None:
    lines = [
        "# 測試報告",
        "",
        f"- 產生時間：{datetime.now():%Y-%m-%d %H:%M}",
        "- 產生方式：`python eval/run_eval.py`（直接呼叫 core/ 函式，不經過 LLM，結果可重現；同時執行一次 pytest）",
        "",
        "## 單元測試",
        "",
    ]
    if unit is None:
        lines.append("pytest 無法執行，請手動執行 `python -m pytest -v` 查看原因。")
    else:
        lines += [f"合計：**{_unit_total(unit)}**", "", "| 測試檔 | 測試內容 | passed | failed | xfailed |", "|---|---|---|---|---|"]
        for file, c in sorted(unit.items()):
            lines.append(f"| `{file}` | {UNIT_DESC.get(file, '')} | {c['passed']} | {c['failed']} | {c['xfailed']} |")
        if any(c["xfailed"] for c in unit.values()):
            lines += ["", "> xfailed 是刻意標記的已知限制（例如「社團怎麼申請」會誤命中），不是新的錯誤。"]
    lines += [
        "",
        "## 評估測試",
        "",
        f"- 題庫：`eval/questions.yaml`，共 {len(results)} 題；檢索 top_k = {TOP_K}，"
        f"MIN_SCORE = {search.MIN_SCORE}，MIN_COVERAGE = {search.MIN_COVERAGE}",
        "",
        "### 總結",
        "",
        "| 類型 | 通過 | 通過率 | 目標 | 達標 |",
        "|---|---|---|---|---|",
    ]
    for t, (p, n) in summary.items():
        target = TARGETS.get(t)
        ok = "—" if target is None else ("✅" if p / n >= target else "❌")
        lines.append(f"| {TYPE_NAMES[t]} | {p}/{n} | {p / n:.0%} | {f'{target:.0%}' if target else '—'} | {ok} |")
    lines += [
        "",
        "> 應分流題只驗證「檢索查不到」；分流到哪個類別由 LLM 決定，這裡只檢查 expected_category 存在於 routing.yaml。",
        "",
        "### 逐題結果",
        "",
        "| 編號 | 類型 | 題目 | 結果 | 預期 | 實際 |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['id']} | {TYPE_NAMES[r['type']]} | {r['question']} | {'✅' if r['passed'] else '❌'} "
            f"| {r['expected']} | {r['actual']} |"
        )
    failed = [r for r in results if not r["passed"]]
    lines += ["", "### 失敗題目分析", ""]
    if not failed:
        lines.append("全部通過。")
    else:
        lines += ["| 編號 | 題目 | 診斷 |", "|---|---|---|"]
        lines += [f"| {r['id']} | {r['question']} | {r['diagnosis']} |" for r in failed]
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


# 執行完整評估流程：評估測試、單元測試、統計、列印結果並產生 Markdown 報告。
def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    results = evaluate()
    summary = summarize(results)
    print_table(results, summary)
    unit = run_unit_tests()
    print(f"\n單元測試：{_unit_total(unit) if unit else 'pytest 無法執行'}")
    write_report(results, summary, unit)
    print(f"\n報告已寫入 {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()