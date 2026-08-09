import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

def get_llm_client(model_name:str=None,
                   temperature: float = 0.0,
                   response_format: bool = False):
    try:
        model_name = os.getenv("ITEM_MODEL")
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_API_BASE")

        model_kwargs = {}
        if response_format:
            model_kwargs['response_format'] = {"type": "json_object"}

        # ========== 性能优化：添加超时配置（避免无限等待）==========
        # timeout: 单个请求的超时时间（秒）
        # request_timeout: 请求超时（连接+读取）
        client = ChatOpenAI(
            model= model_name,
            api_key=api_key,
            base_url=base_url,
            # 下面参数可选的
            temperature=temperature,
            extra_body={"enable_thinking": False},
            model_kwargs=model_kwargs,
            timeout=30.0,  # 30秒超时（避免LLM响应慢导致卡住）
            request_timeout=30.0  # 同上，兼容不同版本
        )
        return client
    except Exception as e:
        raise e

