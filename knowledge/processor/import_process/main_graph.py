import json
import os

from langgraph.constants import END
from langgraph.graph import StateGraph

from knowledge.processor.import_process.base import setup_logging
from knowledge.processor.import_process.nodes.chunks_embedding_node import ChunksEmbeddingNode
from knowledge.processor.import_process.nodes.document_split import DocumentSplitNode
from knowledge.processor.import_process.nodes.entry_node import EntryNode
from knowledge.processor.import_process.nodes.import_milvus_node import ImportMilvusNode
from knowledge.processor.import_process.nodes.item_name_recognition import ItemNameRecognitionNode
from knowledge.processor.import_process.nodes.knowledge_graph_node import KnowGraphNode
from knowledge.processor.import_process.nodes.md_img import MdImageNode
from knowledge.processor.import_process.nodes.pdf_to_md import PdfToMdNode
from knowledge.processor.import_process.state import ImportGraphState, create_default_state

# Lumy 链路节点（半导体规格书场景）
from knowledge.processor.import_process.nodes.pdf_table_extract import PdfTableExtractNode
from knowledge.processor.import_process.nodes.region_label import RegionLabelNode
from knowledge.processor.import_process.nodes.model_extract import ModelExtractNode
from knowledge.processor.import_process.nodes.pg_import import PgImportNode
from knowledge.processor.import_process.nodes.lumy_chunk_nodes import (
    LumyDocumentSplitNode, LumyImportMilvusNode,
)

# 路由方法
def import_router(state:ImportGraphState):
    # 判断文件类型 md  pdf
    if state.get('is_pdf_read_enabled'):
        return "pdf_to_md"

    if state.get('is_md_read_enabled'):
        return "md_img_node"
    return END

# 通过langGraph机制把多个节点执行
# 两个节点
# entry_node : 文件类型检查
# pdf_to_md: pdf转换md
# entry_node =》 pdf_to_md
# 创建langGraph的builder，添加节点，添加边，编译，返回编译对象结果
def create_graph_import() -> StateGraph:
    # 创建langGraph的builder
    builder = StateGraph(ImportGraphState)

    # 添加节点
    # 设置入口节点
    builder.set_entry_point("entry_node")
    # 添加节点
    nodes = {
        "entry_node": EntryNode(),
        "pdf_to_md": PdfToMdNode(),
        "md_img_node": MdImageNode(),
        "document_split_node": DocumentSplitNode(),
        "item_name_rec_node":ItemNameRecognitionNode(),
        "bge_embedding_node": ChunksEmbeddingNode(),
        "import_milvus_node": ImportMilvusNode(),
        "kg_node":KnowGraphNode()
    }
    # 遍历
    for key,value in nodes.items():
        builder.add_node(key, value)

    # 条件边
    # 根据entry_node节点返回数据判断
    # 如果文档类型是md， 进入到 md_img_node
    # 如果文档类型是pdf，进入到 pdf_to_md
    # 参数一：开始节点位置
    # 参数二：判断（路由）方法
    # 参数三：根据参数二返回结果，决定进入哪个节点
    builder.add_conditional_edges(
        "entry_node",
        import_router,
        {
            "md_img_node":"md_img_node",
            "pdf_to_md":"pdf_to_md",
            END:END
        }
    )

    # 添加边
    # entry_node 到 pdf_to_md/md_img_node 的路由由条件边处理，不需要无条件边
    builder.add_edge("pdf_to_md", "md_img_node")
    builder.add_edge("md_img_node", "document_split_node")
    builder.add_edge("document_split_node", "item_name_rec_node")
    builder.add_edge("item_name_rec_node", "bge_embedding_node")
    builder.add_edge("bge_embedding_node", "import_milvus_node")

    # ============================================================================
    # 知识图谱节点配置
    # ============================================================================
    # 当前状态：❌ 已关闭（跳过知识图谱构建）
    # 处理速度：约 10 小时处理 40 个文件（237MB）
    # 功能影响：仅向量检索问答，无知识图谱关系推理

    # [关闭知识图谱] 直接从向量导入结束（当前使用）
    builder.add_edge("import_milvus_node", END)

    # [开启知识图谱] 如需启用知识图谱功能，请按以下步骤操作：
    # 步骤1: 注释掉上面的这行：builder.add_edge("import_milvus_node", END)
    # 步骤2: 取消下面两行的注释：
    # builder.add_edge("import_milvus_node", "kg_node")
    # builder.add_edge("kg_node", END)
    #
    # 开启后效果：
    # - 处理时间：约 3-4 天处理 40 个文件（237MB）
    # - 功能增强：支持实体关系推理、知识图谱可视化
    # - 资源消耗：需要更多内存和 Neo4j 存储空间
    # - 适用场景：需要复杂关系推理、实体链接分析
    #
    # 注意事项：
    # - 确保虚拟机内存充足（建议 16GB+）
    # - 确保磁盘空间充足（建议 50GB+）
    # - LLM API 调用次数会大幅增加（约 30 万次）
    # ============================================================================

    # 图编译，返回编译之后对象
    graph = builder.compile()
    return graph


