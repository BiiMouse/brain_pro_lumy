from typing import List, Dict, Any

from knowledge.processor.query_process.base import BaseNode
from knowledge.processor.query_process.state import QueryGraphState
from knowledge.utils.bge_rerank_util import get_reranker_model
import logging
logger = logging.getLogger(__name__)

# rerank融合节点
class RerankSearchNode(BaseNode):
    name = "rerank"  # ========== 修正：添加节点名称 ==========
    def process(self, state:QueryGraphState)->QueryGraphState:
        #1 获取输入问题
        user_query = (
                state.get('rewritten_query','')
                or state.get('original_query',''))

        #2 获取融合数据，合并一起
        # web搜索数据 + rrf融合数据
        merged_multi_doc:List[Dict[str,Any]] = self.merge_multi_data(state)
        self.logger.info(f"精排候选合并 {len(merged_multi_doc)} 条")

        # 空候选保护：两路检索都为空时直接返回，避免 compute_score([]) 崩溃
        if not merged_multi_doc:
            self.logger.info("融合后候选为空，跳过 Rerank")
            state['reranked_docs'] = []
            return state

        # ========== 性能优化：限制Reranker输入数量（CPU模式优化）==========
        # 3. 限制最大输入数量（避免CPU模式下Reranker推理过慢）
        #    原因：CPU模式下BGE-Reranker推理速度约50-100ms/文档，30个文档需要1.5-3秒
        #    优化：限制在20个文档以内，优先保留RRF得分高的文档
        MAX_RERANK_INPUT = 20
        if len(merged_multi_doc) > MAX_RERANK_INPUT:
            self.logger.info(f"Reranker输入文档数量 {len(merged_multi_doc)} 超过限制，截取前 {MAX_RERANK_INPUT} 个")
            merged_multi_doc = merged_multi_doc[:MAX_RERANK_INPUT]

        #4 把输入问题 + 数据 传递 Reranker模型，进行精排处理
        # 和输入问题语义相似度降序排列之后列表
        reranker_doc:List[Dict[str,Any]] = (
            self.rerank_merged_doc(user_query, merged_multi_doc))
        top_scores = [round(d.get('score') or 0.0, 4) for d in reranker_doc[:5]]
        self.logger.info(
            f"精排完成 | 输入 {len(merged_multi_doc)} 条 | Top5分数: {top_scores}")

        #5 断崖式检测（把上一步答案分数过低去掉）
        cutoff_doc = self.cliff_cutoff(reranker_doc)
        self.logger.info(
            f"断崖截断 {len(reranker_doc)} → {len(cutoff_doc)} 条")

        #6 更新state返回
        state['reranked_docs'] = reranker_doc
        return state

    # 把web搜索数据 + rrf融合数据 合并到一个列表里面
    def merge_multi_data(self,state:QueryGraphState
                         )->List[Dict[str,Any]]:
        # 定义列表，封装最终数据
        # [{content:'111',title:'444'},{...}]
        final_data = []
        # 处理rrf数据（or [] 兜底：lumy 图无 web_search 节点时通道可能未设置）
        rrf_chunks = state.get('rrf_chunks') or []
        for rrf_doc in rrf_chunks:
            content = rrf_doc.get('content')
            if not content:
                continue
            chunk_id = rrf_doc.get('chunk_id','')
            title = rrf_doc.get('title','')
            chunk_dict_data = {
                "content":content,
                "title":title,
                "chunk_id":chunk_id,
                # lumy 链路的证据字段（brain 链路无此字段时为空串，向后兼容）
                "page": rrf_doc.get('page', ''),
                "page_end": rrf_doc.get('page_end', ''),
                "file_title": rrf_doc.get('file_title', ''),
            }
            final_data.append(chunk_dict_data)

        # 处理web搜索数据
        web_search_docs = state.get('web_search_docs') or []
        for web_doc in web_search_docs:
            content = (web_doc.get('content','')
                       or web_doc.get('snippet',''))
            if not content:
                continue
            title = web_doc.get('title','')
            url = web_doc.get('url', '')
            # 构建字典
            web_doc_dict = {
                "content":content,
                "title":title,
                "url":url
            }
            final_data.append(web_doc_dict)
        return final_data

    # 根据用户问题 + 问题答案列表 精排处理
    # user_query用户问题
    # merged_multi_doc问题答案列表
    def rerank_merged_doc(self,
                user_query:str,
               merged_multi_doc:List[Dict[str,Any]]
                )->List[Dict[str,Any]]:
        # 1 获取reranker模型对象
        reranker_model = get_reranker_model()

        # 2 使用reranker模块精排操作，传入问题+答案列表
        # [(问题,答案)]
        query_doc = [(user_query,doc.get('content'))
                     for doc in merged_multi_doc
                     ]
        # 根据问题计算答案分数[0.333 , 0.666]，normalize=True：sigmoid 归一化为 0~1 概率，
        # 与 RAG_REFUSE_THRESHOLD 量纲一致；开关见 config.rerank_normalize。
        normalize = self.config.rerank_normalize
        logger.info(f"reranker正在开始计算分数")
        reranker_score = (
            reranker_model.compute_score(
                sentence_pairs=query_doc,
                normalize=normalize,
                max_length=self.config.rerank_max_length))
        logger.info(f"reranker 完成计算分数")
        # 单条输入时 compute_score 返回标量，统一成列表便于 zip
        if not isinstance(reranker_score, list):
            reranker_score = [reranker_score]

        # 根据计算分数找到对应文档，根据分数对文档排序，
        # ['qq','33','3355']  , [0.1233, 0.0123, 0.03455]
        # [{doc,score}]
        score_doc = [{**doc,"score":score}
                       for doc,score in zip(merged_multi_doc,reranker_score)]

        # 对score_doc数据根据score分数降序
        sorted_score_doc = sorted(score_doc,
            key=lambda x: x['score'],reverse=True
        )
        return sorted_score_doc

    # 断崖式检测（把根据分数排序之后列表去掉分数过低数据）
    def cliff_cutoff(self,reranker_doc:List[Dict[str,Any]]
                     )->List[Dict[str,Any]]:
        # 上限 和 下限
        upper = min(10,len(reranker_doc))
        lower = min(3,upper)

        cutoff_pos = upper
        for i in range(lower-1,upper-1):
            # 当前分数
            current_score = reranker_doc[i].get('score')
            # 下一个位置分数
            next_score = reranker_doc[i+1].get('score')
            # 非空判断
            if current_score is None or next_score is None:
                continue

            # 计算当前分数 和 下一个分数差值
            chazhi = current_score - next_score

            # 相对落差百分比
            baifenbi = chazhi / (abs(current_score) + 1e-6)

            if chazhi >= 0.5 or baifenbi >= 0.25:
                cutoff_pos = i + 1
                break
        return reranker_doc[:cutoff_pos]

if __name__ == "__main__":

    mock_state = {
        "rewritten_query": "怎么测这块主板的短路问题？",
        "rrf_chunks": [
            {"chunk_id": "local_1", "title": "主板维修手册",
             "content": "主板短路通常表现为通电后风扇转一下就停，可以使用万用表的蜂鸣档测量。"},
            {"chunk_id": "local_2", "title": "闲聊",
             "content": "今天中午去吃猪脚饭吧，这块主板外观很漂亮。"},
        ],
        "web_search_docs": [
            {"url": "https://example.com/repair", "title": "短路查修指南",
             "snippet": "主板通电前先打各主供电电感的对地阻值，阻值偏低就是短路。"},
            {"url": "https://example.com/news", "title": "科技新闻",
             "snippet": "苹果发布新款手机，A系列芯片性能提升20%。"},
        ],
    }

    node = RerankSearchNode()
    result = node.process(mock_state)
    print(result)