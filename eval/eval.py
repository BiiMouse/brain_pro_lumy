"""基于RAGAS的RAG系统评估程序

本程序用于评估RAG系统的性能，通过读取测试数据集，
执行RAG查询，并使用RAGAS库计算5个关键指标。
"""

import os
import csv
import warnings
import pandas as pd
from typing import List, Dict, Any, Tuple
from dotenv import load_dotenv
from langchain_core.embeddings import Embeddings

# evaluate() 在 RAGAS 0.4 已弃用（仍可用），这里屏蔽其警告
warnings.filterwarnings("ignore", category=DeprecationWarning, module="ragas")
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
    answer_correctness
)
from datasets import Dataset

# 导入项目内部模块
from knowledge.processor.query_process.main_graph import query_app
from knowledge.utils.llm_client_util import get_llm_client
from knowledge.utils.bgem3_client_util import get_bgem3_client

# 加载环境变量
load_dotenv()


class LangchainCompatibleEmbeddings(Embeddings):
    """将 BGEM3EmbeddingFunction 包装为 LangChain 兼容接口

    RAGAS 需要 LangChain 标准的 embeddings 接口，
    但 BGEM3EmbeddingFunction 是 Milvus 专用格式，需要包装。
    """

    def __init__(self, bgem3_client):
        self._bgem3_client = bgem3_client

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """为文档列表生成向量（LangChain 接口）"""
        embeddings = []
        for text in texts:
            # 使用 BGEM3 编码单个文本
            result = self._bgem3_client.encode_documents([text])
            # 提取 dense 向量（LangChain 只需要 dense 向量）
            if hasattr(result, 'dense'):
                embeddings.append(result.dense[0].tolist())
            else:
                # 如果返回格式不同，尝试直接提取
                embeddings.append(result.tolist())
        return embeddings

    def embed_query(self, text: str) -> List[float]:
        """为单个查询生成向量（LangChain 接口）"""
        result = self._bgem3_client.encode_documents([text])
        if hasattr(result, 'dense'):
            return result.dense[0].tolist()
        else:
            return result.tolist()


def step_1_read_test_data(file_path: str) -> pd.DataFrame:
    """步骤1: 读取测试数据集
    Returns:
        包含测试数据的DataFrame，应包含 question 和 ground_truth 列
    """
    try:
        df = pd.read_csv(file_path, encoding='utf-8-sig')
        print(f"✓ 成功读取测试数据: {file_path}")
        return df
    except Exception as e:
        print(f"✗ 读取测试数据失败: {e}")
        raise


def step_2_init_ragas_models():
    """步骤2: 初始化RAGAS评估所需的模型
    Returns:
        tuple: (llm_client, embedding_client)
    """
    try:
        # 获取LLM客户端（LangChain 标准接口）
        llm_client = get_llm_client()
        print("✓ LLM客户端初始化成功")

        # 获取Embedding客户端
        bgem3_client = get_bgem3_client()
        # 包装为 LangChain 兼容接口
        embedding_client = LangchainCompatibleEmbeddings(bgem3_client)
        print("✓ Embedding客户端初始化成功（已包装为LangChain兼容接口）")

        return llm_client, embedding_client
    except Exception as e:
        print(f"✗ 模型初始化失败: {e}")
        raise


def step_3_extract_context_from_reranked_docs(reranked_docs: List[Dict[str, Any]]) -> List[str]:
    """步骤3: 从reranked_docs中提取上下文内容
    Returns:
        文档内容列表，每个元素是一个独立的文档字符串
    """
    if not reranked_docs:
        return []

    contexts = []
    for doc in reranked_docs:
        content = doc.get('content', '')
        title = doc.get('title', '')

        # 将标题和内容组合
        if title:
            contexts.append(f"【{title}】\n{content}")
        else:
            contexts.append(content)

    return contexts  # 返回列表，不再合并