# ============================================================================
# Lumy 场景导入图（半导体规格书：结构化链路B + 语义链路A）
# 链路B：pdf_table_extract → region_label → model_extract → pg_import
# 链路A：lumy_split(带页码分块) → bge_embedding → lumy_import_milvus
# 通过环境变量 KB_SCENARIO=lumy 启用；默认 brain 走上方原图，行为不变
# ============================================================================
def create_graph_import_lumy() -> StateGraph:
    builder = StateGraph(ImportGraphState)

    builder.set_entry_point("entry_node")
    nodes = {
        "entry_node": EntryNode(),
        # 链路B（结构化）
        "pdf_table_extract": PdfTableExtractNode(),
        "region_label": RegionLabelNode(),
        "model_extract": ModelExtractNode(),
        "pg_import": PgImportNode(),
        # 链路A（语义，带页码）
        "lumy_split": LumyDocumentSplitNode(),
        "bge_embedding_node": ChunksEmbeddingNode(),
        "import_milvus_node": LumyImportMilvusNode(),
    }
    for key, value in nodes.items():
        builder.add_node(key, value)

    builder.add_edge("entry_node", "pdf_table_extract")
    builder.add_edge("pdf_table_extract", "region_label")
    builder.add_edge("region_label", "model_extract")
    builder.add_edge("model_extract", "pg_import")
    builder.add_edge("pg_import", "lumy_split")
    builder.add_edge("lumy_split", "bge_embedding_node")
    builder.add_edge("bge_embedding_node", "import_milvus_node")
    builder.add_edge("import_milvus_node", END)

    return builder.compile()


# 场景开关：KB_SCENARIO=lumy 时导入图走 Lumy 双链路，否则保持 brain 原图
graph = (create_graph_import_lumy()
         if os.getenv("KB_SCENARIO", "brain") == "lumy"
         else create_graph_import())

# 测试
# 构建状态数据，流式输出
def run_graph_import(import_file_path:str,
                     file_dir:str):
    # 获取graph对象
    # graph = create_graph_import()
    # 构建状态数据
    state = {
        "import_file_path":import_file_path,
        "file_dir":file_dir
    }
    # 解包
    init_state = create_default_state(**state)
    # 图执行
    final_state = None
    for event in graph.stream(init_state):
        # event字典遍历
        for node_name,state in event.items():
            print(f"运行节点的:{node_name},state:{state}")
            final_state = state
    return final_state

if __name__ == "__main__":
    setup_logging()
    import_file_path = r"D:\6W100-整本手册.pdf"
    file_dir = r"D:\dev\test"
    # 1. 测试编排流程
    final_state=run_graph_import(
        import_file_path=import_file_path,
                    file_dir=file_dir)
    print(json.dumps(final_state, indent=2,
                     ensure_ascii=False))