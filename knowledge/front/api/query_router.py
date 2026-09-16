"""查询路由"""

import logging
import os
import time
from datetime import datetime
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, Depends
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from knowledge.front.schema.query_schema import QueryRequest, StreamSubmitResponse, QueryResponse
from knowledge.front.service.query_service import QueryService
from knowledge.front.utils.deps import get_query_service
from knowledge.front.utils.paths import get_front_page_dir
from knowledge.utils.sse_util import sse_generator
from knowledge.processor.query_process.base import setup_logging

logger = logging.getLogger(__name__)

# 统一日志配置：控制台 + 项目根 logs/日志.log（幂等，重复调用不叠加 handler）
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):


    """应用生命周期管理（替代已弃用的 on_event）

    功能：
    - 启动时预热BGE-M3和BGE-Reranker模型
    - 预期效果：首次查询快10秒
    """
    # ========== 性能优化：模型预热（已实现）==========
    # 启动时执行（暂时注释掉，排查崩溃问题）
    # from knowledge.utils.bgem3_client_util import warmup_models
    # warmup_models()

    yield

    # 关闭时执行（如果需要）
    # 可以在这里添加资源清理代码


def create_app() -> FastAPI:
    app = FastAPI(
        title="Query Service",
        description="知识库查询服务",
        lifespan=lifespan  # 使用 lifespan 替代 on_event
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )
    front_page_dir = get_front_page_dir()
    if front_page_dir and os.path.exists(front_page_dir):
        app.mount("/front", StaticFiles(directory=front_page_dir))
    register_routes(app)
    return app


def register_routes(app: FastAPI):

    @app.get("/chat.html")
    async def chat_page():
        return FileResponse(os.path.join(get_front_page_dir(), "chat.html"))

    @app.post("/query")
    async def query(
        request: QueryRequest,
        background_tasks: BackgroundTasks,
        service: QueryService = Depends(get_query_service),
    ):
        session_id = request.session_id or service.generate_session_id()
        task_id = service.generate_task_id()
        start_time = time.perf_counter()
        logger.info(
            f"[接收查询] session_id={session_id} task_id={task_id} "
            f"is_stream={request.is_stream} | "
            f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} | "
            f"查询: {request.query}"
        )
        service.submit_query(task_id, request.is_stream)

        if request.is_stream:
            background_tasks.add_task(
                service.run_query_graph, task_id, session_id, request.query, True
            )
            logger.info(f"[流式任务已提交] task_id={task_id}（后台执行，结果经 SSE 推送）")
            return StreamSubmitResponse(
                message="Query submitted", session_id=session_id, task_id=task_id
            )

        service.run_query_graph(task_id, session_id, request.query, False)
        answer = service.get_answer(task_id)
        logger.info(
            f"[返回答案] task_id={task_id} | "
            f"接口总耗时: {time.perf_counter() - start_time:.3f}s | "
            f"答案长度: {len(answer)}"
        )
        return QueryResponse(message="处理完成", session_id=session_id, answer=answer)

    @app.get("/stream/{task_id}")
    async def stream(task_id: str, request: Request):
        return StreamingResponse(
            sse_generator(task_id, request), media_type="text/event-stream",
        )

    @app.get("/history/{session_id}")
    async def get_history(
        session_id: str, limit: int = 50,
        service: QueryService = Depends(get_query_service),
    ):
        try:
            items = service.get_history(session_id, limit)
            return {"session_id": session_id, "items": items}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"history error: {e}")

    @app.delete("/history/{session_id}")
    async def clear_chat_history(
        session_id: str,
        service: QueryService = Depends(get_query_service),
    ):
        count = service.clear_history(session_id)
        return {"message": "History cleared", "deleted_count": count}


if __name__ == "__main__":
    uvicorn.run(app=create_app(), host="0.0.0.0", port=8001)