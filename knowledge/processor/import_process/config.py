"""
集中管理所有配置项，支持环境变量覆盖
  - 文档处理配置（切片长度、重叠句数等）
  - LLM 配置（OpenAI API、模型选择）
  - 存储配置（Milvus、Neo4j、MinIO）
  - 速率限制配置
  - 为什么这么做：使用 dataclass 和环境变量，实现配置的集中管理和灵活性，便于部署和环境切换
"""
from dataclasses import dataclass, field
from typing import Set, Optional
import os
from dotenv import load_dotenv

load_dotenv()

"""
@dataclass 数据类，自动生成__init__, __repr__, __eq__ 等方法
没有这个标签需要多写很多代码：
    def __init__(self, max_content_length: int = 2000,
               image_extensions: Set[str] = None):
      self.max_content_length = max_content_length
      self.image_extensions = image_extensions or {".jpg", ".png"}

    def __repr__(self):
      return f"ImportConfig(max_content_length={self.max_content_length}, ...)"

    def __eq__(self, other):
      if not isinstance(other, ImportConfig):
          return False
      return (self.max_content_length == other.max_content_length and
              self.image_extensions == other.image_extensions)
    # 还要手写 __hash__ 等等...
"""
@dataclass
class ImportConfig:
    """导入流程配置"""

    # ==================== 文档处理配置 ====================
    max_content_length: int = 2000  # 切片最大长度
    min_content_length: int = 500   # 合并短内容的最小长度
    overlap_sentences: int = 1      # 句子级切分时的重叠句数
    item_name_chunk_k: int = 3      # 商品名识别时使用的切片数量

    image_extensions: Set[str] = field(
        default_factory=lambda: {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
    )

    # ==================== LLM 配置 ====================

    """
    field: 用于自定义字段的特殊行为。
    为什么要用field(default_factory=...)
    ❌ 错误：可变默认值陷阱
      类属性定义如下，所有实例共享同一个列表
      extensions: Set[str] = {".jpg", ".png"}
      类实例化2个
      c1 = Config()
      c2 = Config()
      c1.extensions.add(".gif")
      print(c2.extensions)  # {".jpg", ".png", ".gif"} ← c2被意外修改了！
    ✅ 正确：使用 default_factory，每次创建实例时，才调用一次工厂函数 
    每次都是新的不会共享，不会污染，不会累积
      类属性定义，每次创建新实例时都会调用 lambda，生成新的集合
      extensions: Set[str] = field(default_factory=lambda: {".jpg", ".png"})
      类实例化
      c1 = Config()
      c2 = Config()
      c1.extensions.add(".gif")
      print(c2.extensions)  # {".jpg", ".png"} ← 互不影响！
    Python 里，凡是默认值需要动态计算、或属于可变类型，一律用 default_factory，绝对不要用 default=xxx
    """
    openai_api_base: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_BASE", "")
    )
    """
    虽然 str 是不可变类型，不会像 list 那样出问题，
    但这种写法依然是最推荐的写法，原因：
    默认值不是固定写死的，而是每次创建实例都会重新获取环境变量
    不会因为类加载时就计算好默认值，导致后续环境变量变化不生效
    """
    openai_api_key: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", "")
    )
    item_model: str = field(
        default_factory=lambda: os.getenv("ITEM_MODEL", "")
    )
    default_model: str = field(
        default_factory=lambda: os.getenv("MODEL", "")
    )
    vl_model: str = field(
        default_factory=lambda: os.getenv("VL_MODEL", "")
    )
    vl_model_api_base: str = field(
        default_factory=lambda: os.getenv("VL_MODEL_API_BASE", "")
    )
    vl_model_api_key: str = field(
        default_factory=lambda: os.getenv("VL_MODEL_API_KEY", "")
    )

    # ==================== Milvus 配置 ====================
    milvus_url: str = field(
        default_factory=lambda: os.getenv("MILVUS_URL", "")
    )
    chunks_collection: str = field(
        default_factory=lambda: os.getenv("CHUNKS_COLLECTION", "")
    )
    item_name_collection: str = field(
        default_factory=lambda: os.getenv("ITEM_NAME_COLLECTION", "")
    )
    entity_name_collection: str = field(
        default_factory=lambda: os.getenv("ENTITY_NAME_COLLECTION", "")
    )

    # ==================== Neo4j 配置 ====================
    neo4j_uri: str = field(
        default_factory=lambda: os.getenv("NEO4J_URI", "")
    )
    neo4j_username: str = field(
        default_factory=lambda: os.getenv("NEO4J_USERNAME", "")
    )
    neo4j_password: str = field(
        default_factory=lambda: os.getenv("NEO4J_PASSWORD", "")
    )
    neo4j_database: str = field(
        default_factory=lambda: os.getenv("NEO4J_DATABASE", "neo4j")
    )

    # ==================== MinIO 配置 ====================
    minio_endpoint: str = field(
        default_factory=lambda: os.getenv("MINIO_ENDPOINT", "")
    )
    minio_access_key: str = field(
        default_factory=lambda: os.getenv("MINIO_ACCESS_KEY", "")
    )
    minio_secret_key: str = field(
        default_factory=lambda: os.getenv("MINIO_SECRET_KEY", "")
    )
    minio_bucket: str = field(
        default_factory=lambda: os.getenv("MINIO_BUCKET_NAME", "")
    )
    minio_secure: bool = False

    # ==================== 向量配置 ====================
    embedding_dim: int = field(
        default_factory=lambda: int(os.getenv("EMBEDDING_DIM", "1024"))
    )
    embedding_batch_size: int = 5

    # ==================== 速率限制 ====================
    requests_per_minute: int = 12  # 图片总结 API 速率限制

    """
    装饰器@classmethod
    让方法属于类，而不是实例，第一个参数是 cls（类本身），不是 self（实例）
    1. 定义对比
    ----------------------------------------------------------------------------
    方法类型       装饰器           第一个参数      含义
    ---------------------------------------------------------------------------
    实例方法       无               self        代表调用的实例对象
    类方法法       @classmethod     cls         代表类本身
    静态方法       @staticmethod    无          无默认参数
    ----------------------------------------------------------------------------
    
    2. 调用方式对比
    ----------------------------------------------------------------------------
    方法类型      类名调用(类.方法)     实例调用(对象.方法)       说明
    ----------------------------------------------------------------------------
    实例方法      ❌ 报错             ✅ 正常                 只能用实例调用
    类方法       ✅ 正常             ✅ 正常                 类/实例均可调用
    静态方法      ✅ 正常             ✅ 正常                 类/实例均可调用
    ----------------------------------------------------------------------------
    
    3. 核心用途
    实例方法：访问/修改实例属性，处理对象自身数据
    类方法：  访问/修改类属性，常用作工厂方法
    静态方法：与类/实例无关，仅封装独立逻辑
    ----------------------------------------------------------------------------
    案例：
    # 实例方法
    def instance_method(self):
        return f"实例方法，self={self}"

    # 类方法
    @classmethod
    def class_method(cls):
        return f"类方法，cls={cls}"

    # 静态方法
    @staticmethod
    def static_method():
        return f"静态方法，无默认参数"
    """
    @classmethod
    def from_env(cls) -> "ImportConfig":
        """从环境变量加载配置"""
        return cls()


