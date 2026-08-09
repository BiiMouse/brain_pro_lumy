import asyncio
import json
from typing import Tuple, List, Dict, Any

from agents.mcp import MCPServerStreamableHttp

from knowledge.processor.query_process.base import BaseNode
from knowledge.processor.query_process.state import QueryGraphState

# 网络搜索节点 mcp方式
class WebSearchNode(BaseNode):
    name = "web_search_mcp"  # ========== 修正：添加节点名称 ==========
    # 外层同步process
    def process(self, state: QueryGraphState) -> QueryGraphState:
        return asyncio.run(self._async_process(state))

    # 内部真实异步逻辑
    async def _async_process(self,
                             state: QueryGraphState) -> QueryGraphState:
        print(f"\n========== WebSearchNode 开始 ==========")
        try:
            # 1 参数校验
            print(f"开始参数校验...")
            rewritten_query = self.validate_param(state)
            print(f"参数校验完成，query={rewritten_query}")

            # 2 调用mcp工具得到工具返回结果
            print(f"开始调用MCP Web搜索...")
            mcp_result = await self.execute_web_search_mcp(rewritten_query)
            if not mcp_result:
                self.logger.warning("Web搜索未返回结果")
                print(f"Web搜索未返回结果")
                print(f"========== WebSearchNode 完成（空结果） ==========\n")
                return state

            print(f"Web搜索完成，返回{len(mcp_result)}条结果")
            print(f"========== WebSearchNode 完成 ==========\n")
            return {"web_search_docs":mcp_result}
        except Exception as e:
            # Web搜索失败不影响整体流程，只记录日志
            print(f"Web搜索执行失败: {e}")
            self.logger.warning(f"Web搜索执行失败，跳过此步骤: {e}")
            print(f"========== WebSearchNode 完成（失败） ==========\n")
            return state

    # 调用mcp工具得到工具返回结果
    async def execute_web_search_mcp(self,
                 rewritten_query:str)->List[Dict[str,Any]]:
        # 建立和mcp服务器连接
        print(f"建立MCP连接...")
        mcp_client = None

        # 建立连接需要header信息
        headers = {
            "Authorization": f"Bearer {self.config.mcp_api_key}",
            "Content-Type": "application/json"
        }

        try:
            # 创建连接对象
            print(f"创建MCP客户端...")
            mcp_client = MCPServerStreamableHttp(
                name="通用搜索",
                params={
                    "url": self.config.mcp_dashscope_base_url,
                    "headers": headers,
                },
                cache_tools_list=True,
            )

            # 建立连接
            print(f"连接到MCP服务器...")
            await mcp_client.connect()
            print(f"MCP连接成功")

            # 调用mcp服务器工具
            print(f"调用MCP工具: bailian_web_search")
            execute_tool_result = await mcp_client.call_tool(
                # mcp服务器工具名称
                tool_name="bailian_web_search",
                arguments={
                    "query": rewritten_query,
                    "count": 3
                }
            )
            print(f"MCP工具调用成功")
            print("=="*50)
            print(execute_tool_result)
            print("==" * 50)
            if not execute_tool_result:
                print(f"MCP工具返回空结果")
                return []

            # 反序列化 我i什么要做反序列化？？？？？
            print(f"解析MCP结果...")
            content_text:str = execute_tool_result.content[0].text

            data:Dict[str,Any] = json.loads(content_text)

            # 列表
            pages = data.get('pages')
            # 从pages列表获取具体数据，snippet答案 title标题问题  url网页地址
            # 列表 封装最终数据
            search_result = []
            for page in pages:
                snippet = page.get('snippet',"")
                title = page.get('title',"")
                url = page.get('url',"")
                search_result.append({
                    "snippet": snippet,
                    "title": title,
                    "url": url
                })
            return search_result
        except Exception as e:
            # 记录错误日志，但不抛出异常
            self.logger.warning(f"MCP调用失败: {e}")
            return []
        finally:
            if mcp_client:
                try:
                    await mcp_client.cleanup()
                except Exception as cleanup_error:
                    self.logger.warning(f"MCP清理失败: {cleanup_error}")

    # 参数校验
    def validate_param(self,
                       state: QueryGraphState):
        rewritten_query = state.get('rewritten_query')
        if not rewritten_query:
            raise ValueError("rewritten_query is empty")
        return rewritten_query

if __name__ == "__main__":
    state = {
        "rewritten_query": "关于H3C LA2608，如何使用？",
        "item_names": ["H3C LA2608 室内无线网关"],
    }

    web_search = WebSearchNode()
    result = web_search.process(state)
    print(result)