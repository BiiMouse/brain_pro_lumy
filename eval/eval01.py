"""使用 Ragas 对知识库 RAG 流程进行批量评估。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
from datasets import Dataset
from langchain_core.embeddings import Embeddings
from ragas import evaluate
from ragas.metrics import (
    answer_correctness,
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)
from ragas.run_config import RunConfig


EVAL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EVAL_DIR.parent
INPUT_FILE = EVAL_DIR / "qa.csv"
OUTPUT_FILE = EVAL_DIR / "qa_result.csv"

# 允许通过 ``python eval/eval.py`` 从项目根目录直接运行程序。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from knowledge.processor.query_process.main_graph import query_app
from knowledge.processor.query_process.state import create_default_state
from knowledge.utils.bge_m3_embedding_http_util import (
    generate_hybrid_embeddings,
    get_beg_m3_embedding_model,
)
from knowledge.utils.txt_llm_client_util import get_llm_client


OUTPUT_COLUMNS = [
    "question",
    "context",
    "answer",
    "ground_truth",
    "Faithfulness",
    "Answer Relevancy",
    "Context Precision",
    "Context Recall",
    "Answer Correctness",
]

METRIC_COLUMN_MAP = {
    "faithfulness": "Faithfulness",
    "answer_relevancy": "Answer Relevancy",
    "context_precision": "Context Precision",
    "context_recall": "Context Recall",
    "answer_correctness": "Answer Correctness",
}


class BgeM3LangChainEmbeddings(Embeddings):
    """将项目的 BGE-M3 模型适配为 Ragas 可使用的 LangChain 接口。"""

    def __init__(self, embedding_model: Any) -> None:
        """保存由项目工具创建的 BGE-M3 模型。"""
        self.embedding_model = embedding_model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """为一批文档生成 BGE-M3 稠密向量。"""
        if not texts:
            return []
        result = generate_hybrid_embeddings(self.embedding_model, texts)
        if result is None:
            raise RuntimeError("BGE-M3 文档向量生成失败")
        return result["dense"]

    def embed_query(self, text: str) -> list[float]:
        """为单条查询生成 BGE-M3 稠密向量。"""
        embeddings = self.embed_documents([text])
        return embeddings[0]


def step_1_load_test_set(input_file: Path = INPUT_FILE) -> pd.DataFrame:
    """读取并校验包含 question、ground_truth 的评估测试集。"""
    if not input_file.is_file():
        raise FileNotFoundError(f"评估测试集不存在: {input_file}")

    test_df = pd.read_csv(input_file, encoding="utf-8-sig")
    required_columns = {"question", "ground_truth"}
    missing_columns = required_columns.difference(test_df.columns)
    if missing_columns:
        missing_text = ", ".join(sorted(missing_columns))
        raise ValueError(f"评估测试集缺少必要列: {missing_text}")
    if test_df.empty:
        raise ValueError("评估测试集不能为空")

    test_df = test_df.loc[:, ["question", "ground_truth"]].copy()
    if test_df.isnull().any().any():
        raise ValueError("question 和 ground_truth 列不能包含空值")
    test_df["question"] = test_df["question"].astype(str).str.strip()
    test_df["ground_truth"] = test_df["ground_truth"].astype(str).str.strip()
    if (test_df == "").any().any():
        raise ValueError("question 和 ground_truth 列不能包含空字符串")
    return test_df


def _extract_contexts(reranked_docs: list[Any]) -> list[str]:
    """从 state.reranked_docs 中提取非空的 content 作为上下文证据。"""
    contexts: list[str] = []
    for doc in reranked_docs:
        if isinstance(doc, dict):
            content = str(doc.get("content") or "").strip()
        else:
            content = str(getattr(doc, "page_content", "") or "").strip()
        if content:
            contexts.append(content)
    return contexts


def step_2_run_rag(test_df: pd.DataFrame) -> pd.DataFrame:
    """逐条调用 query_app.invoke，并收集答案及重排后的上下文证据。"""
    rag_rows: list[dict[str, Any]] = []
    session_id = f"ragas-eval-{uuid4().hex}"

    for row_number, row in enumerate(test_df.itertuples(index=False), start=1):
        question = row.question
        print(f"[{row_number}/{len(test_df)}] 正在执行 RAG: {question}")
        state = create_default_state(
            original_query=question,
            session_id=session_id,
            task_id=f"ragas-eval-{uuid4().hex}",
            message_id=f"ragas-eval-{uuid4().hex}",
            is_stream=False,
        )
        final_state = query_app.invoke(state)
        if not isinstance(final_state, dict):
            raise RuntimeError(f"RAG 未返回有效 state，问题: {question}")

        answer = str(final_state.get("answer") or "").strip()
        contexts = _extract_contexts(final_state.get("reranked_docs") or [])
        rag_rows.append(
            {
                "question": question,
                "contexts": contexts,
                "answer": answer,
                "ground_truth": row.ground_truth,
            }
        )

    return pd.DataFrame(rag_rows)


def step_3_get_evaluation_models() -> tuple[Any, Embeddings]:
    """通过项目模型工具获取 Ragas 使用的 LLM 与 BGE-M3 嵌入模型。"""
    # Ragas 的判分提示使用 Pydantic JSON 结构，开启 JSON 模式可减少解析失败。
    llm = get_llm_client(temperature=0.0, response_format=True)
    if llm is None:
        raise RuntimeError("无法通过 get_llm_client 获取评估 LLM")

    embedding_model = get_beg_m3_embedding_model()
    if embedding_model is None:
        raise RuntimeError("无法通过 get_beg_m3_embedding_model 获取嵌入模型")
    return llm, BgeM3LangChainEmbeddings(embedding_model)


def step_4_evaluate_with_ragas(
    rag_df: pd.DataFrame, llm: Any, embeddings: Embeddings
) -> pd.DataFrame:
    """使用五项 Ragas 指标评估，并容忍单个模型结果解析失败。"""
    evaluation_dataset = Dataset.from_dict(
        {
            "question": rag_df["question"].tolist(),
            "contexts": rag_df["contexts"].tolist(),
            "answer": rag_df["answer"].tolist(),
            "ground_truth": rag_df["ground_truth"].tolist(),
        }
    )
    evaluation_result = evaluate(
        dataset=evaluation_dataset,
        metrics=[
            faithfulness,
            answer_relevancy,
            context_precision,
            context_recall,
            answer_correctness,
        ],
        llm=llm,
        embeddings=embeddings,
        # DashScope 模型偶尔可能不遵循 Ragas 的 Pydantic 输出结构。
        # 单项失败时返回 NaN，避免已完成的其他评估结果被整批丢弃。
        raise_exceptions=False,
        # 降低并发可减少 DashScope 限流、断连和输出错乱的概率。
        run_config=RunConfig(
            timeout=180,
            max_retries=5,
            max_wait=10,
            max_workers=2,
        ),
    )
    score_df = evaluation_result.to_pandas()

    result_df = rag_df.copy()
    result_df["context"] = result_df["contexts"].apply(lambda items: "\n\n".join(items))
    for ragas_column, output_column in METRIC_COLUMN_MAP.items():
        if ragas_column not in score_df.columns:
            raise RuntimeError(f"Ragas 评估结果缺少指标列: {ragas_column}")
        result_df[output_column] = score_df[ragas_column].to_numpy()
    result_df = result_df.loc[:, OUTPUT_COLUMNS]

    missing_score_count = int(
        result_df[list(METRIC_COLUMN_MAP.values())].isna().sum().sum()
    )
    if missing_score_count:
        print(
            f"警告：有 {missing_score_count} 个指标因模型输出解析失败而记为 NaN，"
            "其余评估结果仍会正常保存。"
        )
    return result_df


def step_5_save_result(
    result_df: pd.DataFrame, output_file: Path = OUTPUT_FILE
) -> None:
    """按要求的九列顺序，以 UTF-8 BOM 编码保存评估结果。"""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(output_file, index=False, encoding="utf-8-sig")


def main() -> None:
    """按读取测试集、执行 RAG、评估、保存的顺序运行完整流程。"""
    test_df = step_1_load_test_set()
    rag_df = step_2_run_rag(test_df)
    llm, embeddings = step_3_get_evaluation_models()
    result_df = step_4_evaluate_with_ragas(rag_df, llm, embeddings)
    step_5_save_result(result_df)
    print(f"评估完成，结果已保存至: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
