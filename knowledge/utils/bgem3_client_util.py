# import os
#
# from dotenv import load_dotenv
# from pymilvus.model.hybrid import BGEM3EmbeddingFunction
#
# # 获取嵌入模型客户端对象
# load_dotenv()
#
# def get_bgem3_client():
#     try:
#         bge_m3 = BGEM3EmbeddingFunction(
#             model_name=os.getenv("BGE_M3_PATH"),
#             device="cpu",
#             use_fp16=False,
#             return_colbert_vecs=False
#         )
#         return bge_m3
#     except Exception as e:
#         raise e

import os
from typing import List
import logging

from dotenv import load_dotenv
from pymilvus.model.hybrid import BGEM3EmbeddingFunction

# 获取嵌入模型客户端对象
load_dotenv()

logger = logging.getLogger(__name__)

# 全局缓存模型实例
_bgem3_client = None


def get_bgem3_client():
    """获取BGE-M3模型客户端（带缓存）"""
    global _bgem3_client
    try:
        if _bgem3_client is None:
            logger.info("首次加载BGE-M3模型...")
            _bgem3_client = BGEM3EmbeddingFunction(
                model_name=os.getenv("BGE_M3_PATH"),
                device="cpu",
                use_fp16=False,
                return_colbert_vecs=False
            )
            logger.info("BGE-M3模型加载完成")
        return _bgem3_client
    except Exception as e:
        raise e


def warmup_models():
    """预热模型：在服务启动时预加载模型

    用法：
        在 query_router.py 或 import_router.py 的 startup 事件中调用
    """
    try:
        logger.info("🔥 开始预热模型...")
        # 预热BGE-M3
        get_bgem3_client()
        # 预热BGE-Reranker
        from knowledge.utils.bge_rerank_util import get_reranker_model
        get_reranker_model()
        logger.info("✅ 模型预热完成")
    except Exception as e:
        logger.warning(f"⚠️  模型预热失败: {e}")

def generate_hybrid_embeddings(embedding_model: BGEM3EmbeddingFunction,
                               embedding_documents: List[str]):
    """
    为文本生成向量嵌入
    :param embedding_model: 嵌入模型(这里使用BGEM3)
    :param embedding_documents: 要生成嵌入的文本列表
    :return: 包含dense和sparse向量的字典
    """
    try:
        # 1. 生成嵌入
        embedding_result=(embedding_model.encode_documents(embedding_documents))

        processed_sparse_result = []
        # 2. 遍历每一个文档
        for index in range(len(embedding_documents)):
            # 2.1 解构csr矩阵&获取稀疏向量
            csr_array = embedding_result['sparse']
            # a) 行索引
            ind_ptr = csr_array.indptr
            # b) 获取行索引的起始值
            start_ind_ptr = ind_ptr[index]
            end_ind_ptr = ind_ptr[index+1]
            # c) 获取token_id
            token_id=(csr_array.indices[start_ind_ptr:end_ind_ptr].tolist())
            # d) 获取权重
            weight=(csr_array.data[start_ind_ptr:end_ind_ptr].tolist())
            # 2.2 获取稀疏向量
            sparse_vector = dict(zip(token_id, weight))
            processed_sparse_result.append(sparse_vector)
        # 3. 返回
        return {
            "dense": [den.tolist() for den in embedding_result["dense"]],
            "sparse": processed_sparse_result
        }
    except Exception as e:
        return None