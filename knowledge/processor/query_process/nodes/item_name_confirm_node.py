import json
import re
from typing import Dict, Any, List, Tuple

from langchain_core.messages import SystemMessage, HumanMessage

from knowledge.processor.query_process.base import BaseNode
from knowledge.processor.query_process.state import QueryGraphState
from knowledge.prompts.query.query_prompt import ITEM_NAME_EXTRACT_TEMPLATE
from knowledge.utils.bgem3_client_util import get_bgem3_client, generate_hybrid_embeddings
from knowledge.utils.llm_client_util import get_llm_client
from knowledge.utils.milvus_client_util import get_milvus_client, create_hybrid_search_requests, \
    execute_hybrid_search_query
from knowledge.utils.mongo_history_util import get_recent_messages
from knowledge.utils.retry_util import retry_on_rate_limit


# 类：操作llm
class ItemNameLLM():

    # 根据用户输入原始问题 + 上下文会话记录 提取商品名
    def extract_item_name(self,original_query:str,
                          history_text: str,
                          )->Dict[str,Any]:

        print(f"========== 开始 extract_item_name ==========")
        print(f"original_query: {original_query}")
        print(f"history_text: {history_text[:100]}...")

        # 获取llm连接对象
        llm_client = get_llm_client(response_format=True)

        # 构建提示词
        system_prompt = "你是一个专业的客服助手，擅长理解用户意图和提取关键信息。"

        human_prompt = ITEM_NAME_EXTRACT_TEMPLATE.format(
            history_text=history_text,query=original_query)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt),
        ]

        print(f"准备调用LLM...")
        # 调用llm llm_response是llm返回原始内容（添加重试机制）
        # ========== 性能优化：减少重试次数（避免过长等待）==========
        # 原配置：max_retries=5, initial_delay=2.0 → 最坏情况 2+4+8+16+32=62秒等待
        # 优化后：max_retries=2, initial_delay=1.0 → 最坏情况 1+2=3秒等待
        @retry_on_rate_limit(max_retries=2, initial_delay=1.0)
        def _invoke_with_retry():
            return llm_client.invoke(messages)

        llm_response = _invoke_with_retry()
        print(f"LLM调用完成，响应类型: {type(llm_response)}")

        # ========== 性能优化：避免 content 属性访问卡住 ==========
        print(f"开始提取 content 属性...")
        try:
            # 设置一个小超时，避免 content 访问卡住
            import signal

            def timeout_handler(signum, frame):
                raise TimeoutError("提取 content 超时")

            # Windows 不支持 signal.alarm，跳过
            # 只添加详细日志
            llm_content = llm_response.content.strip()
            print(f"content 提取成功")

        except Exception as e:
            print(f"content 提取失败: {e}")
            raise

        print(f"LLM content长度: {len(llm_content)}")

        #对llm_content清洗
        print(f"开始 clean_parse...")
        parse_result = self.clean_parse(llm_content)
        print(f"clean_parse 完成")

        print(f"========== extract_item_name 完成 ==========")
        return parse_result

    # 清洗llm内容
    def clean_parse(self,llm_content) -> Dict[str,Any]:
        # ```json   ```
        cleaned = re.sub(r"^```(?:json)?\s*", "", llm_content.strip())
        content = re.sub(r"\s*```$", "", cleaned)
        print(f"[DEBUG] content长度={len(content)}", flush=True)
        print(f"[DEBUG] content前100字符: {content[:100]}", flush=True)

        # ========== 性能优化：使用 json.loads 直接解析（最简单）==========
        try:
            print(f"[DEBUG] 开始JSON解析...", flush=True)
            parsed_llm_result:Dict[str,Any] = json.loads(content)
            print(f"[DEBUG] JSON解析成功", flush=True)
        except json.JSONDecodeError as e:
            print(f"[DEBUG] JSON解析失败: {e}", flush=True)
            # 如果解析失败，返回默认值
            return {
                'item_names': [],
                'rewritten_query': content
            }

        #去掉parsed_llm_result 的item_names空格
        ori_item_names = parsed_llm_result.get('item_names', [])
        cleaned_item_names = [ori_item for ori_item in ori_item_names if ori_item and ori_item.strip()]

        print(f"[DEBUG] 最终结果: item_names={cleaned_item_names}", flush=True)
        return {
            'item_names': cleaned_item_names,
            'rewritten_query': parsed_llm_result.get('rewritten_query', '')
        }

