from typing import List, Dict

from knowledge.front.utils.task_util import set_task_result
from knowledge.processor.query_process.base import BaseNode, T
from knowledge.processor.query_process.state import QueryGraphState
from knowledge.prompts.query.query_prompt import ANSWER_PROMPT
from knowledge.utils.llm_client_util import get_llm_client
from knowledge.processor.query_process.config import get_config
from knowledge.utils.mongo_history_util import save_chat_message
from knowledge.utils.sse_util import push_sse_event, SSEEvent
from knowledge.utils.retry_util import retry_on_rate_limit


# 答案生成节点
class AnswerOutputNode(BaseNode):
    name = "answer_output"  # ========== 修正：添加节点名称 ==========
    def process(self, state: QueryGraphState) -> QueryGraphState:
        # 1 判断是否有answer（有答案），直接返回
        if state.get("answer"):
            set_task_result(state["task_id"], "answer", state["answer"])

        # 2 如果没有answer，获取相关数据（reranker数据 + 历史会话 + item_name等）
        # 3 通过上面数据构建提示词
        else:
            # 3.0 资料充足性闸门：检索为空或最高相关性低于阈值 → 直接拒答，不调用 LLM
            refusal = self.check_context_sufficient(state)
            if refusal:
                state["answer"] = refusal
                set_task_result(state.get("task_id"), "answer", refusal)
            else:
                prompt = self.build_prompt(state)
                state["prompt"] = prompt

                # 4 提示词提交LLM，生成最终答案
                ## 答案生成流水 或者 非流式方式
                self.call_llm_generate_answer(state, prompt)

        # 5 写入历史记录（问题 + llm答案存储mongodb）
        self.write_history(state)

        # 6 SSE流式处理
        is_stream = state.get("is_stream")
        task_id = state.get("task_id")
        if is_stream:
            # sse发送结束数据
            push_sse_event(task_id, SSEEvent.FINAL,
                           {"answer": state.get("answer")})
        return state

    # 资料充足性判断：返回拒答文案（str）则拒答；返回 None 表示资料充足，继续走 LLM
    def check_context_sufficient(self, state: QueryGraphState):
        """
        基于 reranker 相关性分数判断检索资料是否足以作答。
        - 无召回：直接拒答
        - 最高分低于阈值：相关性不足，拒答并提示缺失方向
        覆盖能力 3.1.5（资料不足拒答）。阈值见 RAG_REFUSE_THRESHOLD。
        """
        docs = state.get("reranked_docs") or []
        threshold = get_config().rag_refuse_threshold

        if not docs:
            return (
                "资料不足，暂无法回答该问题。\n\n"
                "缺少的信息：知识库中未检索到与该问题相关的资料。\n"
                "建议：1) 描述更具体一些（如带上产品型号、故障现象）；"
                "2) 确认相关文档是否已导入知识库。"
            )

        top_score = docs[0].get("score") or 0.0
        if top_score < threshold:
            return (
                f"资料不足，暂无法可靠回答该问题（最高相关度 {top_score:.2f}，"
                f"低于阈值 {threshold}，为避免误导不作答）。\n\n"
                "缺少的信息：与该问题直接相关的制度/产品/操作说明。\n"
                "建议：1) 换用更准确的关键词或提供更多背景；"
                "2) 确认相关文档是否已导入知识库。"
            )

        return None

    # 构建提示词
    def build_prompt(self, state: QueryGraphState) -> str:
        # 获取用户问题 + item_name
        question = (state.get("rewritten_query", "")
                    or state.get("original_query", ""))
        item_names = state["item_names"]

        # 获取前一步返回答案列表 reranker融合答案列表
        reranked_docs = state.get("reranked_docs")
        reranked_str = self.format_reranker_docs(reranked_docs)

        # 获取历史会话记录
        history = state.get("history")
        history_str = self.format_history(history)

        # 构建提示词
        return ANSWER_PROMPT.format(
            context=reranked_str or "无参考答案",
            history=history_str if history_str else "暂无历史",
            item_names=item_names,
            question=question,
        )

    # reranker融合答案列表整理 返回str
    def format_reranker_docs(self,
                             reranked_docs: List[Dict]) -> str:
        # 上下文预算：总预算取自 config.max_context_chars（默认 12000），
        # 单条上限取自 config.rag_doc_max_chars（默认 2000）。
        # 历史问题：此处原硬编码 2500 总预算且无单条上限 → 一整节手册（如「电源线」~1100 字）
        # 排在 rerank top-1 时独占预算，把排在第 4 位、含答案的「设备」节挤出 LLM 可见窗口，
        # 导致 Q2(卡纸)/Q3(清洁) 答案虽被检索到却仍被误拒。
        config = get_config()
        total_budget = config.max_context_chars      # 总预算（原硬编码 2500）
        per_doc_cap = config.rag_doc_max_chars       # 单条上限，防大块独占

        # 定义列表，封装最终数据
        result = []
        used = 0
        # ========== 图片展示：收集所有图片URL ==========
        image_urls = []

        # 遍历列表reranked_docs
        for index, doc in enumerate(reranked_docs):
            content = doc.get("content", "")
            if not content:
                continue

            # 单条截断：超长 chunk 只取前 per_doc_cap 字符，避免一整节手册独占预算
            if len(content) > per_doc_cap:
                content = content[:per_doc_cap] + "\n…(该片段过长，已截断)"

            # 直接拼接字典格式
            meta = {
                "score": doc.get("score", 0),
                "url": doc.get("url", ""),
                "title": doc.get("title", ""),
            }

            data = f"[{index}]:{meta}\n{content}"

            if used + len(data) > total_budget:
                break

            result.append(data)
            used += len(data)

            # ========== 图片展示：提取图片URL ==========
            # 从文档中提取图片URL（支持多种格式）
            doc_images = self.extract_images_from_doc(doc)
            image_urls.extend(doc_images)

        # ========== 图片展示：将图片URL添加到结果中 ==========
        # 如果有图片，在上下文末尾添加图片引用
        if image_urls:
            # 去重并限制图片数量（最多5张，避免上下文过长）
            unique_images = list(dict.fromkeys(image_urls))[:5]
            if unique_images:
                result.append("\n【相关图片】\n" + "\n".join([f"[图片{i+1}]: {url}" for i, url in enumerate(unique_images)]))
                # 将图片URL保存到state中，供后续使用
                return self._add_images_to_state(result, unique_images)

        return "\n\n".join(result)

    def extract_images_from_doc(self, doc: Dict) -> List[str]:
        """从文档中提取图片URL

        Args:
            doc: 文档字典，可能包含 content、url、images等字段

        Returns:
            图片URL列表
        """
        images = []

        # 1. 直接从images字段获取
        if "images" in doc and isinstance(doc["images"], list):
            images.extend(doc["images"])

        # 2. 从content中提取图片URL（Markdown格式：![alt](url)）
        import re
        content = doc.get("content", "")
        img_pattern = r'!\[.*?\]\((.*?)\)'
        found_images = re.findall(img_pattern, content)
        images.extend(found_images)

        # 3. 从content中提取HTML <img>标签
        img_html_pattern = r'<img[^>]+src=["\']([^"\']+)["\']'
        found_html_images = re.findall(img_html_pattern, content)
        images.extend(found_html_images)

        return [img for img in images if img and img.startswith(('http://', 'https://'))]

    def _add_images_to_state(self, result: List[str], images: List[str]) -> str:
        """将图片信息添加到上下文并返回

        Args:
            result: 上下文列表
            images: 图片URL列表

        Returns:
            包含图片信息的上下文字符串
        """
        # 将图片信息添加到上下文中
        context_with_images = "\n\n".join(result)
        return context_with_images

    # 历史记录整理 返回str
    def format_history(self, history: List[Dict]) -> str:
        result = []
        used = 0
        for message in history:
            text = message.get("text", "")
            role = message.get("role", "")

            # user:1111
            data = f"{role}:{text}"

            if used + len(data) > 2500:
                break

            result.append(data)
            used += len(data)
        return "\n".join(result)

    # 4 提示词提交LLM，生成最终答案
    # llm生成答案
    def call_llm_generate_answer(self, state, prompt):
        # 获取llm连接对象
        llm_client = get_llm_client()
        task_id = state.get("task_id")
        # 流式 非流式
        if state.get("is_stream"):
            state["answer"] = self.stream_output(llm_client, prompt, task_id)
        else:
            state["answer"] = self.invoke_output(prompt, llm_client)
            set_task_result(task_id, "answer", state["answer"])

        # ========== 图片展示：在答案末尾添加图片 ==========
        # 如果reranked_docs中有图片，在答案末尾添加图片展示
        self.append_images_to_answer(state)

    # 流式输出操作方法
    def stream_output(self, llm_client, prompt, task_id):
        final_answer = ""
        for chunk in llm_client.stream(prompt):
            delta_text = getattr(chunk, "content", "")
            if delta_text:
                final_answer += delta_text
                push_sse_event(task_id,
                               SSEEvent.DELTA, {"delta": delta_text})
        return final_answer

    # 非流式输出（添加重试机制）
    def invoke_output(self, prompt, llm_client):
        @retry_on_rate_limit(max_retries=5, initial_delay=2.0)
        def _invoke_with_retry():
            return llm_client.invoke(prompt)

        res = _invoke_with_retry()
        return res.content

    # 写入历史会话
    def write_history(self, state: QueryGraphState):
        session_id = state["session_id"]
        rewritten_query = (state.get("rewritten_query", "")
                           or state.get("original_query", ""))
        item_names = state.get("item_names") or []

        try:  # 1. 写用户问题
            save_chat_message(
                session_id=session_id,
                role="user",
                text=state["original_query"],
                rewritten_query=rewritten_query,
                item_names=item_names,
            )

            # 2. AI回复
            if state.get("answer"):
                save_chat_message(
                    session_id=session_id,
                    role="assistant",
                    text=state["answer"],  # 模型的输出
                    rewritten_query=rewritten_query,
                    item_names=item_names,
                )
        except Exception as e:
            self.logger.warning(f"写入历史记录失败: {e}")

    def append_images_to_answer(self, state: QueryGraphState):
        """在答案末尾添加相关图片

        从reranked_docs中提取图片URL并添加到答案末尾
        """
        # 1. 获取reranked_docs
        reranked_docs = state.get("reranked_docs", [])
        if not reranked_docs:
            return

        # 2. 收集所有图片URL
        image_urls = []
        for doc in reranked_docs:
            doc_images = self.extract_images_from_doc(doc)
            image_urls.extend(doc_images)

        # 3. 去重并限制数量（最多5张）
        unique_images = list(dict.fromkeys(image_urls))[:5]

        # 4. 如果有图片，添加到答案末尾
        if unique_images and state.get("answer"):
            # 构建图片展示HTML
            images_html = "\n\n### 相关图片\n\n"
            for i, url in enumerate(unique_images):
                images_html += f'<div style="margin: 10px 0;">\n'
                images_html += f'  <img src="{url}" alt="相关图片{i+1}" style="max-width: 600px; border-radius: 8px;"/>\n'
                images_html += f'  <p><small>图片来源: {url}</small></p>\n'
                images_html += f'</div>\n'

            # 将图片添加到答案末尾
            state["answer"] = state["answer"] + images_html
            self.logger.info(f"已添加 {len(unique_images)} 张相关图片到答案末尾")


