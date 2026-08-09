"""重试装饰器工具

用于处理API调用时的速率限制错误（429）和其他可重试错误。
"""

import time
import functools
import logging
from typing import Callable, Type, Tuple, Any, Optional
from openai import RateLimitError

logger = logging.getLogger(__name__)


def retry_on_rate_limit(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (RateLimitError,)
) -> Callable:
    """重试装饰器，处理速率限制错误。

    Args:
        max_retries: 最大重试次数（默认3次）
        initial_delay: 初始等待时间（秒，默认1秒）
        backoff_factor: 退避因子，每次重试延迟时间乘以此因子（默认2.0）
        exceptions: 需要重试的异常类型（默认只重试RateLimitError）

    Returns:
        装饰后的函数

    Example:
        @retry_on_rate_limit(max_retries=5, initial_delay=2.0)
        def call_llm():
            return llm_client.invoke(messages)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        # 使用指数退避策略
                        logger.warning(
                            f"[尝试 {attempt + 1}/{max_retries + 1}] "
                            f"{func.__name__} 失败: {e}. "
                            f"等待 {delay:.1f} 秒后重试..."
                        )
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        logger.error(
                            f"[尝试 {attempt + 1}/{max_retries + 1}] "
                            f"{func.__name__} 在 {max_retries} 次重试后仍然失败"
                        )
                except Exception as e:
                    # 其他异常直接抛出，不重试
                    logger.error(f"{func.__name__} 遇到不可重试的异常: {e}")
                    raise

            # 所有重试都失败，抛出最后一个异常
            if last_exception:
                raise last_exception

        return wrapper
    return decorator


def retry_on_rate_limit_async(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (RateLimitError,)
) -> Callable:
    """异步重试装饰器，处理速率限制错误。

    Args:
        max_retries: 最大重试次数（默认3次）
        initial_delay: 初始等待时间（秒，默认1秒）
        backoff_factor: 退避因子，每次重试延迟时间乘以此因子（默认2.0）
        exceptions: 需要重试的异常类型（默认只重试RateLimitError）

    Returns:
        装饰后的异步函数

    Example:
        @retry_on_rate_limit_async(max_retries=5, initial_delay=2.0)
        async def call_llm_async():
            return await llm_client.ainvoke(messages)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            delay = initial_delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"[尝试 {attempt + 1}/{max_retries + 1}] "
                            f"{func.__name__} 失败: {e}. "
                            f"等待 {delay:.1f} 秒后重试..."
                        )
                        await asyncio.sleep(delay)
                        delay *= backoff_factor
                    else:
                        logger.error(
                            f"[尝试 {attempt + 1}/{max_retries + 1}] "
                            f"{func.__name__} 在 {max_retries} 次重试后仍然失败"
                        )
                except Exception as e:
                    # 其他异常直接抛出，不重试
                    logger.error(f"{func.__name__} 遇到不可重试的异常: {e}")
                    raise

            # 所有重试都失败，抛出最后一个异常
            if last_exception:
                raise last_exception

        return wrapper
    return decorator


if __name__ == "__main__":
    # 测试同步重试
    @retry_on_rate_limit(max_retries=3, initial_delay=0.5)
    def test_sync():
        import random
        if random.random() < 0.7:  # 70%概率失败
            from openai import RateLimitError
            raise RateLimitError("Test rate limit")
        return "成功"

    print("测试同步重试装饰器:")
    result = test_sync()
    print(f"结果: {result}")