# 类：操作向量数据库
class ItemNameVector():
    #根据商品名查向量数据库
    # 三件事情
    # * 1 根据item_name查询向量数据库，得到密集和稀疏向量数据
    # * 2 对查询密集和稀疏向量数据 ，评分对齐
    # 可选 3 分数差异过滤（分数大于0.7数据有多个）
    ## 返回两个列表
    ## 第一个列表：分数阈值大于0.7数据
    ## 第二个列表：分数大于0.6  小于0.7 数据
    def match_item_name_filter(self,
           item_names:List[str])->Tuple[List[str],List[str]]:
        # 1 根据item_name查询向量数据库，得到密集和稀疏向量数据
        # [{"",""} , {"",""}]
        search_result:List[Dict[str,Any]] = self.match_vector(item_names)

        # 2 根据向量数据库查询返回密集和稀疏向量，进行评分对齐
        confirmed,options = self.item_name_score_algin(search_result)
        # print("=="*50)
        # print(confirmed)
        # print("==" * 50)
        # print(options)

        # 可选 3 分数差异过滤（分数大于0.7数据有多个）
        # if len(confirmed)>1:
        #     confirmed = self.item_name_score_filter(confirmed,search_result)
        return confirmed,options

    # 根据item_name查询密集和稀疏向量
    def match_vector(self,item_names:List[str]) -> List[Dict[str,Any]]:
        # 定义列表，封装最终结果
        search_result = []

        # 获取milvus连接对象
        milvus_client = get_milvus_client()

        # 把item_names向量化查询
        embedding_model = get_bgem3_client()
        # 通过embedding_model转换密稠和稀疏向量
        # embedding_model.encode_documents(item_names)
        # 调用工具类的方法实现
        # {
        #     "dense": 密稠列表,
        #     "sparse": 稀疏向量
        # }
        hybrid_embedding_result = (
            generate_hybrid_embeddings(embedding_model,item_names))

        # item_names列表获取每个item_name 同时这个item_name对应密稠和稀疏向量
        for index,extract_name in enumerate(item_names):
            # extract_name每个商品名称
            # item_name对应密稠和稀疏向量
            dense_vector = hybrid_embedding_result['dense'][index]
            sparse_vector = hybrid_embedding_result['sparse'][index]

            # 构建混合查询条件
            # 密稠和稀疏向量，转换要求的类型 AnnSearchRequest
            hybrid_search_requests = create_hybrid_search_requests(
                dense_vector=dense_vector,
                sparse_vector=sparse_vector,
            )

            # 调研方法执行查询
            hybrid_search_result =execute_hybrid_search_query(
                milvus_client,
                collection_name="kb_item_names_v2",
                search_requests=hybrid_search_requests,
                ranker_weights=(0.5, 0.5),
                norm_score=True,
                output_fields=["item_name"]
            )

            # 根据向量数据库查询结果，构建返回数据
            # 把每个item_name构建好数据放到最终列表里面 search_result
            # [
            #     [
            #         {
            #             'pk': '466823158374813291',
            #             'distance': 0.7221629619598389,
            #             'entity': {
            #                 'item_name': 'H3CLA2608室内无线网关'
            #             }
            #         }
            #     ]
            # ]
            item_name_search_result = {
                "extracted_name": extract_name,
                "matches":[
                    {
                        "item_name": h["entity"]["item_name"],
                        "score":h["distance"]
                    }
                    for h in (hybrid_search_result[0]
                              if hybrid_search_result else [])
                ]
            }
            search_result.append(item_name_search_result)
        return search_result

    # 评分对齐
    # 参数 search_result查询向量数据库返回结果 列表
    # [
    #     {
    #         "extracted_name": "H3CLA2608",
    #         "matches": [
    #             {
    #                 "item_name": "H3CLA2608",
    #                 "score": 0.7221629619598389
    #             },
    #             {
    #                 "item_name": "H3CLA2608室内无线网关1",
    #                 "score": 0.8221629619598389
    #             }
    #         ]
    #     }
    # ]
    # 返回列表元组 ，有两个列表
    # 第一个列表：分数大于0.7 数据
    # 第二个列表： 分数在0.6 -0.7之间数据
    def item_name_score_algin(self,
               search_result:List[Dict[str,Any]])->Tuple[List[str],List[str]]:
        # 定义两个列表，后面封装使用
        confirmed = [] # 分数大于0.7 数据
        options = [] # 分数在0.6 -0.7之间数据
        # 遍历参数查询结果列表
        for item_name_search_result in search_result:
            # 获取extracted_name 提取商品名称
            extracted_name = item_name_search_result.get('extracted_name')
            # 从获取名称是 matches列表，把这个列表按照score降序排列，得到排列之后列表
            # matches根据分数降序之后列表  sorted方法
            matches = sorted(item_name_search_result.get('matches'),
                   key=lambda x: x['score'],reverse=True)

            # 1 matches列表遍历，得到列表中每部分数据分数 score值
            # 1.1 score 大于 0.7 处理 放到confirmed列表
            high = [m for m in matches if m.get('score')>=0.7]
            if high: # 有大于评分0.7数据
                # 如果数据有一个情况
                # [{....}]
                if len(high)==1:
                    # 把值放到confirmed列表
                    high_item_name_one = high[0]["item_name"]
                    if high_item_name_one not in confirmed:
                        confirmed.append(high_item_name_one)
                # 数据有多个情况
                else: # [{....},{....}]
                    # 把值放到options列表
                    for h in high[:3]:
                        high_item_name_many = h.get("item_name")
                        if (high_item_name_many not in options
                                and high_item_name_many not in confirmed):
                            options.append(high_item_name_many)
            else: # 1.2 score 大于0.6 小于0.7 处理 放到options列表
                mid = [m for m in matches if m['score']>=0.6]
                if mid: # 有大于0.6 小于0.7 数据
                    for m in mid[:3]:
                        m_item_name = m.get("item_name")
                        if (m_item_name not in options
                                and m_item_name not in confirmed):
                            options.append(m_item_name)
        # confirmed: 大于0.7 一个数据
        # options：1 大于0.7多个数据  2 0.6 -0.7范围之间数据
        return confirmed, options

    # 分数差异性过滤
    # def item_name_score_filter(self):
    #     pass

