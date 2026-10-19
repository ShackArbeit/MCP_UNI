"""評估測試集：直接呼叫 core/ 的函式（不經過 LLM），結果可以重現。

執行：python eval/run_eval.py
輸出：終端機表格 + 三類通過率，並寫入 docs/測試報告.md。
"""
from __future__ import annotations

import sys
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


def _fmt_terms(terms: list[tuple[str, ...]]) -> str:
    return "、".join("／".join(alts) for alts in terms)


def _diagnose_answerable(question: str, expected_ids: list[str]) -> str:
    """找出預期條文在哪一關被擋下：排名不夠前面、分數低於門檻，或查詢詞覆蓋率不足。"""
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


def _diagnose_route(question: str, hits: list[dict]) -> str:
    terms = search.query_terms(question)
    parts = []
    for h in hits:
        i = next(k for k, c in enumerate(search._CHUNKS) if c["id"] == h["id"])
        hit = [alts for alts in terms if any(a in search._FULL_TEXTS[i] for a in alts)]
        parts.append(f"{h['id']}（分數 {h['score']:.2f}，命中 {_fmt_terms(hit)}，覆蓋率 {search.coverage(terms, i):.0%}）")
    return f"查詢詞：{_fmt_terms(terms)}<br>誤命中：" + "；".join(parts)


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


def summarize(results: list[dict]) -> dict[str, tuple[int, int]]:
    summary = {}
    for t in TYPE_NAMES:
        group = [r for r in results if r["type"] == t]
        summary[t] = (sum(r["passed"] for r in group), len(group))
    return summary


def print_table(results: list[dict], summary: dict[str, tuple[int, int]]) -> None:
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"{r['id']}  {TYPE_NAMES[r['type']]:<3}  {mark}  {r['question']}")
        print(f"      實際：{r['actual']}")
    print()
    for t, (p, n) in summary.items():
        target = f"（目標 {TARGETS[t]:.0%}）" if t in TARGETS else ""
        print(f"{TYPE_NAMES[t]}：{p}/{n} = {p / n:.0%}{target}")


def write_report(results: list[dict], summary: dict[str, tuple[int, int]]) -> None:
    lines = [
        "# 測試報告",
        "",
        f"- 產生時間：{datetime.now():%Y-%m-%d %H:%M}",
        "- 產生方式：`python eval/run_eval.py`（直接呼叫 core/ 函式，不經過 LLM，結果可重現）",
        f"- 題庫：`eval/questions.yaml`，共 {len(results)} 題；檢索 top_k = {TOP_K}，"
        f"MIN_SCORE = {search.MIN_SCORE}，MIN_COVERAGE = {search.MIN_COVERAGE}",
        "",
        "## 總結",
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
        "## 逐題結果",
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
    lines += ["", "## 失敗題目分析", ""]
    if not failed:
        lines.append("全部通過。")
    else:
        lines += ["| 編號 | 題目 | 診斷 |", "|---|---|---|"]
        lines += [f"| {r['id']} | {r['question']} | {r['diagnosis']} |" for r in failed]
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    results = evaluate()
    summary = summarize(results)
    print_table(results, summary)
    write_report(results, summary)
    print(f"\n報告已寫入 {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