if __name__ == "__main__":
    # 构造模拟状态
    mock_state = {
        "task_id": "001",
        "session_id": "test_session_001",
        "is_stream": True,  # 非流式测试
        "original_query": "万用表怎么测电压？",
        "rewritten_query": "RS-12数字万用表如何测量电压？",
        "item_names": ["RS-12数字万用表"],
        # "answer": "当前问题无法识别",
        "reranked_docs": [
            {
                "text": "数字万用表测量电压步骤：1. 将旋钮转到V档位；2. 黑表笔插COM孔，红表笔插V孔；3. 将表笔并联到被测点两端。",
                "source": "local",
                "chunk_id": "chunk_001",
                "title": "万用表使用手册",
                "score": 0.9234
            },
            {
                "text": "测量直流电压时需注意正负极性，红表笔接正极，黑表笔接负极。",
                "source": "web",
                "url": "https://example.com/guide",
                "title": "电压测量指南",
                "score": 0.8756
            }
        ],
        "history": [
            {"user": "万用表是什么？", "assistant": "万用表是一种多功能电子测量仪器..."}
        ]
    }

    # 执行答案生成
    output = AnswerOutputNode()
    result = output.process(mock_state)
    # 打印结果
    print("\n【生成结果】:")
    print("-" * 60)
    print(result.get("answer"))
    print("-" * 60)
