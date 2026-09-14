### Lumy 查询-答案生成节点（证据引用契约 + 双源拒答闸门）

"""
与 brain answer_node 的差别：
  - 上下文 = 结构化检索结果（型号库，带页码） + 向量检索片段（带文件/页码）
  - prompt 内置证据契约：每条结论标 [文件 第N页] / [型号库]，
    参数保留单位/测试条件/typ-max，跨文档分列来源，冲突明示
  - 拒答闸门：结构化与向量双源都为空/低分才拒答（结构化命中即视为证据充分）
"""

import json
from typing import Dict, List

from knowledge.front.utils.task_util import set_task_result
from knowledge.processor.query_process.base import BaseNode
from knowledge.processor.query_process.config import get_config
from knowledge.processor.query_process.state import QueryGraphState
from knowledge.prompts.query.lumy_query_prompt import LUMY_ANSWER_PROMPT
from knowledge.utils.llm_client_util import get_llm_client_long
from knowledge.utils.mongo_history_util import save_chat_message
from knowledge.utils.retry_util import retry_on_rate_limit
from knowledge.utils.sse_util import push_sse_event, SSEEvent


class AnswerLumyNode(BaseNode):
    name = "answer_output"

    def process(self, state: QueryGraphState) -> QueryGraphState:
        task_id = state.get("task_id")
        # 1 拒答闸门（双源）
        refusal = self.check_evidence(state)
        if refusal:
            state["answer"] = refusal
            set_task_result(task_id, "answer", refusal)
        else:
            prompt = self.build_prompt(state)
            state["prompt"] = prompt
            if state.get("is_stream"):
                state["answer"] = self.stream_answer(prompt, task_id)
            else:
                state["answer"] = self.invoke_answer(prompt)
            set_task_result(task_id, "answer", state["answer"])

        # 2 写历史（可追溯）
        self.write_history(state)

        # 3 SSE 结束事件（流式模式）
        if state.get("is_stream"):
            push_sse_event(task_id, SSEEvent.FINAL,
                           {"answer": state.get("answer")})
        return state

    # ---------- 拒答闸门 ----------
    def check_evidence(self, state: QueryGraphState):
        """结构化命中 → 充分；否则看向量 top 分是否过阈值"""
        structured = state.get("structured_docs") or []
        if structured:
            return None
        docs = state.get("reranked_docs") or []
        threshold = get_config().rag_refuse_threshold
        if not docs:
            return ("知识库中未检索到与该问题相关的资料。\n\n"
                    "缺少的信息：与该问题直接相关的型号或参数资料。\n"
                    "建议：1) 确认型号拼写（含后缀）；2) 确认相关规格书是否已导入。")
        top_score = docs[0].get("score") or 0.0
        if top_score < threshold:
            return (f"知识库中未找到足够相关的资料（最高相关度 {top_score:.2f}，"
                    f"低于阈值 {threshold}，为避免误导不作答）。\n\n"
                    "建议：1) 换用更准确的关键词或提供型号全称；"
                    "2) 确认相关规格书是否已导入。")
        return None

    # ---------- 上下文构建 ----------
    def format_structured(self, structured: List[Dict]) -> str:
        lines = []
        for i, d in enumerate(structured[:20]):
            payload = json.dumps(d.get("payload") or {}, ensure_ascii=False)
            src = f"{d.get('file') or ''}"
            page = d.get("page")
            cite = f"第{page}页" if page else ""
            lines.append(f"[{i}] ({d['type']}) {src} {cite} {payload[:600]}")
        return "\n".join(lines) if lines else "无"

    def format_docs(self, docs: List[Dict]) -> str:
        config = get_config()
        total_budget = config.max_context_chars
        per_doc_cap = config.rag_doc_max_chars
        lines, used = [], 0
        for i, doc in enumerate(docs):
            content = doc.get("content", "")
            if not content:
                continue
            if len(content) > per_doc_cap:
                content = content[:per_doc_cap] + "\n…(截断)"
            file_title = doc.get("file_title") or doc.get("title") or ""
            page = doc.get("page")
            cite = f"{file_title} 第{page}页" if (file_title and page != "") else file_title
            block = f"[{i}] 来源:{cite} 相关度{doc.get('score', 0):.2f}\n{content}"
            if used + len(block) > total_budget:
                break
            lines.append(block)
            used += len(block)
        return "\n\n".join(lines) if lines else "无"

    def build_prompt(self, state: QueryGraphState) -> str:
        question = (state.get("rewritten_query") or state.get("original_query"))
        history = state.get("history") or []
        history_str = "\n".join(
            f"{m.get('role','')}: {m.get('text','')[:150]}" for m in history[-6:]
        ) or "暂无"
        return LUMY_ANSWER_PROMPT.format(
            structured_context=self.format_structured(
                state.get("structured_docs") or []),
            doc_context=self.format_docs(state.get("reranked_docs") or []),
            history=history_str,
            question=question,
        )

    # ---------- 生成 ----------
    def invoke_answer(self, prompt: str) -> str:
        # 长超时客户端：长清单类答案（如 TL432 的 20 个 PPN 罗列）会超过 30s；
        # 答案是纯文本，必须关闭 JSON 模式
        llm = get_llm_client_long(temperature=0.1, response_format=False)

        @retry_on_rate_limit(max_retries=3, initial_delay=1.0)
        def _invoke():
            return llm.invoke(prompt)

        return _invoke().content

    def stream_answer(self, prompt: str, task_id) -> str:
        """SSE 流式输出（前端 chat.html 逐字显示）"""
        llm = get_llm_client_long(temperature=0.1, response_format=False)
        final_answer = ""
        try:
            for chunk in llm.stream(prompt):
                delta = getattr(chunk, "content", "")
                if delta:
                    final_answer += delta
                    push_sse_event(task_id, SSEEvent.DELTA,
                                   {"delta": delta})
        except Exception as e:
            # 流式中断：降级为整段生成，保证有答案
            self.logger.warning(f"流式输出中断，降级非流式: {e}")
            final_answer = self.invoke_answer(prompt)
        return final_answer

    def write_history(self, state: QueryGraphState):
        try:
            save_chat_message(
                session_id=state.get("session_id") or "lumy_cli",
                role="user",
                text=state.get("original_query", ""),
                rewritten_query=state.get("rewritten_query", ""),
                item_names=state.get("model_entities") or [],
            )
            if state.get("answer"):
                save_chat_message(
                    session_id=state.get("session_id") or "lumy_cli",
                    role="assistant",
                    text=state["answer"],
                    rewritten_query=state.get("rewritten_query", ""),
                    item_names=state.get("model_entities") or [],
                )
        except Exception as e:
            self.logger.warning(f"写入历史记录失败: {e}")


if __name__ == "__main__":
    from knowledge.processor.query_process.base import setup_logging

    setup_logging()
    node = AnswerLumyNode()
    st = {
        "original_query": "MAX20029ATIA/V+ 的后缀 /V+ 代表什么？",
        "rewritten_query": "MAX20029ATIA/V+ 的后缀 /V+ 代表什么？",
        "intent": "rule_explain",
        "model_entities": ["MAX20029ATIA/V+"],
        "structured_docs": [{
            "type": "naming_rule", "file": "max20029-max20029d.pdf", "page": 17,
            "payload": {
                "family": "MAX20029", "pattern": "MAX20029ATI_/V+",
                "positions": [
                    {"segment": "A", "meaning": "28 TQFN-EP 封装", "kind": "ordering"},
                    {"segment": "TI", "meaning": "-40°C to +125°C 汽车级", "kind": "ordering"},
                    {"segment": "_", "meaning": "Selector Guide 配置字母", "kind": "functional"},
                    {"segment": "/V+", "meaning": "AEC-Q100 认证 + 无铅/RoHS", "kind": "ordering"},
                ],
            },
        }],
        "reranked_docs": [],
        "history": [],
    }
    print(node.process(st)["answer"])
