from typing import Tuple, List

from knowledge.processor.query_process.base import BaseNode, T
from knowledge.processor.query_process.state import QueryGraphState
from knowledge.utils.bgem3_client_util import get_bgem3_client, generate_hybrid_embeddings
from knowledge.utils.milvus_client_util import get_milvus_client, create_hybrid_search_requests, \
    execute_hybrid_search_query

# 向量检索节点
class VectorSearchNode(BaseNode):
    name = "search_embedding"  # ========== 修正：添加节点名称 ==========

    # ---------- 覆写钩子（lumy 子类定制集合/字段/过滤） ----------
    def _collection_name(self) -> str:
        return self.config.chunks_collection

    def _output_fields(self) -> list:
        return ["chunk_id", "content", "item_name"]

    def _filter_expr(self, state: "QueryGraphState", item_names: list) -> str:
        return self.create_item_name_filter(item_names)

    def process(self, state: QueryGraphState) -> QueryGraphState:
        self.logger.info("========== VectorSearchNode 开始 ==========")
        # 1 参数校验
        item_names, rewritten_query = self.validate_param(state)
        self.logger.info(f"参数校验成功: item_names={item_names}, query={rewritten_query[:50]}...")

        # 2 对重写问题向量化，获取嵌入模型对象
        self.logger.info("获取BGE-M3客户端")
        bgem3_client = get_bgem3_client()
        self.logger.info("BGE-M3客户端获取成功")

        # 获取milvus连接对象
        self.logger.info("获取Milvus客户端")
        milvus_client = get_milvus_client()
        self.logger.info("Milvus客户端获取成功")

        self.logger.info("开始生成混合向量")
        embeddings_result = generate_hybrid_embeddings(
            bgem3_client, embedding_documents=[rewritten_query])
        self.logger.info("向量生成完成")

        # 非空判断
        if not embeddings_result:
            self.logger.warning("向量生成失败，返回空结果")
            return {"embedding_chunks": []}

        # 3 构建item_name标量字段条件，item_name in ["xxx", "yyy"]
        item_name_filter_expr = self._filter_expr(state, item_names)
        self.logger.info(f"构建过滤条件: {item_name_filter_expr}")

        # 4 构建问题向量化之后 向量条件
        self.logger.info("构建混合搜索请求")
        hybrid_requests = create_hybrid_search_requests(
            # 稠密向量
            dense_vector = embeddings_result["dense"][0],

            # 稀疏向量
            sparse_vector = embeddings_result["sparse"][0],

            # 标量字段条件表达式
            expr = item_name_filter_expr,
            limit = 5
        )
        self.logger.info("搜索请求构建完成")

        # 5 执行混合检索（pymilvus的方法）
        collection_name = self._collection_name()
        self.logger.info(f"开始执行Milvus检索: collection={collection_name}")
        res = execute_hybrid_search_query(
            milvus_client=milvus_client,
            collection_name=collection_name,
            search_requests=hybrid_requests,
            # ranker_weights=(0.5, 0.5),
            norm_score=True,
            output_fields=self._output_fields()
        )
        self.logger.info(f"Milvus检索完成，返回{len(res[0]) if res and res[0] else 0}条结果")
        self.logger.debug(f"Milvus原始检索结果: {res}")

        if not res or not res[0]:
            self.logger.info("检索结果为空，返回空state")
            return {"embedding_chunks": []}
        # 6 更新state返回
        self.logger.info("========== VectorSearchNode 完成 ==========")
        return {"embedding_chunks": res[0]} # 为啥不是res

    # 参数校验
    def validate_param(self, state: QueryGraphState) -> Tuple[List[str], str]:
        rewritten_query = state.get('rewritten_query')
        item_names = state.get('item_names', [])
        if not rewritten_query:
            raise ValueError("rewritten_query is empty")
        # ========== 优化：允许 item_names 为空（进行全库检索）==========
        # if not item_names:
        #     raise ValueError("item_names is empty")
        return item_names, rewritten_query

    # 构建查询标量条件表达式
    def create_item_name_filter(self, item_names: List[str]) -> str:
        # ========== 优化：如果 item_names 为空，返回空过滤条件（检索所有数据）==========
        if not item_names:
            return ""  # 空过滤条件，检索所有文档
        item_name_filter = ", ".join(f'"{name}"' for name in item_names)
        return f" item_name in [{item_name_filter}]"


if __name__ == "__main__":
    from knowledge.processor.query_process.base import setup_logging
    setup_logging()

    state = {
        "rewritten_query": "关于H3C LA2608，如何使用？",
        "item_names": ["H3C LA2608 室内无线网关"],
    }

    vector_search_node = VectorSearchNode()
    result = vector_search_node.process(state)
    print(result)
