"""
状态管理，定义整个导入流程中传递的数据结构
  - ImportGraphState：TypedDict 类型，包含任务ID、文件路径、控制标志、处理结果等
  - 提供默认状态和工厂函数 create_default_state
  - 为什么这么做：在 LangGraph 的节点间传递数据时，使用强类型的 TypedDict 可以提供类型提示，避免数据错误
定义完整的状态结构和辅助函数
"""

from typing import TypedDict, List, Dict, Any, Optional

import copy

"""
导入流程图状态，包含整个导入流程中传递的所有数据
TypedDict 提供类型提示，以检查字段类型。结构化数据，定义字典的固定结构。文档化，作为状态结构的文档说明

total=False 的含义：表示所有字段都是可选的。创建字典时，可以只包含部分字段。LangGraph 状态的推荐设置
这样做更灵活，不需要每次初始化所有字段，符合 LangGraph 的状态在流程中逐步演化的思路。
如果 total=True 必须每次都提供所有字段，失去渐进式构建的优势，增加代码复杂度

思考：
ImportGraphState 属性没有使用 field(default_factory=lambda...
而 config.py的@dataclass class ImportConfig 属性使用了。为什么？
回答:两个类使用了不同的类型系统
  ----------------------------------------------------------------------------
   特性               ImportConfig             state.py - ImportGraphState 
  ----------------------------------------------------------------------------
   装饰器              @dataclass              TypedDict              
   用途                创建可实例化的对象         定义字典的结构类型             
   是否需要 field()    需要                     ❌ 不需要                
   是否有 init         自动生成                  ❌ 没有构造函数           
  ---------------------------------------------------------------------------
  1. @dataclass - 数据类 (config.py)
      @dataclass
      class ImportConfig:
          # 需要用 field() 来处理可变默认值
          image_extensions: Set[str] = field(
              default_factory=lambda: {".jpg", ".png"}
          )
      为什么需要 field()？
          - @dataclass 会自动生成 __init__() 方法
          - 如果你直接写 extensions: Set[str] = {".jpg"}，所有实例会共享同一个集合（可变默认值陷阱）
          - 必须用 field(default_factory=...) 让每个实例获得独立的副本
      调用方式：
      config = ImportConfig();  config.image_extensions

  2. TypedDict - 类型字典 (state.py)
      from typing import TypedDict
      class ImportGraphState(TypedDict, total=False):
          task_id: str           # 只是类型注解
          is_pdf_read_enabled: bool
          chunks: List
    
      为什么不需要 field()？
          - TypedDict 本质不是类，是 typing 模块提供的结构化类型提示，运行时不存在，是静态检查工具的约定
          - 不会生成 __init__() 方法，不能实例化
          - 属性定义只是声明键的类型，不涉及默认值存储
          - 默认值需要在外部定义（如代码中的 GRAPH_DEFAULT_STATE）
      调用方式：
      # state = ImportGraphState()  ❌不能实例化！ 报错
      # 只能作为类型注解或直接创建字典
      state: ImportGraphState = {
          "task_id": "123",
          "chunks": []
      }
  总结
    1.为什么 ImportConfig 用 field()? 因为它是 @dataclass，需要用 field() 避免可变默认值陷阱，
    且 dataclass 会生成__init__() 创建实例
    2.为什么 ImportGraphState 不用 field()? 因为它是 TypedDict，只是字典的类型注解，不能实例化，
    没有默认值存储问题
    3.TypedDict 如何提供默认值?在外部定义常量字典（如 GRAPH_DEFAULT_STATE），
    然后用 copy.deepcopy() 创建副本

  简单记忆：
  - dataclass = 真正的类，需要实例化 → 用 field()
  - TypedDict = 只是类型提示，不是类 → 直接写字典，不用 field()
  
追问：为什么继承 TypedDict 后，ImportGraphState 就不是类了？
回答：
TypedDict 是个"特殊的基类"， 说明：
    1. 用 class 定义，但运行时不是真正的类
    2. 实例化后类型是 dict，不是自定义类
    3. 仅用于类型检查，不创建真实对象
    4. 无实例属性，不需要 field()，因为每次都是新字典，不会共享引用
    5. ImportGraphState 只是字典结构的类型标记

关于 ImportGraphState(TypedDict)    
    1. 语法上：它是用 class 定义的，看起来像类
    2. 运行时：不是真正的类，不能正常做 isinstance 判断
    3. 功能上：只是用来标记“这个字典必须包含哪些键、什么类型”
    4. 实例化：本质就是创建一个普通字典
"""
class ImportGraphState(TypedDict, total=False):

    # ==================== 任务标识 ====================

    task_id: str  # 任务 ID，用于任务追踪

    # ==================== 控制标志 ====================

    is_md_read_enabled: bool  # 是否启用 MD 读取

    is_pdf_read_enabled: bool  # 是否启用 PDF 读取

    # ==================== 路径信息 ====================

    import_file_path: str  # 导入文件路径（上传后的路径）

    file_dir: str  # 导入(出)文件目录

    original_file_path: str  # 原始文件路径（用户上传前的路径）

    pdf_path: str  # PDF 文件路径

    md_path: str  # 转换后Markdown 文件路径

    # ==================== 文件信息 ====================

    file_title: str  # 文件标题（不含扩展名）

    item_name: str  # 识别出的商品/产品名称

    # ==================== 处理中间数据 ====================

    md_content: str  # Markdown 文档内容

    chunks: List  # 文档切片列表

    # ==================== 默认状态 ====================


GRAPH_DEFAULT_STATE: ImportGraphState = {

    "task_id": "",

    "is_pdf_read_enabled": False,

    "is_md_read_enabled": False,

    "file_dir": "",

    "import_file_path": "",

    "original_file_path": "",

    "pdf_path": "",

    "md_path": "",

    "file_title": "",

    "md_content": "",

    "chunks": [],

    "item_name": "",

}

def create_default_state(**overrides) -> ImportGraphState:
    """
    创建默认状态，支持覆盖
    Args:
        **overrides: 要覆盖的字段
    Returns:
        新的状态实例
    Examples:
        state = create_default_state(task_id="task_001", local_file_path="doc.pdf")
    """
    state = copy.deepcopy(GRAPH_DEFAULT_STATE)
    state.update(overrides)
    return state


def get_default_state() -> ImportGraphState:
    """
    Returns:
        状态副本（避免全局污染）
    """
    """
    深拷贝：创建了一个完全独立的副本，所有层级的对象都是新创建的
    作用：避免多个任务共享同一个默认值，防止数据污染
    应用场景：工厂函数、多实例创建、状态管理
    当默认值包含可变对象（list、dict、set）时，总是使用 deepcopy() 创建副本
    --更形象的比喻
      ImportGraphState (TypedDict)  =  产品说明书（图纸）
        描述产品应该有哪些部件，运行时不存在

      GRAPH_DEFAULT_STATE           =  模板样品（1号）
        真实存在的字典，作为默认值参考
    
      copy.deepcopy(...)            =  复制样品（2号、3号...）
        创建独立的新字典，符合说明书规定的结构，但与"说明书类"无关，只是普通字典
    """
    return copy.deepcopy(GRAPH_DEFAULT_STATE)
