### Lumy 查询-向量检索节点（独立集合 + file_title 过滤 + 页码输出字段）

"""
与 brain 的差别：
  - 集合：kb_lumy_chunks_v1（LUMY_CHUNKS_COLLECTION）
  - 过滤：不做 item_name 过滤（多家族PDF的item_name是拼接串，`in`精确匹配会漏），
          改用 file_title in [结构化检索命中的文件]；未命中时全库检索
  - 输出字段：带 page / page_end / file_title（答案证据引用需要页码）
"""

import os

from langchain_core.messages import SystemMessage, HumanMessage

from knowledge.processor.query_process.nodes.hyde_search_node import HydeSearchNode
from knowledge.processor.query_process.nodes.vector_search_node import VectorSearchNode
from knowledge.prompts.query.query_prompt import USER_HYDE_PROMPT_TEMPLATE
from knowledge.utils.llm_client_util import get_llm_client_long


def _file_title_expr(files: list) -> str:
    """PG 的 file_name 带 .pdf 后缀，chunk 的 file_title 是 stem，统一成 stem"""
    if not files:
        return ""  # 结构化未命中 → 全 lumy 库检索
    stems = [f[:-4] if f.lower().endswith(".pdf") else f for f in files]
    joined = ", ".join(f'"{s}"' for s in stems)
    return f" file_title in [{joined}]"


class LumyVectorSearchNode(VectorSearchNode):
    name = "search_embedding"

    def _collection_name(self) -> str:
        return os.getenv("LUMY_CHUNKS_COLLECTION", "kb_lumy_chunks_v1")

    def _output_fields(self) -> list:
        return ["chunk_id", "content", "item_name", "file_title",
                "page", "page_end"]

    def _filter_expr(self, state, item_names: list) -> str:
        return _file_title_expr(state.get("entity_files") or [])


class LumyHydeSearchNode(HydeSearchNode):
    name = "search_embedding_hyde"

    def _collection_name(self) -> str:
        return os.getenv("LUMY_CHUNKS_COLLECTION", "kb_lumy_chunks_v1")

    def _output_fields(self) -> list:
        return ["chunk_id", "content", "item_name", "file_title",
                "page", "page_end"]

    def _filter_expr(self, state, item_names: list) -> str:
        return _file_title_expr(state.get("entity_files") or [])

    def generate_call_llm(self, rewritten_query: str,
                          item_names: list) -> str:
        """覆写：HyDE 假设文档生成偶发超时，用长超时客户端（纯文本输出）"""
        llm_client = get_llm_client_long(response_format=False)
        system_prompt = (f"您是一位{item_names}的技术文档领域的专家，"
                         f"主要擅长编写技术文档、操作手册、文档规格说明")
        human_prompt = USER_HYDE_PROMPT_TEMPLATE.format(
            item_hint=item_names, rewritten_query=rewritten_query)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt),
        ]
        llm_response = llm_client.invoke(messages)
        content = getattr(llm_response, 'content', "").strip()
        return content if content else ""