# ==================== 全局单例 ====================
_config: Optional[ImportConfig] = None


def get_config() -> ImportConfig:
    """获取配置单例"""
    global _config
    if _config is None:
        """
          --直接用类名调用（推荐）---
          为什么需要 from_env？工厂模式：提供多种创建对象的方式
          @dataclass
          class ImportConfig:
              openai_api_key: str = ""
              neo4j_uri: str = ""
              
              # 方式1：默认构造函数
              def __init__(self, openai_api_key: str = "", neo4j_uri: str = ""):
                  self.openai_api_key = openai_api_key
                  self.neo4j_uri = neo4j_uri
    
              # 方式2：从环境变量加载
              @classmethod
              def from_env(cls) -> "ImportConfig":
                  # 自动读取 .env 文件
                  return cls(
                      openai_api_key=os.getenv("OPENAI_API_KEY", ""),
                      neo4j_uri=os.getenv("NEO4J_URI", "")
                  )

              # 方式3：从字典加载
              @classmethod
              def from_dict(cls, data: dict) -> "ImportConfig":
                   return cls(
                      openai_api_key=data.get("openai_api_key", ""),
                      neo4j_uri=data.get("neo4j_uri", "")
                  )

              # 方式4：从配置文件加载
              @classmethod
              def from_file(cls, filepath: str) -> "ImportConfig":
                  import json
                  with open(filepath) as f:
                      data = json.load(f)
                  return cls.from_dict(data)

          实际使用
          # 方式1：手动传入参数
          config1 = ImportConfig(
              openai_api_key="sk-xxx",
              neo4j_uri="bolt://localhost:7687"
          )
        
          # 方式2：从环境变量加载
          config2 = ImportConfig.from_env()
        
          # 方式3：从字典加载
          config_data = {
              "openai_api_key": "sk-xxx",
              "neo4j_uri": "bolt://localhost:7687"
          }
          config3 = ImportConfig.from_dict(config_data)
        
          # 方式4：从配置文件加载
          config4 = ImportConfig.from_file("config.json")
        
          在这个代码中
          _config = ImportConfig.from_env()
          #                 ↑
          #            直接用类名调用
          # 等价于
          _config = ImportConfig(
              openai_api_base=os.getenv("OPENAI_API_BASE", ""),
              openai_api_key=os.getenv("OPENAI_API_KEY", ""),
              vl_model=os.getenv("VL_MODEL", ""),
              ... 自动读取所有环境变量
          )
        """
        _config = ImportConfig.from_env()
    return _config

