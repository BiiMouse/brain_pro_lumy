"""
导入流程自定义异常类，统一错误处理，提供更清晰的错误信息
ImportProcessError  # 基础异常
  ├── ConfigurationError          # 配置错误
  ├── FileProcessingError         # 文件处理错误
  │   ├── PdfConversionError      # PDF 转换错误
  │   └── ImageProcessingError    # 图片处理错误
  ├── DocumentSplitError          # 文档切分错误
  ├── EmbeddingError              # 向量化错误
  ├── LLMError                    # LLM 调用错误
  ├── StorageError                # 存储错误
  │   ├── MilvusError            # Milvus 错误
  │   ├── Neo4jError             # Neo4j 错误
  │   └── MinioError             # MinIO 错误
  └── ValidationError            # 验证错误
"""


class ImportProcessError(Exception):
    """导入流程基础异常"""
    """
    构造方法，在创建异常对象时自动调用
    super().__init__(message): 调用父类 Exception 的 __init__ 并传递 message
    让父类完成初始化（保存错误消息）这是必须的，因为父类需要知道错误消息才能正常工作
    这种设计让自定义异常既能存储额外信息（节点名、原始异常），又能通过 super() 复用父类的标准异常行为
    """
    def __init__(self, message: str, node_name: str = "", cause: Exception = None):
        self.node_name = node_name
        self.cause = cause
        super().__init__(message)

    """
    定义异常对象的字符串表示
    调用时机：需要将异常转换为字符串时, 如使用 print() 或 str() 时自动调用 
    super().__str__() 的作用：
      - 调用父类 Exception 的 __str__ 方法
      - 获取传入构造函数的原始 message 字符串
      - 这样可以复用父类的消息存储逻辑，而不是自己重新实现
    
    示例演示
      # 创建异常
      try:
          raise FileNotFoundError("原始文件未找到")
      except FileNotFoundError as e:
          error = ImportProcessError(
              message="处理失败",
              node_name="PDF导入",
              cause=e
          )
      打印异常时，__str__ 被调用
      print(error)  输出: [PDF导入] 处理失败 (原因: 原始文件未找到)
    """
    def __str__(self):
        # 创建列表存储各个部分
        parts = []
        #  如果有节点名
        if self.node_name:
            parts.append(f"[{self.node_name}]")
        # 获取父类的错误消息
        parts.append(super().__str__())
        if self.cause:
            parts.append(f"(原因: {self.cause})")
        return " ".join(parts)


class ConfigurationError(ImportProcessError):
    """配置错误：环境变量缺失或配置值无效"""
    pass


class FileProcessingError(ImportProcessError):
    """文件处理错误：文件不存在、格式错误、读写失败"""
    pass


class PdfConversionError(FileProcessingError):
    """PDF 转换错误：MinerU 转换失败"""
    pass


class ImageProcessingError(FileProcessingError):
    """图片处理错误：图片总结、上传失败"""
    pass


class DocumentSplitError(ImportProcessError):
    """文档切分错误：切分逻辑异常"""
    pass


class EmbeddingError(ImportProcessError):
    """向量化错误：模型调用失败、向量生成异常"""
    pass


class LLMError(ImportProcessError):
    """LLM 调用错误：API 调用失败、响应解析失败"""
    pass


class StorageError(ImportProcessError):
    """存储错误：数据库操作失败"""
    pass


class MilvusError(StorageError):
    """Milvus 存储错误"""
    pass


class Neo4jError(StorageError):
    """Neo4j 存储错误"""
    pass


class MinioError(StorageError):
    """MinIO 存储错误"""
    pass


class ValidationError(ImportProcessError):
    """数据验证错误：输入数据不符合预期"""
    pass

"""
问题： 
为什么要调用super().__init__(message)，是因为Exception的init方法有标准处理流程？
子类只需要传递message即可执行标准处理流程？
Exception类也有__str__()方法？

------- 回答如下--------
1. 要调用 super().__init__(message) 就是为了复用 Exception 基类的标准初始化流程。
内置的 Exception 类的 __init__ 方法里有标准、成熟、官方的错误处理逻辑，包括：
    -存储错误信息 message
    -处理异常参数
    -兼容 Python 所有异常机制（try/except、日志、堆栈追踪等）
ImportProcessError 是子类，它扩展了异常（加了 node_name、cause），但基础功能必须依赖父类。
所以：super().__init__(message)意思就是：我自己处理新增的属性，父类你负责处理标准的错误消息，我们分工合作。

2. 子类只需要传递 message 就能执行标准处理流程。是的！完全正确。
父类 Exception 已经把标准流程封装好了，你只需要把 message 传给它，它就会：
    -把 message 存到内部属性 args
    -让 str(e)、repr(e) 正常工作
    -让异常打印、日志记录都正常
子类不需要重复造轮子，只需要传参即可

3. Exception 类也有 __str__() 方法？当然有！而且是 Python 官方实现的标准字符串输出方法。
parts.append(super().__str__())就是在调用父类 
Exception 的 str()，它会输出你当初传进去的 message。
如果你这样抛异常：
    raise ImportProcessError("文件读取失败")
那么：
super().__str__()  # 输出："文件读取失败"
你自己的 __str__ 只是在父类输出的基础上，额外拼接了节点名和原因，让错误信息更丰富。
"""