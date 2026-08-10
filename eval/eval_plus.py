"""增强版 RAG 评估

在 eval.py 的 RAGAS 5 指标（覆盖 #2 忠实 / 检索质量）之上，补齐本次改造新增的：
  - #4 引用  ：答案是否带 [编号] 出处、引用编号是否落在检索文档范围内（规则可算，确定性）
  - #5 拒答  ：该拒答的用例是否拒答、可回答的用例是否作答（拒答准确率）
  - 阈值校准 ：打印可回答集 / 拒答集的 reranker 最高分分布，用于定 RAG_REFUSE_THRESHOLD

数据分工（互不污染）：
  - qa.csv     : 可回答用例 (question, ground_truth) → RAGAS 5 指标 + 引用指标
  - qa_neg.csv : 该拒答用例 (question, note)         → 拒答准确率 + 分数分布

复用 eval.py 的 RAGAS 通路（模型初始化、evaluate 调用、上下文提取），不改动 eval.py。

运行（从项目根目录）:
    python eval/eval_plus.py                 # 完整（含 RAGAS）
    RUN_RAGAS=0 python eval/eval_plus.py     # 仅跑引用/拒答/阈值（快，不调 LLM 评判，适合调阈值）
"""

from __future__ import annotations

import os
import re
import sys
import argparse
from pathlib import Path
from typing import List, Dict, Any, Tuple

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

EVAL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EVAL_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 复用 eval.py 的 RAGAS 通路（import eval 不执行其 main）
from eval import (  # noqa: E402
    step_2_init_ragas_models,
    step_3_extract_context_from_reranked_docs,
    step_6_evaluate_metrics,
)
from knowledge.processor.query_process.main_graph import query_app  # noqa: E402

# ==================== 配置 ====================
ANSWERABLE_FILE = EVAL_DIR / "qa.csv"
NEGATIVE_FILE = EVAL_DIR / "qa_neg.csv"
RESULT_FILE = EVAL_DIR / "qa_result_plus.csv"   # 增强结果输出（区别于 eval.py 的 qa_result.csv）

RUN_RAGAS = True  # 由 main() 里 argparse 覆盖；True=跑 RAGAS，False=只跑引用/拒答/阈值

# 答案中的引用标记，形如 [0] [1] [0][2]
CITATION_RE = re.compile(r"\[(\d+)\]")
# 拒答文案特征（与 answer_node.check_context_sufficient 的拒答模板保持一致）
REFUSAL_MARKERS = ("资料不足", "暂无法", "低于阈值")


# ==================== RAG 查询 ====================
def run_rag_query(question: str) -> Tuple[str, List[str], int, float]:
    """执行单条 RAG 查询，返回 (answer, contexts, 命中文档数, reranker最高分)。"""
    query_state = {
        "original_query": question,
        "session_id": "eval_plus_session",
        "task_id": "eval_plus_task",
        "is_stream": False,
    }
    result_state = query_app.invoke(query_state)
    answer = result_state.get("answer", "") or ""
    docs = result_state.get("reranked_docs", []) or []
    contexts = step_3_extract_context_from_reranked_docs(docs)
    top_score = float(docs[0].get("score") or 0.0) if docs else 0.0
    return answer, contexts, len(docs), top_score


# ==================== 引用指标 (#4) ====================
def citation_metrics(answer: str, num_docs: int) -> Dict[str, Any]:
    """统计答案中的引用情况。

    Returns:
        citation_count   : 引用标记总数
        has_citation     : 是否至少带一个引用
        citation_valid   : 引用编号是否全部落在检索文档范围内
        citation_valid_rate: 有效引用占比（0~1）
    """
    if not answer:
        return {"citation_count": 0, "has_citation": False,
                "citation_valid": False, "citation_valid_rate": 0.0}
    cites = [int(c) for c in CITATION_RE.findall(answer)]
    if not cites:
        return {"citation_count": 0, "has_citation": False,
                "citation_valid": False, "citation_valid_rate": 0.0}
    valid = [c for c in cites if 0 <= c < num_docs]
    return {
        "citation_count": len(cites),
        "has_citation": True,
        "citation_valid": len(valid) == len(cites),
        "citation_valid_rate": len(valid) / len(cites),
    }


