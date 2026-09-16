"""查询流程节点基类

定义统一的节点接口规范，提供通用功能。
"""

from abc import ABC, abstractmethod
from typing import TypeVar, Optional
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from knowledge.processor.query_process.config import QueryConfig, get_config
from knowledge.processor.query_process.exceptions import QueryProcessError

T = TypeVar("T")  # 泛型状态类型


class BaseNode(ABC):
    """查询流程节点基类。

    所有节点类都应继承此基类，实现 process 方法。
    基类提供统一的日志、任务追踪和错误处理。

    Attributes:
        name: 节点名称，子类应覆盖。
        config: 配置对象。
        logger: 日志记录器。

    Example:
        >>> class MyNode(BaseNode):
        ...     name = "my_node"
        ...
        ...     def process(self, state):
        ...         # 实现具体逻辑
        ...         return state
        ...
        >>> # 作为 LangGraph 节点使用
        >>> node = MyNode()
        >>> workflow.add_node("my_node", node)
    """

    name: str = "base_node"

    def __init__(self, config: Optional[QueryConfig] = None):
        """初始化节点。

        Args:
            config: 配置对象，默认使用全局配置。
        """
        self.config = config or get_config()
        self.logger = logging.getLogger(f"query.{self.name}")

    def __call__(self, state: T) -> T:
        """节点执行入口。

        LangGraph 调用节点时会调用此方法。
        提供统一的日志输出、计时、任务追踪和异常处理。

        Args:
            state: 图状态字典。

        Returns:
            更新后的状态字典。

        Raises:
            QueryProcessError: 节点执行失败时抛出。
        """
        # 先记录每一步的开始时间（perf_counter 计耗时，datetime 记可读时间点）
        start_time = time.perf_counter()
        start_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        display = self.get_node_display_name()
        try:
            self.logger.info(
                f"--- [{display}] {self.name} 开始 | 开始时间: {start_at} ---")

            # ========== 性能优化：推送SSE进度（实时反馈思考过程）==========
            # 1. 获取task_id和is_stream标志
            task_id = state.get("task_id")
            is_stream = state.get("is_stream", False)

            # 2. 如果是流式模式，推送节点开始事件
            if is_stream and task_id:
                try:
                    from knowledge.utils.sse_util import push_sse_event
                    from knowledge.front.utils.task_util import update_task_status  # 修正：正确路径
                    # 3. 更新任务状态为"正在执行当前节点"
                    update_task_status(task_id, f"processing_{self.name}")
                    # 4. 推送进度事件到前端（显示节点名称）
                    push_sse_event(task_id, "progress", {
                        "node": self.name,
                        "status": "processing",
                        "message": f"正在执行: {self.get_node_display_name()}"
                    })
                except Exception as sse_error:
                    # SSE推送失败不影响主流程
                    self.logger.warning(f"SSE进度推送失败（可忽略）: {sse_error}")

            result = self.process(state)

            # 5. 节点完成后，推送完成事件
            if is_stream and task_id:
                try:
                    from knowledge.utils.sse_util import push_sse_event
                    from knowledge.front.utils.task_util import update_task_status, TASK_STATUS_PROCESSING  # 修正：正确路径
                    update_task_status(task_id, TASK_STATUS_PROCESSING)
                    push_sse_event(task_id, "progress", {
                        "node": self.name,
                        "status": "completed",
                        "message": f"完成: {self.get_node_display_name()}"
                    })
                except Exception as sse_error:
                    # SSE推送失败不影响主流程
                    self.logger.warning(f"SSE进度推送失败（可忽略）: {sse_error}")

            elapsed = time.perf_counter() - start_time
            self.logger.info(
                f"--- [{display}] {self.name} 完成 | 耗时: {elapsed:.3f}s ---")

            return result
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            self.logger.error(
                f"[{display}] {self.name} 执行失败 | "
                f"已耗时: {elapsed:.3f}s | 错误: {e}",
                exc_info=True,
            )
            raise QueryProcessError(
                message=str(e),
                node_name=self.name,
                cause=e
            )

    @abstractmethod
    def process(self, state: T) -> T:
        """节点核心处理逻辑。

        子类必须实现此方法。

        Args:
            state: 图状态字典。

        Returns:
            更新后的状态字典。
        """
        pass

    def log_step(self, step_name: str, message: str = ""):
        """记录步骤日志。

        Args:
            step_name: 步骤名称。
            message: 附加信息。
        """
        log_msg = f"[{step_name}]"
        if message:
            log_msg += f" {message}"
        self.logger.info(log_msg)

    def get_node_display_name(self) -> str:
        """获取节点的中文显示名称（用于日志与前端进度展示）

        子类可以覆盖此方法以提供更友好的名称。

        Returns:
            节点显示名称，默认返回映射表的中文，无映射时返回节点名。
        """
        # 节点名称映射表（英文 -> 中文）
        name_map = {
            # brain 场景
            "item_name_confirm": "商品名称识别",
            "search_embedding": "向量召回",
            "search_embedding_hyde": "HyDE召回",
            "web_search_mcp": "网络搜索",
            # lumy 场景
            "intent_entity": "意图与关键字识别",
            "structured_lookup": "结构化检索(PG)",
            # 两场景公共
            "rrf": "RRF融合",
            "rerank": "精排",
            "answer_output": "答案生成",
        }
        return name_map.get(self.name, self.name)


def setup_logging(level: int = logging.INFO):
    """配置查询流程日志（控制台 + 项目根 logs/日志.log 文件）。

    每次运行的日志追加写入 日志.log，文件头部写入分隔行区分多次运行。
    幂等：重复调用不会叠加 handler。

    Args:
        level: 日志级别，默认 INFO。
    """
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'

    # 1. 控制台输出。
    #    force=True：import 链中的第三方库（如 pymilvus 的 dictConfig）或模块级
    #    logging.info() 会抢先对 root 挂 handler，此时 basicConfig 静默失效、
    #    root 级别停在 WARNING，所有 INFO 日志被过滤，日志.log 只会建成空文件。
    #    force 强制接管 root，保证配置一定生效。
    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt=date_format,
        force=True,
    )
    # 双保险：不依赖 basicConfig 是否生效，显式压级别
    logging.getLogger().setLevel(level)

    # 2. 文件输出：项目根 logs/日志.log（追加模式，保留每次运行日志）
    root = logging.getLogger()
    log_path = Path(__file__).resolve().parents[3] / "logs" / "日志.log"
    already = any(
        isinstance(h, logging.FileHandler)
        and getattr(h, "baseFilename", "") == str(log_path)
        for h in root.handlers
    )
    if not already:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(log_format, date_format))
        root.addHandler(file_handler)
        # 每次进程启动写入分隔行，便于在文件中区分多次运行
        logging.getLogger("query.run").info(
            "\n%s\n运行启动 | PID %s | 日志文件: %s\n%s",
            "=" * 60, os.getpid(), log_path, "=" * 60,
        )