# 商品名确认节点
class ItemNameConfirmNode(BaseNode):
    name = "item_name_confirm"  # ========== 修正：添加节点名称（用于SSE进度反馈） ==========
    def __init__(self):
        super().__init__()
        # 操作llm对象
        self._item_name_llm = ItemNameLLM()
        # 操作向量数据库对象
        self._item_name_vector = ItemNameVector()

    def process(self,state:QueryGraphState)->QueryGraphState:
        print(f"\n========== ItemNameConfirmNode 开始 ==========")
        # 1 获取用户输入原始问题
        original_query = state.get('original_query')
        print(f"original_query: {original_query}")

        # 2 获取用户上下文会话
        session_id = state.get('session_id')
        print(f"session_id: {session_id}")
        # 调用工具类方法，根据session_id获取最近10条会话记录
        chat_history = get_recent_messages(session_id,limit=10)
        print(f"chat_history: {len(chat_history)} 条记录")
        # 把查询mongodb得到历史会话列表，拼接字符串
        history = ""
        for msg in chat_history:
            role = msg.get('role')
            text = msg.get('text')
            history += f"{role}:{text}\n"

        # 3 根据用户输入原始问题+上下文会话调用LLM 提取商品名
        # llm返回格式：在提示词约定好格式
        # {
        #     "item_names": ["商品A", "商品B"],
        #     "rewritten_query": "关于商品A和商品B，..."
        # }
        print(f"开始调用 extract_item_name...")
        llm_result = (
            self._item_name_llm.extract_item_name(original_query,
                                                  history))
        print("调用LLM返回结果：")
        print(llm_result)

        # 4 根据LLM提取商品名，查询向量数据库进行数据处理
        # （查询得到密集和稀疏向量，评分对齐，分数差异化过滤）
        # 从上一步llm返回结果 llm_result 里面获取 商品名名称
        item_names = llm_result.get('item_names')
        rewritten_query = llm_result.get('rewritten_query')
        print(f"item_names: {item_names}")
        print(f"rewritten_query: {rewritten_query}")

        # 判断 item_names是否为空
        if item_names:
            print(f"开始查询向量数据库匹配商品名...")
            # ItemNameVector类里面方法查询向量数据库
            # match_item_name_filter返回两个列表
            # 第一个列表：匹配分数阈值 0.7  大于0.7数据 []
            # 第二个列表：小于0.7数据 大于0.6数据  []
            confirmed,options = (
                self._item_name_vector.match_item_name_filter(item_names))
            print(f"向量查询完成: confirmed={confirmed}, options={options}")
        else: # llm没有提取tem_name信息
            confirmed, options = [],[]
            print(f"item_names为空，跳过向量查询")

        # 5 更新state数据返回
        self.update_state(state,item_names,
                          confirmed,options,rewritten_query)

        state['history'] = chat_history
        print(f"========== ItemNameConfirmNode 完成 ==========\n")
        return state

    # 更新state数据
    def update_state(self,state,item_names,
                     confirmed,options,rewritten_query):
        if confirmed: # confirmed列表：阈值分数大于0.7
            state['rewritten_query'] = rewritten_query
            state['item_names'] = confirmed
            print(f"[UPDATE] 使用高置信度商品名: {confirmed}", flush=True)
        elif options: #阈值分数小于0.7 大于0.6  [1,2,3] => 1,2,3
            # ========== 优化：使用低置信度商品名继续检索（而不是结束流程）==========
            state['rewritten_query'] = rewritten_query
            state['item_names'] = options
            print(f"[UPDATE] 使用低置信度商品名: {options}", flush=True)
            # 注释掉原来的逻辑（会结束流程）
            # state['answer'] = f"请选择具体问题：{','.join(options)}"
        else: #商品名没有提取出来
            # ========== 优化：使用所有提取的商品名继续检索（而不是结束流程）==========
            if item_names:
                state['rewritten_query'] = rewritten_query
                state['item_names'] = item_names
                print(f"[UPDATE] 无匹配商品名，使用LLM提取的: {item_names}", flush=True)
            else:
                # ========== 终极方案：不设置 answer，继续检索（使用原问题）==========
                state['rewritten_query'] = state.get('original_query', rewritten_query)
                state['item_names'] = []
                print(f"[UPDATE] 完全无法识别，使用原问题进行检索", flush=True)
                # 注释掉原来的逻辑（会结束流程）
                # state['answer'] = "当前问题无法识别..."


if __name__ == "__main__":
    test_state: QueryGraphState = {
        "original_query": "我想知道H3C LA2608如何使用？"
    }
    print(f"输入: {json.dumps(test_state, ensure_ascii=False, indent=2)}\n")

    node_item_name_confirm = ItemNameConfirmNode()
    result=node_item_name_confirm.process(test_state)

    print(f"确认商品: {result.get('item_names')}")
    print(f"改写查询: {result.get('rewritten_query')}")
    if result.get("answer"):
        print(f"拦截回复: {result.get('answer')}")