# ==================== 拒答检测 (#5) ====================
def is_refusal(answer: str) -> bool:
    if not answer:
        return False
    return any(m in answer for m in REFUSAL_MARKERS)


# ==================== I/O ====================
def read_answerable() -> pd.DataFrame:
    df = pd.read_csv(ANSWERABLE_FILE, encoding="utf-8-sig")
    for col in ("question", "ground_truth"):
        if col not in df.columns:
            raise ValueError(f"{ANSWERABLE_FILE.name} 缺少必需列: {col}")
    return df


def read_negative() -> pd.DataFrame:
    if not NEGATIVE_FILE.exists():
        return pd.DataFrame(columns=["question", "note"])
    df = pd.read_csv(NEGATIVE_FILE, encoding="utf-8-sig")
    if "question" not in df.columns:
        raise ValueError(f"{NEGATIVE_FILE.name} 缺少必需列: question")
    return df


# ==================== 主流程 ====================
def evaluate_answerable(df: pd.DataFrame, llm_client, emb_client
                        ) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """跑可回答集：RAG 查询 → 引用指标 + (可选)RAGAS。

    Returns:
        raw_df : 每条的问题/答案/上下文/分数/引用指标
        full_df: raw_df 合并 RAGAS 分数（RUN_RAGAS=0 时无指标列）
    """
    rows: List[Dict[str, Any]] = []
    for i, q in enumerate(df["question"].tolist()):
        print(f"[可回答 {i + 1}/{len(df)}] {q[:40]}...")
        answer, contexts, num_docs, top_score = run_rag_query(q)
        cm = citation_metrics(answer, num_docs)
        rows.append({
            "question": q,
            "ground_truth": df["ground_truth"].iloc[i],
            "answer": answer,
            "context": "\n\n".join(contexts),
            "num_docs": num_docs,
            "top_rerank_score": top_score,
            "is_refusal": is_refusal(answer),
            **cm,
        })
    raw_df = pd.DataFrame(rows)

    full_df = raw_df.copy()
    if RUN_RAGAS and len(raw_df) > 0:
        from datasets import Dataset
        data = [{
            "question": r["question"], "answer": r["answer"],
            "contexts": r["context"].split("\n\n") if r["context"] else [],
            "ground_truth": r["ground_truth"],
        } for _, r in raw_df.iterrows()]
        scores = step_6_evaluate_metrics(Dataset.from_list(data), llm_client, emb_client)
        # 合并 RAGAS 分数列（scores 行序与 raw_df 一致）
        for col in scores.columns:
            full_df[col] = list(scores[col])
    return raw_df, full_df


def evaluate_negative(df: pd.DataFrame) -> pd.DataFrame:
    """跑拒答集：只关心是否正确拒答 + 分数分布。"""
    rows: List[Dict[str, Any]] = []
    for i, q in enumerate(df["question"].tolist()):
        print(f"[拒答集 {i + 1}/{len(df)}] {q[:40]}...")
        answer, _ctx, num_docs, top_score = run_rag_query(q)
        rows.append({
            "question": q,
            "note": df["note"].iloc[i] if "note" in df.columns else "",
            "answer": answer,
            "num_docs": num_docs,
            "top_rerank_score": top_score,
            "is_refusal": is_refusal(answer),
            "refusal_correct": is_refusal(answer),  # 负样本集期望全部拒答
        })
    return pd.DataFrame(rows)