def step_4_run_rag_query(question: str) -> Tuple[str, List[str]]:
    """步骤4: 执行RAG查询并获取答案和上下文
    question: 用户问题
    tuple: (answer, contexts) - RAG生成的答案和提取的上下文列表
    """
    try:
        # 构建查询状态
        query_state = {
            "original_query": question,
            "session_id": "eval_session",
            "task_id": "eval_task",
            "is_stream": False,
        }

        # 执行RAG查询
        result_state = query_app.invoke(query_state)

        # 提取答案
        answer = result_state.get('answer', '')

        # 提取上下文（从reranked_docs）
        reranked_docs = result_state.get('reranked_docs', [])
        context = step_3_extract_context_from_reranked_docs(reranked_docs)

        print(f"  - 问题: {question[:50]}...")
        print(f"  - 答案长度: {len(answer)} 字符")
        print(f"  - 上下文文档数: {len(context)}")

        return answer, context

    except Exception as e:
        print(f"✗ RAG查询执行失败: {e}")
        return "", []


def step_5_prepare_evaluation_dataset(
    test_df: pd.DataFrame,
    answers: List[str],
    contexts: List[List[str]]
):
    """步骤5: 准备RAGAS评估数据集
    Args:
        test_df: 测试数据DataFrame
        answers: RAG生成的答案列表
        contexts: 提取的上下文列表（每个元素是一个文档列表）
    Returns: HuggingFace Dataset对象，RAGAS可以直接使用
    """
    try:
        # 构建数据字典（contexts已经是列表的列表，直接使用）
        data = []
        for i in range(len(test_df)):
            data.append({
                "question": test_df['question'].iloc[i],
                "answer": answers[i],
                "contexts": contexts[i] if contexts[i] else [],  # 直接使用列表
                "ground_truth": test_df['ground_truth'].iloc[i]
            })

        # 创建HuggingFace Dataset（RAGAS可以直接使用）
        dataset = Dataset.from_list(data)
        print(f"✓ 评估数据集准备完成，共 {len(dataset)} 条")

        return dataset

    except Exception as e:
        print(f"✗ 评估数据集准备失败: {e}")
        raise


def step_6_evaluate_metrics(
    dataset,
    llm_client,
    embedding_client
) -> pd.DataFrame:
    """步骤6: 执行RAGAS评估计算5个指标

    Args:
        dataset: RAGAS评估数据集
        llm_client: LLM客户端
        embedding_client: Embedding客户端

    Returns:
        包含5个指标得分的DataFrame
    """
    try:
        print("\n开始RAGAS评估...")
        print("-" * 60)

        # 兼容不同版本的RAGAS
        # v0.4+: 使用 experiment() 或带参数的 evaluate()
        # v0.3-: 使用旧的 evaluate()
        try:
            # 尝试使用 RAGAS v0.4+ 的 evaluate()（支持 llm 和 embeddings 参数）
            print("  使用自定义 LLM 和 Embedding 模型进行评估...")
            result = evaluate(
                dataset=dataset,
                metrics=[
                    faithfulness,
                    answer_relevancy,
                    context_precision,
                    context_recall,
                    answer_correctness
                ],
                llm=llm_client,
                embeddings=embedding_client
            )
        except TypeError as e:
            # 如果参数不支持，尝试不带 llm/embeddings 的版本
            if "unexpected keyword argument" in str(e):
                print("  ⚠️  当前RAGAS版本不支持 llm/embeddings 参数，使用默认配置")
                print("  注意: 这将使用 OpenAI 的默认模型（需要 OPENAI_API_KEY）")
                result = evaluate(
                    dataset=dataset,
                    metrics=[
                        faithfulness,
                        answer_relevancy,
                        context_precision,
                        context_recall,
                        answer_correctness
                    ]
                )
            else:
                print(f"  ❌ 参数类型错误: {e}")
                raise
        except Exception as e:
            print(f"  ❌ 评估过程出错: {e}")
            print("  提示: 可能是 LLM 或 Embedding 模型配置问题")
            raise

        # 转换为DataFrame格式（兼容不同版本的RAGAS）
        if hasattr(result, 'to_pandas'):
            scores_df = result.to_pandas()
        elif isinstance(result, pd.DataFrame):
            scores_df = result
        else:
            # 如果是字典或其他格式，尝试转换
            scores_df = pd.DataFrame(result)

        print("✓ RAGAS评估完成")
        print("-" * 60)

        return scores_df

    except Exception as e:
        print(f"✗ RAGAS评估失败: {e}")
        raise


