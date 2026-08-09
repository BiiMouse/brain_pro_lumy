"""性能分析工具

用于诊断系统性能瓶颈，记录各节点执行时间。
"""

import time
import functools
import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)


def timing_decorator(func: Callable) -> Callable:
    """装饰器：记录函数执行时间。

    用法：
        @timing_decorator
        def my_function():
            pass
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        elapsed_time = end_time - start_time

        # 记录执行时间
        func_name = func.__name__
        if elapsed_time >= 60:
            logger.info(f"⏱️  {func_name} 耗时: {elapsed_time/60:.2f}分钟 ({elapsed_time:.2f}秒)")
        elif elapsed_time >= 1:
            logger.info(f"⏱️  {func_name} 耗时: {elapsed_time:.2f}秒")
        else:
            logger.debug(f"⏱️  {func_name} 耗时: {elapsed_time*1000:.2f}毫秒")

        return result
    return wrapper


class PerformanceTimer:
    """上下文管理器：记录代码块执行时间。

    用法：
        with PerformanceTimer("向量检索"):
            # 执行向量检索
            results = search()
    """

    def __init__(self, operation_name: str):
        self.operation_name = operation_name
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        logger.info(f"🚀 开始: {self.operation_name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed_time = time.time() - self.start_time

        if elapsed_time >= 60:
            logger.info(
                f"✅ 完成: {self.operation_name} - "
                f"耗时: {elapsed_time/60:.2f}分钟 ({elapsed_time:.2f}秒)"
            )
        elif elapsed_time >= 1:
            logger.info(f"✅ 完成: {self.operation_name} - 耗时: {elapsed_time:.2f}秒")
        else:
            logger.info(
                f"✅ 完成: {self.operation_name} - "
                f"耗时: {elapsed_time*1000:.2f}毫秒"
            )

        # 性能警告
        if elapsed_time > 300:  # 5分钟
            logger.warning(
                f"⚠️  性能警告: {self.operation_name} 耗时过长 "
                f"({elapsed_time/60:.2f}分钟)，需要优化！"
            )


if __name__ == "__main__":
    # 测试
    @timing_decorator
    def test_function():
        time.sleep(1.5)
        return "完成"

    result = test_function()

    with PerformanceTimer("测试操作"):
        time.sleep(0.5)
        print("执行测试操作")
