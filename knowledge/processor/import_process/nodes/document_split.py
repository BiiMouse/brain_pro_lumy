### 步骤4 文档切分

import json
import os.path
import re
from typing import Tuple, List, Any, Dict
from langchain_text_splitters import RecursiveCharacterTextSplitter
from knowledge.processor.import_process.base import BaseNode, setup_logging
from knowledge.processor.import_process.config import get_config
from knowledge.processor.import_process.state import ImportGraphState

# 文档切分节点
class DocumentSplitNode(BaseNode):
    def __init__(self):
        super().__init__()
        # 🟡 中优先级：性能优化 - 预编译正则为类属性
        # 修复：在初始化时预编译正则，避免重复编译，提升性能
        self.title_rule = re.compile(r"^\s*(#{1,6})\s+(.+)")

        # 🟡 中优先级：性能优化 - 缓存切分器分隔符列表
        # 修复：将分隔符列表缓存为类属性，减少初始化开销
        self.text_splitter_separators = ["\n\n", "\n", "。", "！", "？", " ", ""]

    def process(self, state: ImportGraphState) -> ImportGraphState:

        (md_content, file_title) = self.get_input_param(state)

        # 2 根据md的标题切分
        parts = self.split_doc_title(md_content, file_title)
        self.logger.info(f"根据标题切分内容：{parts}")
        self.logger.info("==" * 50)

        # 3 对根据标题切分内容再进行处理
        # [{body:111,title:第一章}，{body:666,title:第2章}]
        # 原则：如果每段内容过大再进行切分
        # 3.1 如果段内容过大切分，阈值每段最大不超过1000
        #     流程： 判断段内容如果小于1000，不切分返回
        #           判断段内容大于1000，切分，递归字符文本切分器
        #            ["\n\n","\n","。","！","？"," ",""]
        # 3.2 如果每段内容太小，多个段内容合并，阈值每段最小500
        #     流程：判断每段内容大于500，不合并返回
        #          判断每段内容小于500，进行多段合并
        #          合并规则：同源合并，找同一个parent_title段内容合并
        #     特殊：如果合并之后总大小大于100，不做处理
        config = get_config()
        # 2000, 500
        final_chunks = self.split_and_merge(parts,
                                            config.max_content_length,
                                            config.min_content_length)
       
        self.logger.info(f"切分合并内容：{final_chunks}")
        self.logger.info("==" * 50)

        # 4 对上面切分和合并返回列表，根据业务需求重新组装，组装满足具体业务结构
        chunks = self.collect_data(final_chunks)
       
        self.logger.info(f"最终组装结果：{chunks}")
        # 更新到state里面
        state['chunks'] = chunks

        # 5 其他：输出操作日志 和 备份json格式
        self.output_log(md_content, chunks, config.max_content_length)

        # 备份json格式
        self.copy_chunks(chunks, state)
        return state

    # 把拆分合并之后，最终组装的数据备份
    # 把数据生成json格式文件，保存到本地目录
    def copy_chunks(self, chunks, state):
        file_dir = state.get('file_dir')
        output_file_dir = os.path.join(file_dir, 'chunks.json')

        with open(output_file_dir, 'w', encoding='utf-8') as f:
            json.dump(chunks, f, ensure_ascii=False, indent=4)

    # 输出日志
    def output_log(self, md_content, chunks, max_content_length):
        # 统计md文档行
        line_count = md_content.count("\n") + 1
        self.logger.info(f"md文档共有{line_count}行")
        self.logger.info(f"最终切分章节数:{len(chunks)}")
        self.logger.info(f"最大切片长度:{max_content_length}")

        if chunks:
            self.logger.info("章节预览:")  # 只前5个章节，做简单预览；i为下标，sec为单个章节字典
            for i, sec in enumerate(chunks[:5]):
                # 取出标题，并且截断为前30个字符
                title = sec.get("title", "")[:30]
                self.logger.info(f"{i + 1}.{title}")
            if len(chunks) > 5:
                self.logger.info(f"还有{len(chunks) - 5}章节")

    # 对切分和合并数据重新组装
    def collect_data(self, final_chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        chunks = []
        for chunk in final_chunks:
            # {
            #     "title": title + "-" + f"{index + 1}",
            #     "body": text,
            #     "file_title": file_title,
            #     "parent_title": parent_title,
            #     "part": f"{index + 1}",
            # }
            title = chunk.get('title')
            body = chunk.get('body')
            file_title = chunk.get('file_title')
            parent_title = chunk.get('parent_title')

            # 最终内容 ：content 包含 title + body
            content = f"{title}\n\n{body}"

            data = {
                "title": title,
                "content": content,
                "file_title": file_title,
                "parent_title": parent_title,
            }
            if "part" in chunk:
                data['part'] = chunk.get('part')
            chunks.append(data)
        return chunks

    # 把标题切分 文档拆分和合并
    def split_and_merge(self, parts: List[Dict[str, Any]],
                        max_content_length: int,
                        min_content_length: int):
        # 1 对parts列表遍历，获取每段内容
        current_parts = []
        for part in parts:
            # 对每段内容，如果过大，再拆分. split_long_part的结果也是一个列表
            current_parts.extend(self.split_long_part(part, max_content_length))

        # 2 把上一步拆分之后每段内容，如果过小，进行合并
        final_chunks = self.merge_short_part(current_parts, min_content_length)
        return final_chunks

    # 内容过大继续切分
    def split_long_part(self, part, max_content_length):

        # {
        #     "title": new_title,
        #     "body": content,
        #     "file_title": file_title,
        #     "parent_title": parent_title,
        # }
        # 1 从每段内容part字典获取相关数据
        title = part.get('title')
        body = part.get('body')
        file_title = part.get('file_title')
        parent_title = part.get('parent_title')

        # 2 判断当前段内容是否超过最大大小 max_content_length
        # title处理
        if len(title) > 50:
            title = title[:50]

        # 计算title + body 总大小
        # 一般 切分大小计算：包含 title和body
        title_prefix = f"{title}\n\n"
        total_length = len(title_prefix) + len(body)
        # total_length max_content_length比较
        # 如果这段内容比要求大小小，直接返回
        if total_length <= max_content_length:
            return [part]

        body_size = max_content_length - len(title_prefix)

        # 创建分割器对象
        # 如果这段内容比要求大，继续切分.使用langchain封装递归字符文本切分器
        # 专门给大模型、RAG、向量库用的文本切割,按分隔符一层层递归切割文本，尽量不把句子切断

        text_splitter = RecursiveCharacterTextSplitter(
            # 切分每段大小是多大
            chunk_size=body_size, # 每一块最大长度
            chunk_overlap=0, # 块之间没有重叠, 完全切开，不重复
            separators=self.text_splitter_separators, # 自定义分隔符列表,按优先级从大到小切割。
            keep_separator=False, # 切割后，不保留分隔符
        )

        # 输入：一长串字符串 body  输出：字符串列表，每一段都是一个小块
        texts = text_splitter.split_text(body)

        # 把切分之后列表，再处理，返回业务相关字段和值
        f_parts = []
        # 递归字符文本切分器返回列表遍历
        for index, text in enumerate(texts):
            f_parts.append({
                "title": title + "-" + f"{index + 1}",
                "body": text,
                "file_title": file_title,
                "parent_title": parent_title,
                "part": f"{index + 1}",
            })
        return f_parts

    # 同源切分内容，其内容过小的合并
    def merge_short_part(self, current_parts, min_content_length):
        # current_parts传递切分之后列表 [{...},{....}]
        # 添加空列表检查，为空时直接返回空列表
        if not current_parts:
            return []

        # 获取列表第一段内容,以第一段为基准
        current_part = current_parts[0]

        # 创建列表
        f_parts = []

        # 从第二段内容开始遍历
        for next_part in current_parts[1:]:
            # 判断下一段内容和当前内容是否同源 是否同一个parent_title
            same_parent = current_part["parent_title"] == next_part["parent_title"]

            # 目前只能确定current_part的字符数小于2000
            # 当前内容大小是否小于min_content_length
            body_len = len(current_part.get('body'))

            if same_parent and body_len < min_content_length:
                # 当前段内容 body  + 下一段内容 body
                #    1111  lstrip()  rstrip()  strip()
                current_part['body'] = current_part.get('body').rstrip() + "\n\n" + next_part.get('body').lstrip()
                current_part['title'] = current_part["parent_title"]
                current_part['part'] = 0
            else:
                # 非同源的，不合并
                f_parts.append(current_part)
                current_part = next_part

        # 处理最后一段内容， f_parts已经是切分完，字符大小500-2000之间
        f_parts.append(current_part)

        # 为同一父标题下的段落重新编号
        # 合并段落时将 part 设为0，因此需要在这里为同一父标题下的
        # 段落重新生成连续的序号，便于标识段落在其所属章节中的顺序位置
        # 问题：part_counter 使用列表但当作字典访问，会导致 TypeError
        # 修复：改为字典，可以正常存储键值对
        part_counter = {}
        result = []
        for part in f_parts:
            if "part" in part:
                parent_title = part["parent_title"]

                part_counter[parent_title] = (
                        part_counter.get(parent_title, 0) + 1)

                new_part = part_counter[parent_title]

                part["part"] = new_part
            result.append(part)
        return result

    # 根据标题切分
    # 从第一行开始向下操作：遇到标题结束，上面切分一段
    # [{body:111,title:第一章}，{body:666,title:第2章}]
    # 优化思路：
    #   1. 建立 title_index 索引 - O(1) 查找标题
    #   2. 建立 line_to_parent 映射 - O(1) 获取父标题
    #   3. 使用 title_level_stack 栈 - O(1) 维护层级关系
    #   4. 使用 bisect 二分查找 - O(log n) 查找下一个标题
    def split_doc_title(self,
                        md_content: str,
                        file_title: str) -> List[dict]:

        title_rule = self.title_rule
        # 根据\n获取md每行内容
        md_lines = md_content.split("\n")
        total_lines = len(md_lines)

        # 第一步：建立索引结构
        # 一次性解析，多次复用，避免重复遍历
        # 1. 建立标题索引 - {行号: 标题}
        title_index = {}
        # 2. 建立标题层级索引 - {行号: 层级}
        title_level = {}
        for i, line in enumerate(md_lines):
            match = title_rule.match(line)
            if match:
                # 处理标题行
                title_index[i] = line
                level = len(match.group(1))  # #=1, ##=2, ###=3
                title_level[i] = level

        # self.logger.info(f"title_index: {title_index}")
        # self.logger.info(f"title_level: {title_level}")
        # title_index:{6: '## HAK 180烫金机', 32: '## ▲警告', 36: '## 设备', 79: '## 电源线', 118: '## 设备', 130: '## 电源线', 138: '## 为设备选择一个安全的位置', 150: '## 设备', 154: '## 电源线', 158: '## 警告标签', 162: '## 设备保修和责任', 166: '## 设备和电源线', 174: '## 产品中有害物质的名称及含量'}
        # title_level:{6: 2, 32: 2, 36: 2, 79: 2, 118: 2, 130: 2, 138: 2, 150: 2, 154: 2, 158: 2, 162: 2, 166: 2, 174: 2}
        # 3. 预排序标题索引 - 用于二分查找
        import bisect
        sorted_title_indices = sorted(title_index.keys())

        # ========== 第二步：建立父标题映射 ==========
        # 优化：使用栈结构维护标题层级，避免线性查找
        # 原方案：for lv in range(current_level-1,0,-1) - O(n) 线性查找
        # 优化后：title_level_stack[-1] - O(1) 栈顶获取
        line_to_parent = {}
        title_level_stack = []  # 栈结构：[(行号, 层级)]

        for i in range(total_lines):
            # 如果当前行是标题，更新栈
            if i in title_level:
                current_level = title_level[i]
                # 这是一个标准的栈操作，用于维护Markdown标题的层级关系：
                # - 当遇到新标题时，弹出栈中所有层级大于或等于当前层级的标题
                # - 然后将当前标题压入栈
                # - 这样栈顶始终是当前行的直接父标题
                # 不会陷入无限循环，因为每次循环都会执行 pop()，栈会不断减小直到满足退出条件。
                while title_level_stack and title_level_stack[-1][1] >= current_level:
                    title_level_stack.pop()
                # 将当前标题压入栈
                title_level_stack.append((i, current_level))

            # 记录当前行的父标题（栈顶元素）
            if title_level_stack:
                line_to_parent[i] = title_level_stack[-1][0]
            else:
                line_to_parent[i] = None  # 没有父标题
        # self.logger.info(f"line_to_parent: {line_to_parent}")
        # self.logger.info(f"title_level_stack: {title_level_stack}")

        # ========== 第三步：辅助函数 ==========
        def find_next_title_index(current_index: int) -> int:
            """
            查找当前行之后的下一个标题索引
            优化：使用二分查找代替线性遍历
            原方案：for idx in sorted_title_indices - O(n)
            优化后：bisect.bisect_right - O(log n)
            """
            pos = bisect.bisect_right(sorted_title_indices, current_index)
            # 结果A if 条件 else 结果B
            return sorted_title_indices[pos] if pos < len(sorted_title_indices) else total_lines
            # """
            #     if pos<len(sorted_title_indices):
            #         return sorted_title_indices[pos]
            #     else:
            #         return total_lines
            # """

        def append_section(start_idx: int, end_idx: int) -> dict:
            """
            提取两个标题之间的内容为一个段落
            优化：使用切片代替 join，减少字符串操作
            """
            title = title_index.get(start_idx, "")

            # 获取父标题 - O(1) 查找
            parent_idx = line_to_parent.get(start_idx)
            if parent_idx is not None and parent_idx in title_index:
                parent_title = title_index[parent_idx]
            else:
                parent_title = title if title else file_title

            # 提取内容
            body_lines = md_lines[start_idx + 1:end_idx]
            body = "\n".join(body_lines)

            return {
                "title": title,
                "body": body,
                "file_title": file_title,
                "parent_title": parent_title,
            }

        # ========== 第四步：切分文档 ==========
        res = []

        # 处理文档开头（第一个标题之前的内容）
        if sorted_title_indices:
            first_title_idx = sorted_title_indices[0]
            if first_title_idx > 0:
                # 第一个标题之前有内容
                res.append({
                    "title": "",
                    "body": "\n".join(md_lines[:first_title_idx]),
                    "file_title": file_title,
                    "parent_title": file_title,
                })

            # 处理标题段落
            for i in range(len(sorted_title_indices)):
                current_title_idx = sorted_title_indices[i]
                next_title_idx = find_next_title_index(current_title_idx)

                # 提取段落
                section = append_section(current_title_idx, next_title_idx)
                if section["title"] or section["body"]:
                    res.append(section)
        else:
            # 整个文档没有标题
            res.append({
                "title": "",
                "body": md_content,
                "file_title": file_title,
                "parent_title": file_title,
            })
        return res

    # md格式标准化
    def get_input_param(self,
                        state: ImportGraphState) -> Tuple[str, str]:
        # 获取md内容
        md_content = state.get('md_content')
        # \r \r\n => \n
        if md_content:
            md_content = (md_content.replace("\r\n", "\n")
                          .replace("\r", "\n"))
        # 获取file_title
        file_title = state.get('file_title')
        return md_content, file_title

if __name__ == '__main__':
    setup_logging()
    doc_split_node = DocumentSplitNode()
    # 构建md_content
    file_path = r"D:\dev\hak180产品安全手册\auto\hak180产品安全手册.md"
    with open(file_path, "r", encoding="utf-8") as f:
        file_content = f.read()
    # 构建数据
    state = {
        "file_title": "6W100-整本手册",
        "md_content": file_content,
        "file_dir": r"D:\dev\hak180产品安全手册\auto"
    }

    doc_split_node.process(state)

"""
while title_level_stack and title_level_stack[-1][1] >= current_level:

> 可是我怎么没看到while的循环变量呢？另外这又是什么title_level_stack[-1][1]

● 很好的问题！让我详细解释这个特殊的while循环模式。

  1. 为什么没有"循环变量"？

  这是一个基于数据结构变化的循环，而不是传统的计数器循环。

  while title_level_stack and title_level_stack[-1][1] >= current_level:
      title_level_stack.pop()  # 每次执行都会改变栈的内容！

  关键点：每次循环执行 pop() 后，栈的内容就变了：
  - 栈长度减小
  - 栈顶元素改变
  - 循环条件动态变化

  对比传统循环：
  # 传统计数器循环
  i = 0
  while i < 10:
      print(i)
      i += 1  # 需要显式更新计数器

  # 这个栈循环
  while stack and stack[-1] >= value:
      stack.pop()  # 操作本身改变了数据，无需计数器

  2. title_level_stack[-1][1] 详解

  这是Python的列表和元组索引语法：

  title_level_stack = [(行号, 层级), (行号, 层级), ...]
  #                    元组[0]  元组[1]   ↑ 这是列表索引

  具体例子：
  title_level_stack = [(6, 2), (32, 3), (79, 2)]
  #                    ↑    ↑   ↑    ↑   ↑    ↑
  #                  行号 层级 行号 层级 行号 层级

  title_level_stack[-1]      # (79, 2)  ← 获取栈顶元组
  title_level_stack[-1][0]   # 79       ← 元组的第1个元素（行号）
  title_level_stack[-1][1]   # 2        ← 元组的第2个元素（层级）

  3. 实际运行演示

  让我用一个具体例子说明这个循环如何工作：

  # 假设当前栈中有这些标题
  title_level_stack = [(6, 1), (32, 2), (79, 3)]
  #                    一级  二级      三级

  # 现在遇到一个新的二级标题
  current_level = 2

  # 第1次循环：栈顶是 (79, 3)，层级3 >= 2，条件满足
  while title_level_stack and title_level_stack[-1][1] >= current_level:  # 3 >= 2 ✓
      title_level_stack.pop()  # 弹出 (79, 3)
      # 栈变为：[(6, 1), (32, 2)]

  # 第2次循环：栈顶是 (32, 2)，层级2 >= 2，条件满足
  while title_level_stack and title_level_stack[-1][1] >= current_level:  # 2 >= 2 ✓
      title_level_stack.pop()  # 弹出 (32, 2)
      # 栈变为：[(6, 1)]

  # 第3次判断：栈顶是 (6, 1)，层级1 >= 2，条件不满足
  while title_level_stack and title_level_stack[-1][1] >= current_level:  # 1 >= 2 ✗
      # 循环结束！

  # 最终栈中保留了比当前层级低的标题
  title_level_stack = [(6, 1)]  # 只有比当前层级(2)小的标题保留

  4. 为什么要这样设计？

  这是为了维护Markdown标题的层级关系：

  # 一级标题 (level=1)
    ## 二级标题A (level=2)
      ### 三级标题 (level=3)
    ## 二级标题B (level=2)  ← 遇到这个时，需要弹出三级标题

  栈的作用：
  - 栈顶 = 当前行最近的父标题
  - 遇到新标题时，先弹出所有同级或下级标题
  - 再压入当前标题，这样栈顶就是新的父标题

  这种循环模式在算法中很常见，叫做**"栈清理循环"**！

"""