def step_7_save_results(
    test_df: pd.DataFrame,
    contexts: List[List[str]],
    answers: List[str],
    scores: pd.DataFrame,
    output_path: str
):
    """步骤7: 保存评估结果到CSV文件

    Args:
        test_df: 原始测试数据
        contexts: 上下文列表（每个元素是一个文档列表）
        answers: 答案列表
        scores: RAGAS评估得分
        output_path: 输出文件路径
    """
    try:
        # 构建结果DataFrame（将contexts列表转换回字符串，方便CSV存储）
        contexts_as_strings = ['\n\n'.join(ctx) for ctx in contexts]

        result_data = {
            'question': test_df['question'].tolist(),
            'context': contexts_as_strings,  # 转换为字符串存储
            'answer': answers,
            'ground_truth': test_df['ground_truth'].tolist(),
        }

        # 添加5个指标列（如果存在）
        score_columns = ['faithfulness', 'answer_relevancy',
                        'context_precision', 'context_recall', 'answer_correctness']

        for col in score_columns:
            if col in scores.columns:
                # 转换为标准Python float类型
                result_data[col] = [float(x) if pd.notna(x) else None
                                   for x in scores[col].tolist()]

        result_df = pd.DataFrame(result_data)

        # 保存为UTF-8 BOM编码的CSV
        result_df.to_csv(output_path, index=False, encoding='utf-8-sig')

        print(f"\n 评估结果已保存: {output_path}")

    except Exception as e:
        print(f"✗ 保存结果失败: {e}")
        raise


def main():
    """主函数：执行完整的RAG评估流程

    流程步骤：
    1. 读取测试数据
    2. 初始化模型
    3. 执行RAG查询获取答案和上下文
    4. 准备评估数据集
    5. 执行RAGAS评估
    6. 保存评估结果
    """
    print("RAG系统评估程序 - 基于RAGAS")

    # 定义文件路径
    input_file = os.path.join(os.path.dirname(__file__), 'qa.csv')
    output_file = os.path.join(os.path.dirname(__file__), 'qa_result.csv')

    try:
        # ========== 步骤1: 读取测试数据 ==========
        print("\n【步骤1】读取测试数据集\n")
        test_df = step_1_read_test_data(input_file)

        # 验证必需列
        required_columns = ['question', 'ground_truth']
        for col in required_columns:
            if col not in test_df.columns:
                raise ValueError(f"测试数据缺少必需列: {col}")

        # ========== 步骤2: 初始化模型 ==========
        print("\n【步骤2】初始化RAGAS评估模型\n")

        llm_client, embedding_client = step_2_init_ragas_models()

        # ========== 步骤3-4: 执行RAG查询 ==========
        print("\n【步骤3-4】执行RAG查询\n")

        answers = []
        contexts = []

        for idx, row in test_df.iterrows():
            question = row['question']
            print(f"\n处理第 {idx + 1}/{len(test_df)} 条数据...")

            # 执行RAG查询
            answer, context = step_4_run_rag_query(question)
            answers.append(answer)
            contexts.append(context)

        # ========== 步骤5: 准备评估数据集 ==========
        print("\n【步骤5】准备RAGAS评估数据集\n")

        dataset = step_5_prepare_evaluation_dataset(test_df, answers, contexts)

        # ========== 步骤6: 执行RAGAS评估 ==========
        print("\n【步骤6】执行RAGAS指标评估\n")

        scores = step_6_evaluate_metrics(dataset, llm_client, embedding_client)

        # 打印评估结果摘要
        print("\n评估结果摘要:\n")
        score_columns = ['faithfulness', 'answer_relevancy',
                        'context_precision', 'context_recall', 'answer_correctness']

        for col in score_columns:
            if col in scores.columns:
                mean_score = scores[col].mean()
                print(f"  {col}: {mean_score:.4f}")

        # ========== 步骤7: 保存评估结果 ==========
        print("\n【步骤7】保存评估结果\n")
        step_7_save_results(test_df, contexts, answers, scores, output_file)

        print("\n" + "=" * 80)
        print("✓ 评估完成！")

    except Exception as e:
        print(f"\n✗ 评估过程出错: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
