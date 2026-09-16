"""增强版 RAG 评估

在 RAGAS 5 指标之上补齐本次改造新增：
  - #4 引用  ：答案是否带 [编号]、编号是否落在检索文档范围内（规则可算）
  - #5 拒答  ：该拒答的用例是否拒答、可回答的用例是否作答（拒答准确率）
  - 阈值校准 ：打印可回答/拒答集的 reranker 最高分分布，用于定 RAG_REFUSE_THRESHOLD

数据分工（互不污染）：
  - qa.csv     : 可回答 (question, ground_truth) → RAGAS 5 指标 + 引用指标
  - qa_neg.csv : 该拒答 (question, note)         → 拒答准确率 + 分数分布

RAGAS 通路 eval_plus 自带硬化（专用长超时判分客户端 + 低并发 + NaN 补全 + 空缺即报错），
不复用 eval.py 的 step_6；旧版三处致 NaN 的根因见项目根 问题解决记录.md。

运行（从项目根目录）:
    python eval/eval_plus.py                 # 完整（含 RAGAS）
    python eval/eval_plus.py --no-ragas      # 仅引用/拒答/阈值（快，不调 LLM 评判）
    python eval/eval_plus.py --smoke 2       # 诊断：前 2 条跑 RAGAS 且抛真实异常
    python eval/eval_plus.py --allow-nan     # 仍有空缺只告警不报错（默认空缺则 exit 1）
"""

from __future__ import annotations

import uuid
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

from knowledge.processor.query_process.main_graph import query_app  # noqa: E402
from knowledge.utils.bgem3_client_util import get_bgem3_client  # noqa: E402
from knowledge.processor.query_process.base import setup_logging  # noqa: E402

# 统一日志配置：控制台 + 项目根 logs/日志.log（幂等，重复调用不叠加 handler）
setup_logging()

# RAGAS 0.4：自带长超时判分客户端 + 低并发 + NaN 补全（build_ragas_judge / run_ragas_with_retry）
import warnings  # noqa: E402
warnings.filterwarnings("ignore", category=DeprecationWarning, module="ragas")
from ragas import evaluate as ragas_evaluate  # noqa: E402
from ragas.metrics import (  # noqa: E402
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
    answer_correctness,
)
from ragas.run_config import RunConfig  # noqa: E402
from ragas.llms.base import LangchainLLMWrapper  # noqa: E402  # bypass_n 用
from datasets import Dataset  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from langchain_core.embeddings import Embeddings  # noqa: E402  # LangchainCompatibleEmbeddings 基类

# ==================== 配置 ====================
ANSWERABLE_FILE = EVAL_DIR / "qa.csv"
NEGATIVE_FILE = EVAL_DIR / "qa_neg.csv"
RESULT_FILE = EVAL_DIR / "qa_result_plus.csv"   # 增强结果输出（区别于 eval.py 的 qa_result.csv）

RUN_RAGAS = True  # 由 main() 里 argparse 覆盖；True=跑 RAGAS，False=只跑引用/拒答/阈值

# 答案中的引用标记，形如 [0] [1] [0][2]
CITATION_RE = re.compile(r"\[(\d+)\]")
# 拒答文案特征（与 answer_node.check_context_sufficient 的拒答模板保持一致）
REFUSAL_MARKERS = "资料不足，暂无法"


