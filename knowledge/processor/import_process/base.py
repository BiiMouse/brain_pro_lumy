"""
导入流程节点基类, 定义统一的节点接口规范，提供通用功能
  - BaseNode：所有流程节点的抽象基类
  - 实现了 __call__ 方法，提供统一的日志、错误处理和任务追踪
  - 子类只需实现 process 方法即可作为 LangGraph 节点使用
  - 为什么这么做：统一接口规范，便于在 LangGraph 工作流中组合多个节点，提供一致的错误处理和日志记录
"""

from abc import ABC, abstractmethod
from typing import TypeVar, Optional
import logging

from knowledge.processor.import_process.config import ImportConfig, get_config
from knowledge.processor.import_process.exceptions import ImportProcessError

"""
TypeVar用于创建泛型。定义一个类型变量，名称叫"T"
为什么需要它？
看BaseNode的几个方法签名: def __call__(self, state: T) -> T:
 def process(self, state: T) -> T:，这里的T表示“可以是任何类型”。我们举例子，假设你有不同的状态类型：
场景1：状态是字典
    dict_state = {"file": "data.csv"}
    node1 = MyNode()
    result1 = node1(dict_state)  # T 在这里是 dict
场景2：状态是列表
    list_state = [1, 2, 3]
    result2 = node1(list_state)  # T 在这里是 list

为啥要写 T = TypeVar("T") 
1.类型安全，不用 TypeVar 类型检查器会认为 state 和返回值无关
  def process(self, state: dict) -> dict: 
  用 TypeVar - 类型检查器知道输入输出是同一类型，传入 dict，返回也是 dict
2.灵活性，不用为每种状态类型写不同的类，一个BaseNode可以处理任何类型状态

在这个项目中
  LangGraph 的 state 可能是：dict（最常见）、自定义的 TypedDict、BaseModel
  用 T = TypeVar("T") 让 BaseNode 能适配所有这些情况。
  理解了吗？简单说就是：T 是一个占位符，代表"任意类型"，但输入输出类型必须一致。
"""
T = TypeVar("T")  # 泛型状态类型

