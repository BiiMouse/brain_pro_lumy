### Lumy 查询-步骤1 意图识别与实体提取节点

"""
替代 brain 模式的 item_name_confirm：六类意图 + 型号/参数/文档实体 + 查询改写。
识别失败安全降级为 param_query（走向量检索兜底）。
"""

import json
import re
from typing import Dict, Any

from langchain_core.messages import SystemMessage, HumanMessage

from knowledge.processor.query_process.base import BaseNode
from knowledge.processor.query_process.state import QueryGraphState
from knowledge.prompts.query.lumy_query_prompt import (
    INTENT_ENTITY_SYSTEM_PROMPT, INTENT_ENTITY_USER_TEMPLATE,
)
from knowledge.utils.llm_client_util import get_llm_client
from knowledge.utils.retry_util import retry_on_rate_limit

VALID_INTENTS = {"model_list", "model_detail", "rule_explain",
                 "param_query", "cross_compare", "no_answer"}


class IntentEntityNode(BaseNode):
    name = "intent_entity"

    def process(self, state: QueryGraphState) -> QueryGraphState:
        query = state.get("original_query", "")
        history = state.get("history") or []
        history_lines = []
        for msg in history[-6:]:
            history_lines.append(
                f"{msg.get('role', '')}: {msg.get('text', '')[:150]}")
        history_text = "\n".join(history_lines) if history_lines else "暂无"

        result = self.classify(query, history_text)

        state["intent"] = result.get("intent", "param_query")
        state["model_entities"] = result.get("models", [])
        state["param_entities"] = result.get("params", [])
        state["file_entities"] = result.get("files", [])
        state["rewritten_query"] = (result.get("rewritten_query")
                                    or query)
        print(f"[intent_entity] intent={state['intent']} "
              f"models={state['model_entities']} params={state['param_entities']}")
        return state

    def classify(self, query: str, history_text: str) -> Dict[str, Any]:
        llm = get_llm_client(response_format=True)
        messages = [
            SystemMessage(content=INTENT_ENTITY_SYSTEM_PROMPT),
            HumanMessage(content=INTENT_ENTITY_USER_TEMPLATE.format(
                history=history_text, query=query)),
        ]

        @retry_on_rate_limit(max_retries=2, initial_delay=1.0)
        def _invoke():
            return llm.invoke(messages)

        try:
            content = _invoke().content.strip()
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
            data = json.loads(content)
        except Exception as e:
            self.logger.warning(f"意图识别失败，降级 param_query: {e}")
            return {"intent": "param_query", "models": [], "params": [],
                    "files": [], "rewritten_query": query}

        if data.get("intent") not in VALID_INTENTS:
            data["intent"] = "param_query"
        for key in ("models", "params", "files"):
            if not isinstance(data.get(key), list):
                data[key] = []
        return data


if __name__ == "__main__":
    from knowledge.processor.query_process.base import setup_logging

    setup_logging()
    node = IntentEntityNode()
    for q in ["MAX20029B系列有哪些型号？",
              "MAX20029BATIA/V+的后缀/V+代表什么？",
              "LM358的供电电压范围是多少？",
              "MAX20029和LM317的封装有什么差异？",
              "TL431的价格是多少？"]:
        st = node({"original_query": q})
        print(f"  Q: {q}")
        print(f"  → intent={st['intent']} models={st['model_entities']} "
              f"params={st.get('param_entities')} rewritten={st['rewritten_query']}\n")