def print_summary(ans_full: pd.DataFrame, neg_df: pd.DataFrame) -> None:
    print("\n" + "=" * 70)
    print("评估摘要")
    print("=" * 70)

    # ---- 可回答集 ----
    n_a = len(ans_full)
    print(f"\n【可回答集】共 {n_a} 条")
    if n_a:
        # RAGAS 指标
        for col in ["faithfulness", "answer_relevancy", "context_precision",
                    "context_recall", "answer_correctness"]:
            if col in ans_full.columns:
                vals = pd.to_numeric(ans_full[col], errors="coerce").dropna()
                if len(vals):
                    print(f"  {col:22s}: {vals.mean():.4f}")
        # 引用指标 (#4)
        cite_rate = ans_full["has_citation"].mean()
        cite_valid = ans_full.loc[ans_full["has_citation"], "citation_valid_rate"].mean() \
            if cite_rate > 0 else 0.0
        print(f"  {'citation_rate(#4)':22s}: {cite_rate:.4f}   (可回答答案中带引用的比例)")
        print(f"  {'citation_valid_rate':22s}: {cite_valid:.4f}   (引用编号落在检索范围内的比例)")
        # 误拒（可回答却不该拒却拒了）
        wrong_refuse = ans_full["is_refusal"].sum()
        if wrong_refuse:
            print(f"  ⚠️ 误拒答: {int(wrong_refuse)}/{n_a} 条（阈值可能偏高）")
        # 分数分布
        scores = ans_full["top_rerank_score"].tolist()
        print(f"  reranker最高分: min={min(scores):.3f} max={max(scores):.3f} "
              f"mean={sum(scores)/len(scores):.3f}")

    # ---- 拒答集 ----
    n_r = len(neg_df)
    print(f"\n【拒答集】共 {n_r} 条")
    if n_r:
        acc = neg_df["refusal_correct"].mean()
        print(f"  {'refusal_accuracy(#5)':22s}: {acc:.4f}   (该拒答的用例中正确拒答的比例)")
        miss = neg_df.loc[~neg_df["refusal_correct"], ["question", "top_rerank_score"]]
        for _, r in miss.iterrows():
            print(f"  ⚠️ 未拒答: score={r['top_rerank_score']:.3f}  {r['question'][:30]}")
        if len(neg_df):
            scores = neg_df["top_rerank_score"].tolist()
            print(f"  reranker最高分: min={min(scores):.3f} max={max(scores):.3f} "
                  f"mean={sum(scores)/len(scores):.3f}")

    # ---- 阈值建议 (#5 校准) ----
    if n_a and n_r:
        a_min = ans_full["top_rerank_score"].min()
        r_max = neg_df["top_rerank_score"].max()
        print("\n【阈值校准建议】")
        if a_min > r_max:
            mid = (a_min + r_max) / 2
            print(f"  两集分数完全可分：可回答最低 {a_min:.3f} > 拒答最高 {r_max:.3f}")
            print(f"  → 建议 RAG_REFUSE_THRESHOLD = {mid:.2f}（当前 "
                  f"{os.getenv('RAG_REFUSE_THRESHOLD','0.4(默认)')}）")
        else:
            print(f"  两集分数有重叠：可回答最低 {a_min:.3f} ≤ 拒答最高 {r_max:.3f}")
            print(f"  → 阈值无法完美区分，需结合更准的检索/负样本；可取重叠区中点微调")
    print("=" * 70)


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG 增强评估")
    parser.add_argument("--no-ragas", action="store_true",
                        help="跳过 RAGAS（不调 LLM 评判），只跑引用/拒答/阈值校准，速度快")
    args = parser.parse_args()

    global RUN_RAGAS
    RUN_RAGAS = not args.no_ragas

    print("RAG 增强评估 - RAGAS + 引用(#4) + 拒答(#5) + 阈值校准")
    print(f"RAGAS: {'启用' if RUN_RAGAS else '跳过（--no-ragas）'}")

    ans_df = read_answerable()
    neg_df = read_negative()
    print(f"可回答集 {len(ans_df)} 条 / 拒答集 {len(neg_df)} 条")

    llm_client = emb_client = None
    if RUN_RAGAS and len(ans_df) > 0:
        llm_client, emb_client = step_2_init_ragas_models()

    _, ans_full = evaluate_answerable(ans_df, llm_client, emb_client)
    neg_full = evaluate_negative(neg_df)

    # 合并保存（含 RAGAS + 引用 + 拒答）
    out = pd.concat([ans_full, neg_full], ignore_index=True, sort=False)
    out.to_csv(RESULT_FILE, index=False, encoding="utf-8-sig")
    print(f"\n结果已保存: {RESULT_FILE}")

    print_summary(ans_full, neg_full)
    return 0


if __name__ == "__main__":
    sys.exit(main())
