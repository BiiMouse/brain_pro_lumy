"""Lumy 型号知识库自测问答评估

对 eval/lumy_qa.json 的题目逐题执行 lumy 查询图，检查：
  - 事实点：expected_any（至少其一）/ expected_all（全部包含）
  - 引用完整性：expected_cite 文件名出现在答案或证据中
  - 拒答题：答案含拒答标志且不编造

用法：
    set KB_SCENARIO=lumy
    python eval/lumy_eval.py [--smoke N] [--out eval/lumy_result.md]
"""

import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

os.environ.setdefault("KB_SCENARIO", "lumy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from knowledge.processor.query_process.main_graph import query_app  # noqa: E402

REFUSAL_MARKS = ["未找到", "未提供", "无法回答", "不作答", "未收录", "暂无法"]
CITE_RE = re.compile(r"\[([^\]第]+?)(?:\s*第\d+页?)?\]|\[型号库\]")


def run_one(q: dict) -> dict:
    state = {
        "original_query": q["question"],
        "session_id": f"lumy_eval_{uuid.uuid4().hex[:8]}",
        "task_id": uuid.uuid4().hex,
        "is_stream": False,
    }
    t0 = time.time()
    st = query_app.invoke(state)
    answer = st.get("answer") or ""
    evidence_text = answer
    for d in (st.get("structured_docs") or []):
        evidence_text += f" {d.get('file') or ''}"
    for d in (st.get("reranked_docs") or []):
        evidence_text += f" {d.get('file_title') or ''} {d.get('content') or ''}"
    return {
        "answer": answer,
        "intent": st.get("intent"),
        "n_structured": len(st.get("structured_docs") or []),
        "n_docs": len(st.get("reranked_docs") or []),
        "evidence_text": evidence_text,
        "elapsed": time.time() - t0,
    }


def check_one(q: dict, r: dict) -> dict:
    """返回 {pass, reasons[]}"""
    reasons = []
    answer, evidence = r["answer"], r["evidence_text"]

    if q.get("expected_refusal"):
        if not any(m in answer for m in REFUSAL_MARKS):
            reasons.append("未出现拒答标志")
        # 不得编造价格/库存
        if re.search(r"\d+\s*(元|USD|\$)|库存\s*\d+", answer):
            reasons.append("疑似编造数字")
    else:
        any_kw = q.get("expected_any") or []
        if any_kw and not any(k in answer for k in any_kw):
            # 事实点也允许出现在证据中（答案引用证据编号）——宽松匹配证据文本
            if not any(k in evidence for k in any_kw):
                reasons.append(f"缺少事实点(any): {any_kw}")
        all_kw = q.get("expected_all") or []
        missing = [k for k in all_kw if k not in answer and k not in evidence]
        if missing:
            reasons.append(f"缺少事实点(all): {missing}")
        for cite in q.get("expected_cite") or []:
            if cite.lower() not in evidence.lower():
                reasons.append(f"缺少引用: {cite}")
        if not any(m in answer for m in ("[", "第", "型号库")):
            reasons.append("答案无证据引用标记")

    return {"pass": not reasons, "reasons": reasons}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", type=int, default=0, help="只跑前 N 题")
    parser.add_argument("--out", default="eval/lumy_result.md")
    args = parser.parse_args()

    qa_path = Path(__file__).parent / "lumy_qa.json"
    data = json.loads(qa_path.read_text(encoding="utf-8"))
    questions = data["questions"]
    if args.smoke:
        questions = questions[:args.smoke]

    results = []
    for q in questions:
        print(f"\n>>> [{q['id']}] ({q['type']}) {q['question']}", flush=True)
        try:
            r = run_one(q)
            c = check_one(q, r)
        except Exception as e:
            r = {"answer": "", "evidence_text": "", "elapsed": 0,
                 "intent": "ERROR", "n_structured": 0, "n_docs": 0}
            c = {"pass": False, "reasons": [f"执行异常: {e}"]}
        c.update({"id": q["id"], "type": q["type"], "q": q["question"],
                  "answer": r["answer"], "intent": r["intent"],
                  "elapsed": r["elapsed"]})
        results.append(c)
        mark = "✓" if c["pass"] else "✗"
        print(f"    {mark} {c['reasons'] or ''}", flush=True)

    # 汇总报告
    passed = sum(1 for c in results if c["pass"])
    lines = ["# Lumy 自测问答结果", "",
             f"- 总题数: {len(results)}，通过: {passed}，"
             f"通过率: {passed/len(results)*100:.0f}%", "",
             "| ID | 类型 | 问题 | 结果 | 失败原因 | 用时 |",
             "|---|---|---|---|---|---|"]
    for c in results:
        lines.append(f"| {c['id']} | {c['type']} | {c['q'][:30]} | "
                     f"{'✓' if c['pass'] else '✗'} | {'; '.join(c['reasons'])} | "
                     f"{c['elapsed']:.0f}s |")
    lines.append("")
    for c in results:
        lines.append(f"## {c['id']} {c['q']}")
        lines.append(f"- 意图: {c['intent']}  用时: {c['elapsed']:.0f}s")
        lines.append("```")
        lines.append(c["answer"][:1200])
        lines.append("```")
        lines.append("")
    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"\n通过 {passed}/{len(results)} → {args.out}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