"""
 ABC 是 Abstract base class的缩写，来自python的abc模块。
 主要用于：防止直接实例化 -> base = BaseNode(); 强制子类实现抽象方法：这个类必须实现process方法，否则无法实例化
 原因：在这个baseNode的场景中
    1.定义了所有节点必须遵循的接口规范
    2.确保每个节点都实现process()，第77行@abstractmethod
    3.统一了日志、错误处理
    4.防止误用基类
 ABC就像一个模板，规定了子类必须有什么方法，但是自己不能直接使用。考虑一个建筑图纸，你不能住在图纸里，但可以根据图纸建设很多
 真正的房子。
"""
class BaseNode(ABC):
    name: str = "base_node"  # 节点名称，子类应覆盖

    """
    Optional 是 Python typing 模块中的一个类型提示工具，参数是可选的（optional），不是必需的
    Optional[X] 是 X | None 的简写，表示：
      1.可以是 ImportConfig 对象
      2.或者是 None
    = None 表示默认值是 None
    完整的意思是：
      1.可以传入 ImportConfig 对象：node = MyNode(config)
      2.使用默认值 None：node = MyNode()
      3.也可以显式传入 None：node = MyNode(None)
    """
    def __init__(self, config: Optional[ImportConfig] = None):
        self.config = config or get_config()
        self.logger = logging.getLogger(f"import.{self.name}")


    """
    __xxx__ 这种命名叫做 ”魔术方法“，也叫python内置的特殊方法，会在特定时机调用他们
    1.__init__ 在创建对象时自动调用，初始化对象的属性一次
    2.__call__ 让对象像函数一样被调用，每次执行一次对象（）时都会调用，可多次调用，更简洁
        class Adder:
              def __init__(self, n):
                  self.n = n
              def __call__(self, x):
                  return x + self.n
        add5 = Adder(5)  # 调用 __init__
        res = add5(10) # 15, 调用__call__
        
        在此项目中看实际应用哦：
          class BaseNode(ABC):
            def __init__(self, config=None): # 初始化：创建对象时执行一次
              self.config = config
    
            def __call__(self, state): # 调用：每次执行节点时都会调用
              try:
                return self.process(state)
              except Exception as e:
                raise
          # 使用流程
          node = MyNode(config)      # 调用 __init__，初始化一次
          result = node(state)       # 调用 __call__，可以多次调用
          result = node(another_state)  # 再次调用 __call__
    3.__eq__     想自定义比较逻辑时
    """
    def __call__(self, state: T) -> T:
        """节点执行入口"""
        self.logger.info(f"--- {self.name} 开始 ---")

        try:
            result = self.process(state)
            self.logger.info(f"--- {self.name} 完成 ---")
            return result
        except ImportProcessError:
            # 已经是自定义异常，直接抛出
            raise
        except Exception as e:
            self.logger.error(f"{self.name} 执行失败: {e}")
            raise ImportProcessError(
                message=str(e),
                node_name=self.name,
                cause=e
            )

    """
    装饰器=函数的“包装器”，在不改原函数情况下，给函数添加额外功能。
    是 Python 解释器内置规定好的 “标签 / 标记”，给方法贴上这个标签，解释器就会自动改变它的调用规则
    这个效果不是函数自己有的，是解释器看到装饰器后强制做的处理。算语法糖
    比如
        @decorator
        def myFunction()
    等价于
        myFunction = decorator(myFunction)
    然后，我们借用@staticmethod 解释原理的工作流程是这样的：
    当你写 @staticmethod，Python 解释器识别这个内置标记，解释器修改这个方法的绑定行为
        ✅ 不自动传递实例 self
        ✅ 允许 类名.方法() 直接调用
        ✅ 也允许 实例.方法() 调用
    这一切都是解释器的行为，不是它后面函数自己的能力！
    1.@abstractmethod 抽象方法强制实现，子类必须实现它后面的方法
    2.@staticmethod 静态方法
        class MyClass:
          @staticmethod
          def greet():
              print("Hello")
        # 不需要 self，直接调用 MyClass.greet()
    3. @dataclass 数据类（自动生成方法）
          from dataclasses import dataclass
          @dataclass
          class User:
              name: str
              age: int
          # 自动生成 __init__, __repr__, __eq__ 等方法
          user = User("Alice", 25)
          print(user)  # User(name='Alice', age=25)
    4.@classmethod  第一个参数是类
    5.@property  像属性一样访问
    6.@lru_cache  缓存结果
    7.@wraps  保留函数信息
    """
    @abstractmethod
    def process(self, state: T) -> T:
        """节点核心处理逻辑，子类必须实现此方法。"""
        pass

    def log_step(self, step_name: str, message: str = ""):
        """记录步骤日志"""
        log_msg = f"[{step_name}]"
        if message:
            log_msg += f" {message}"
        self.logger.info(log_msg)

# 配置日志格式
"""
setup_logging是模块级函数，是全局的工具函数，不依赖任何实例，直接调用。不能写入类里面

原因是：配置全局日志系统，这是全局配置，影响整个程序，不应该属于某个类
  logging.basicConfig(...) 
  它只调用一次，在main.py 或程序入口，之后所有节点的日志都按这个格式输出
  from processor.import_process.base import setup_logging
  setup_logging(logging.INFO) 
"""
def setup_logging(level: int = logging.INFO):
    """
    配置导入流程日志,每条日志包含：时间、节点名、级别、消息
    Args:
        level: 日志级别
    """
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        force=True,  # import 链中第三方库可能已动过 root，强制接管，防止日志.log 空文件
    )
    logging.getLogger().setLevel(level)  # 双保险：显式压级别