# ==================== 内联工具（原 eval.py；该文件待删除，唯一来源迁入此处） ====================
class LangchainCompatibleEmbeddings(Embeddings):
    """把 BGEM3EmbeddingFunction 包装成 LangChain Embeddings 接口供 RAGAS 使用。

    BGEM3EmbeddingFunction.encode_documents() 在当前 pymilvus 返回 dict
    （{"dense": [...], "sparse": ...}），不是带 .dense 属性的对象——若用
    hasattr(result, 'dense') 判断，对 dict 恒为 False，会掉进对 dict 调
    .tolist() 的分支直接 AttributeError。这里 isinstance 兼容 dict 与旧版对象。
    """

    def __init__(self, bgem3_client):
        self._bgem3_client = bgem3_client

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量编码文档（一次性 encode，比逐条快；RAGAS 一次喂一批）。"""
        result = self._bgem3_client.encode_documents(list(texts))
        dense = result["dense"] if isinstance(result, dict) else result.dense
        return [d.tolist() for d in dense]

    def embed_query(self, text: str) -> List[float]:
        """编码单条查询（复用 embed_documents，去重）。"""
        return self.embed_documents([text])[0]


def step_3_extract_context_from_reranked_docs(reranked_docs: List[Dict[str, Any]]) -> List[str]:
    """从 reranked_docs 提取上下文：每条拼成 "【title】\\n{content}" 的独立字符串。"""
    if not reranked_docs:
        return []
    contexts = []
    for doc in reranked_docs:
        content = doc.get("content", "")
        title = doc.get("title", "")
        if title:
            contexts.append(f"【{title}】\n{content}")
        else:
            contexts.append(content)
    return contexts


# ==================== RAGAS 5 指标（自带硬化判分） ====================
RAGAS_METRICS = [
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
    answer_correctness,
]
RAGAS_SCORE_COLS = ["faithfulness", "answer_relevancy", "context_precision",
                    "context_recall", "answer_correctness"]

JUDGE_TIMEOUT = 300.0      # 判分客户端超时（秒）。原 180 太紧——faithfulness/answer_correctness 的结构化 prompt 单次可能近 200s，180 直接 TimeoutError。
RAGAS_MAX_WORKERS = 2      # 低并发，避开 DeepSeek 限流 / 断连。
RAGAS_MAX_RETRIES = 2      # 温和重试。注意：重试只救快失败（429/解析错），救不了慢调用（两次慢调用塞不进一个超时预算）；原 8×max_wait30 会重试风暴吃光预算、把真错掐成误导性 TimeoutError。慢调用的兜底交给 NAN_RETRY_ROUNDS 的按行补跑。
NAN_RETRY_ROUNDS = 3       # 按行补跑：某格 NaN 就整行重判，最多 3 轮。与 RAGAS_MAX_RETRIES 互补——前者治慢，后者治错。


def build_ragas_judge() -> "ChatOpenAI":
    """构建 RAGAS 专用判分 LLM：temperature=0 + 长超时。

    不沿用 get_llm_client：它把客户端 timeout 硬编码 30s（适合生产答题路径的用户等待），
    但 RAGAS 判分 prompt 很长，30s 易超时 → 该格 NaN。判分客户端独立给 180s。
    不强制 response_format：RAGAS 0.4 经 with_structured_output(function_calling) 走结构化
    输出，DeepSeek-v4 支持 function calling；若 --smoke 仍报解析错再考虑开 JSON 模式。
    """
    return ChatOpenAI(
        model=os.getenv("ITEM_MODEL"),
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_API_BASE"),
        temperature=0.0,
        extra_body={"enable_thinking": False},
        timeout=JUDGE_TIMEOUT,
        request_timeout=JUDGE_TIMEOUT,
    )


def build_ragas_embeddings():
    """RAGAS 所需 embeddings（answer_relevancy / context_precision 会用到）。"""
    return LangchainCompatibleEmbeddings(get_bgem3_client())


def _to_ragas_dataset(rows: List[Dict[str, Any]]) -> Dataset:
    """把 raw 行（含 question/answer/context/ground_truth）拼成 RAGAS 输入 Dataset。"""
    return Dataset.from_list([{
        "question": r["question"],
        "answer": r["answer"],
        "contexts": r["context"].split("\n\n") if r.get("context") else [],
        "ground_truth": r["ground_truth"],
    } for r in rows])


def run_ragas_once(rows: List[Dict[str, Any]], judge_llm, emb_client,
                   run_config: RunConfig, raise_exceptions: bool) -> pd.DataFrame:
    """对给定行跑一次 RAGAS，返回仅含 5 个指标列的 DataFrame（行序与 rows 一致）。"""
    # bypass_n=True：推理模型 / vLLM 端点会拒绝 RAGAS 给 ChatOpenAI 显式设的 .n
    # （报 'Invalid n value (currently only n = 1 is supported)'）。跳过设 .n，n=1 时无损失。
    ragas_llm = LangchainLLMWrapper(judge_llm, run_config=run_config, bypass_n=True)
    result = ragas_evaluate(
        dataset=_to_ragas_dataset(rows),
        metrics=RAGAS_METRICS,
        llm=ragas_llm,
        embeddings=emb_client,
        run_config=run_config,
        raise_exceptions=raise_exceptions,
        show_progress=True,
    )
    scores = result.to_pandas() if hasattr(result, "to_pandas") else pd.DataFrame(result)
    return scores[RAGAS_SCORE_COLS].astype("float64")


def run_ragas_with_retry(rows: List[Dict[str, Any]], judge_llm, emb_client,
                         max_rounds: int = NAN_RETRY_ROUNDS) -> pd.DataFrame:
    """跑 RAGAS 并对空缺行补跑，直到无空缺或用尽轮次。

    返回 shape == (len(rows), 5) 的 DataFrame；仍空缺的格子会在控制台逐个列出。
    """
    run_config = RunConfig(
        timeout=int(JUDGE_TIMEOUT),
        max_retries=RAGAS_MAX_RETRIES,
        max_wait=30,
        max_workers=RAGAS_MAX_WORKERS,
    )
    n = len(rows)
    scores = {col: [None] * n for col in RAGAS_SCORE_COLS}   # None=未填，float=已判分
    idxs = list(range(n))
    for rnd in range(max_rounds + 1):
        if not idxs:
            break
        sub_rows = [rows[i] for i in idxs]
        print(f"  RAGAS 第 {rnd} 轮：判分 {len(sub_rows)} 条（raise_exceptions=False）...")
        sub = run_ragas_once(sub_rows, judge_llm, emb_client, run_config, raise_exceptions=False)
        for local_j, gi in enumerate(idxs):
            for col in RAGAS_SCORE_COLS:
                v = sub[col].iloc[local_j]
                if pd.notna(v):
                    scores[col][gi] = float(v)
        idxs = [gi for gi in idxs
                if any(scores[col][gi] is None for col in RAGAS_SCORE_COLS)]
        if idxs:
            print(f"    仍有 {len(idxs)} 条含空缺，重试...")

    # 残留空缺汇报
    nan_cells = [(rows[i]["question"][:30], c)
                 for i in range(n) for c in RAGAS_SCORE_COLS
                 if scores[c][i] is None]
    if nan_cells:
        print(f"  ⚠️ 经 {max_rounds + 1} 轮仍有 {len(nan_cells)} 个空缺（用 --smoke 抓真实报错）:")
        for q, c in nan_cells[:20]:
            print(f"     - [{c}] {q}...")
    else:
        print(f"  ✓ RAGAS 5 指标 × {n} 条全部出值，无空缺。")
    return pd.DataFrame(scores).astype("float64")


# ==================== RAG 查询 ====================
def run_rag_query(question: str) -> Tuple[str, List[str], int, float]:
    """执行单条 RAG 查询，返回 (answer, contexts, 命中文档数, reranker最高分)。"""
    query_state = {
        "original_query": question,
        "session_id": f"eval_plus_{uuid.uuid4().hex[:8]}",  # 每条独立会话：QA 集是单轮问题，历史必须为空
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
    return REFUSAL_MARKERS in answer


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

    Args:
        llm_client : RAGAS 判分客户端（build_ragas_judge）；--no-ragas 时为 None。
        emb_client : RAGAS embeddings（build_ragas_embeddings）；--no-ragas 时为 None。

    Returns:
        raw_df : 每条的问题/答案/上下文/分数/引用指标
        full_df: raw_df 合并 RAGAS 分数（RUN_RAGAS=False 时无指标列）
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
        rag_rows = raw_df[["question", "answer", "context", "ground_truth"]].to_dict("records")
        scores = run_ragas_with_retry(rag_rows, llm_client, emb_client)
        for col in RAGAS_SCORE_COLS:
            full_df[col] = scores[col].to_numpy()
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
    print("\n" + "=" * 70 + "\n评估摘要\n" + "=" * 70)

    # ---- 可回答集 ----
    n_a = len(ans_full)
    if n_a:
        print("\n【可回答集】")
        for col in RAGAS_SCORE_COLS:                       # 复用常量，别再硬编码 5 个名字
            if col in ans_full.columns:
                v = pd.to_numeric(ans_full[col], errors="coerce").dropna()
                if len(v):
                    print(f"  {col:22s} {v.mean():.4f}")
        cite_rate = ans_full["has_citation"].mean()
        cite_valid = (ans_full.loc[ans_full["has_citation"], "citation_valid_rate"].mean()
                      if cite_rate else 0)
        s = ans_full["top_rerank_score"]
        print(f"  {'citation_rate(#4)':22s} {cite_rate:.4f}")
        print(f"  {'citation_valid_rate':22s} {cite_valid:.4f}")
        print(f"  {'reranker max-score':22s} min={s.min():.3f} mean={s.mean():.3f} max={s.max():.3f}")
        wrong = int(ans_full["is_refusal"].sum())
        if wrong:
            print(f"  ⚠️ 误拒答 {wrong}/{n_a}（阈值可能偏高）")

    # ---- 拒答集 ----
    n_r = len(neg_df)
    if n_r:
        print("\n【拒答集】")
        s = neg_df["top_rerank_score"]
        print(f"  {'refusal_accuracy(#5)':22s} {neg_df['refusal_correct'].mean():.4f}")
        print(f"  {'reranker max-score':22s} min={s.min():.3f} mean={s.mean():.3f} max={s.max():.3f}")
        for _, r in neg_df[~neg_df["refusal_correct"]].iterrows():
            print(f"  ⚠️ 未拒答 score={r['top_rerank_score']:.3f}  {r['question'][:30]}")

    # ---- 阈值校准 (#5) ----
    if n_a and n_r:
        a_min, r_max = ans_full["top_rerank_score"].min(), neg_df["top_rerank_score"].max()
        print("\n【阈值校准】")
        if a_min > r_max:
            print(f"  可分 answerable_min={a_min:.3f} > refuse_max={r_max:.3f}"
                  f"  → 建议 RAG_REFUSE_THRESHOLD={(a_min + r_max) / 2:.2f}"
                  f"（当前 {os.getenv('RAG_REFUSE_THRESHOLD', '0.4(默认)')}）")
        else:
            print(f"  重叠 answerable_min={a_min:.3f} ≤ refuse_max={r_max:.3f}"
                  f"  → 阈值无法完美区分，可取重叠区中点微调")
    print("=" * 70)


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG 增强评估")
    parser.add_argument("--no-ragas", action="store_true",
                        help="跳过 RAGAS（不调 LLM 评判），只跑引用/拒答/阈值校准，速度快")
    parser.add_argument("--smoke", type=int, default=0, metavar="N",
                        help="诊断模式：取前 N 条可回答问题跑 RAGAS，且 raise_exceptions=True "
                             "（不吞异常），用于抓真实判分报错（超时/解析/schema）。跑完即退出。")
    parser.add_argument("--allow-nan", action="store_true",
                        help="RAGAS 仍有空缺指标则只告警不报错（默认：有空缺则 exit 1，杜绝'结果不全'）")
    args = parser.parse_args()

    global RUN_RAGAS
    RUN_RAGAS = not args.no_ragas

    print(f"RAGAS: {'启用' if RUN_RAGAS else '跳过（--no-ragas）'}")

    ans_df = read_answerable()
    neg_df = read_negative()
    print(f"可回答集 {len(ans_df)} 条 / 拒答集 {len(neg_df)} 条")

    judge_llm = emb_client = None
    if RUN_RAGAS and len(ans_df) > 0:
        judge_llm = build_ragas_judge()
        emb_client = build_ragas_embeddings()
        print("RAGAS 判分客户端就绪（专用长超时 180s + 低并发 2）")

    # ---- 诊断模式：单轮、不吞异常，抓真实报错 ----
    if RUN_RAGAS and args.smoke and len(ans_df) > 0:
        n = min(args.smoke, len(ans_df))
        print(f"\n🚩 --smoke 模式：前 {n} 条可回答问题，raise_exceptions=True（真实报错会直接抛出）")
        smoke_rows: List[Dict[str, Any]] = []
        for i in range(n):
            print(f"[smoke {i + 1}/{n}] {ans_df['question'].iloc[i][:40]}...")
            answer, contexts, _num, _top = run_rag_query(ans_df["question"].iloc[i])
            smoke_rows.append({"question": ans_df["question"].iloc[i],
                               "ground_truth": ans_df["ground_truth"].iloc[i],
                               "answer": answer, "context": "\n\n".join(contexts)})
        rc = RunConfig(timeout=int(JUDGE_TIMEOUT), max_retries=RAGAS_MAX_RETRIES,
                       max_wait=30, max_workers=RAGAS_MAX_WORKERS)
        scores = run_ragas_once(smoke_rows, judge_llm, emb_client, rc, raise_exceptions=True)
        print("\nsmoke 通过：N 条全部 5 指标无异常，分数：")
        print(scores.to_string(index=False))
        return 0

    _, ans_full = evaluate_answerable(ans_df, judge_llm, emb_client)
    neg_full = evaluate_negative(neg_df)

    # 合并保存（含 RAGAS + 引用 + 拒答）
    out = pd.concat([ans_full, neg_full], ignore_index=True, sort=False)
    out.to_csv(RESULT_FILE, index=False, encoding="utf-8-sig")
    print(f"\n结果已保存: {RESULT_FILE}")

    print_summary(ans_full, neg_full)

    # ---- 反"结果不全"：RAGAS 空缺则报错 ----
    if RUN_RAGAS and len(ans_full) > 0 and not args.allow_nan:
        nan_cols = [c for c in RAGAS_SCORE_COLS if c in ans_full.columns
                    and pd.to_numeric(ans_full[c], errors="coerce").isna().any()]
        if nan_cols:
            print(f"\n RAGAS 仍有空缺指标列: {nan_cols}")
            print(" 用 --smoke 2 抓真实报错；确认无碍后可用 --allow-nan 强行通过。")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
