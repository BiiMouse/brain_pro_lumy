### 步骤3 图片处理


import base64
import os
import re
from pathlib import Path
from typing import Tuple, List
from openai import OpenAI
from knowledge.processor.import_process.base import BaseNode
from knowledge.processor.import_process.config import get_config

from knowledge.processor.import_process.state import ImportGraphState
from knowledge.utils.minio_util import get_minio_client

# md里面图片处理类
class MdImageNode(BaseNode):
    def process(self, state: ImportGraphState) -> ImportGraphState:
        """处理 Markdown 文档中的图片"""
        self.log_step("图片处理", "[开始处理图片]")

        # 获取 MD 内容和图片路径
        md_content, md_path, image_path, source_md_path = self.get_md_content(state)

        # 添加调试日志
        print(f"[图片处理] md_path: {md_path}")
        print(f"[图片处理] image_path: {image_path}")
        print(f"[图片处理] source_md_path: {source_md_path}")
        print(f"[图片处理] image_path.exists(): {image_path.exists()}")

        # 如果没有图片文件夹，直接返回
        if not image_path.exists():
            print(f"[图片处理] images文件夹不存在，跳过图片处理: {image_path}")
            state['md_content'] = md_content
            return state

        print(f"[图片处理] images文件夹存在，开始处理图片")

        # 获取图片及其上下文内容
        target_images_context = self.get_images_context(image_path, md_content)

        # 调用视觉模型生成图片摘要
        images_summaries = self.create_image_summary(md_path, target_images_context)

        # 上传图片到 MinIO 并更新 MD 内容
        new_md_content = self.upload_img_update_md(md_path, md_content, images_summaries, target_images_context)

        # 写回源文件（如果提供了原始文件路径）
        if source_md_path and source_md_path.exists():
            with open(source_md_path, 'w', encoding='utf-8') as f:
                f.write(new_md_content)
            print(f"[图片处理] 已更新源文件: {source_md_path}")
        else:
            # 如果没有原始路径，写回上传后的文件
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(new_md_content)
            print(f"[图片处理] 已更新处理文件: {md_path}")

        state['md_content'] = new_md_content
        return state

    def get_md_content(self, state: ImportGraphState) -> Tuple[str, Path, Path, Path]:
        """获取 MD 内容和图片路径

        Returns:
            (md_content, md_path, image_path, source_md_path)
            - md_content: markdown文件内容
            - md_path: 用于读取的markdown文件路径
            - image_path: images文件夹路径
            - source_md_path: 需要写回的源文件路径（如果有）
        """
        # 优先使用原始文件路径
        original_file_path = state.get('original_file_path', '')
        print(f"[图片处理] state中的original_file_path: {original_file_path}")

        if original_file_path and Path(original_file_path).exists():
            md_path = original_file_path
            source_md_path = Path(original_file_path)
            print(f"[图片处理] 使用原始文件路径")
        else:
            # 回退到上传后的路径
            md_path = state['md_path']
            source_md_path = None  # 没有原始路径
            print(f"[图片处理] 使用上传后的路径: {md_path}")

        md_path_obj = Path(md_path)

        if not md_path_obj.exists():
            raise FileNotFoundError(f"md文件不存在: {md_path}")

        with open(md_path_obj, "r", encoding="utf-8") as f:
            md_content = f.read()

        # 图片路径为 md 同级目录下的 images 文件夹
        image_path = md_path_obj.parent / "images"
        print(f"[图片处理] 构建的image_path: {image_path}")

        return md_content, md_path_obj, image_path, source_md_path

    def pre_parse_md_document(self, md_content: str) -> dict:
        """
        预解析 MD 文档，建立索引结构
        返回：{md_lines, title_index, image_locations, line_to_title, sorted_title_indices}

        优化策略：批量处理代替逐个处理，减少循环嵌套
        原方案：遍历图片文件 → 查找MD中的位置 → 获取上下文（3层嵌套）
        优化后：遍历MD文档 → 按顺序处理图片位置 → 检查文件存在（2层嵌套）
        """
        md_lines = md_content.split("\n")

        # 建立标题索引 - 一次解析，多次复用
        title_index = {}
        for i, line in enumerate(md_lines):
            if re.match(r"^#{1,6}\s+", line):
                title_index[i] = line

        # 建立图片位置索引 - 优化重点：按MD文档顺序存储
        # 原方案：image_locations = {img_name: [line_index1, line_index2, ...]}
        #   问题：需要先遍历文件系统中的图片，再查找位置（造成嵌套）
        # 优化后：image_locations_in_order = [(line_index1, img_name1), (line_index2, img_name2), ...]
        #   优势：直接按MD文档顺序处理，无需先遍历文件系统，减少一层循环
        image_locations_in_order = []
        for i, line in enumerate(md_lines):
            # 匹配标准 Markdown 图片语法：![图片](path)
            img_match = re.search(r"!\[.*?\]\((.*?)\)", line)
            # 如果没有匹配，尝试匹配 HTML <img> 标签：<img src="path" />
            if not img_match:
                img_match = re.search(r'<img\s+src=["\'](.*?)["\']', line, re.IGNORECASE)

            if img_match:
                img_path = img_match.group(1)
                img_name = os.path.basename(img_path)
                image_locations_in_order.append((i, img_name))

        # 为每行建立所属标题映射（O(1)查找）- 用空间换时间
        line_to_title = {}
        last_title_idx = 0
        for i in range(len(md_lines)):
            if i in title_index:
                last_title_idx = i
            line_to_title[i] = last_title_idx

        # 预排序标题索引 - 用于二分查找优化
        # 原方案：每次查找下一个标题时都要重新排序
        # 优化后：预排序一次，后续使用二分查找（O(log n)）
        sorted_title_indices = sorted(title_index.keys()) # [0, 4, 20, 38, 48, 116]

        return {
            'md_lines': md_lines,
            'title_index': title_index, # {0: '## 个人简历 PERSONAL RESUME', 4: '## 个人信息', 20: '## 教育经历', 38: '## 工作经历', 48: '## 项目经历：集装箱物流可视项目', 116: '## 自我评价'}
            'image_locations_in_order': image_locations_in_order, # [(18, 'e5b959eb138729c623731f44b1282b29bc64e88f84f896c314cf0ea6472d0b50.jpg')]
            'line_to_title': line_to_title, # {0: 0, 1: 0, 2: 0, 3: 0, 4: 4, 5: 4, 6: 4, 7: 4, 8: 4, 9: 4, 10: 4, 11: 4, 12: 4, 13: 4, 14: 4, 15: 4, 16: 4, 17: 4, 18: 4, 19: 4, 20: 20, 21: 20, 22: 20, 23: 20, 24: 20, 25: 20, 26: 20, 27: 20, 28: 20, 29: 20, 30: 20, 31: 20, 32: 20, 33: 20, 34: 20, 35: 20, 36: 20, 37: 20, 38: 38, 39: 38, 40: 38, 41: 38, 42: 38, 43: 38, 44: 38, 45: 38, 46: 38, 47: 38, 48: 48, 49: 48, 50: 48, 51: 48, 52: 48, 53: 48, 54: 48, 55: 48, 56: 48, 57: 48, 58: 48, 59: 48, 60: 48, 61: 48, 62: 48, 63: 48, 64: 48, 65: 48, 66: 48, 67: 48, 68: 48, 69: 48, 70: 48, 71: 48, 72: 48, 73: 48, 74: 48, 75: 48, 76: 48, 77: 48, 78: 48, 79: 48, 80: 48, 81: 48, 82: 48, 83: 48, 84: 48, 85: 48, 86: 48, 87: 48, 88: 48, 89: 48, 90: 48, 91: 48, 92: 48, 93: 48, 94: 48, 95: 48, 96: 48, 97: 48, 98: 48, 99: 48, 100: 48, 101: 48, 102: 48, 103: 48, 104: 48, 105: 48, 106: 48, 107: 48, 108: 48, 109: 48, 110: 48, 111: 48, 112: 48, 113: 48, 114: 48, 115: 48, 116: 116, 117: 116, 118: 116, 119: 116, 120: 116, 121: 116, 122: 116, 123: 116, 124: 116}
            'sorted_title_indices': sorted_title_indices # [0, 4, 20, 38, 48, 116]
        }

    def get_images_context(self, image_path: Path, md_content: str) -> List[Tuple[str, str, Tuple[str, str, str]]]:
        """
        获取所有图片的上下文信息

        优化策略：调整处理顺序，减少循环嵌套
        原方案问题：
          第1层：遍历文件系统中的图片文件 (100个)
          第2层：对每个图片，遍历MD中的位置 (5处)
          第3层：对每个位置，查找下一个标题 (100个标题)
          时间复杂度：O(图片数 × 位置数 × 标题数) = O(n × m × k)

        优化后方案：
          第1层：遍历MD中的图片位置 (500处)
          第2层：检查文件是否存在，获取上下文 (O(1)查找)
          时间复杂度：O(MD中图片数) = O(n)

        性能提升：从 O(n × m × k) 降至 O(n)，其中 n=MD中图片数，m=每个图片位置数，k=标题数
        """
        target_images_context = []

        # 预解析 MD 文档
        parsed_data = self.pre_parse_md_document(md_content)

        # 获取有效的图片文件集合 - 用于O(1)存在性检查
        config = get_config()

        # {'e5b959eb138729c623731f44b1282b29bc64e88f84f896c314cf0ea6472d0b50.jpg'}
        valid_images_set = {
            img_name for img_name in os.listdir(image_path)
            if os.path.splitext(img_name)[1] in config.image_extensions
        }

        # 按MD文档顺序处理图片位置 - 减少一层循环
        for line_index, img_name in parsed_data['image_locations_in_order']:
            # O(1)检查图片文件是否存在
            if img_name not in valid_images_set:
                continue

            # 直接获取上下文（已使用预解析的索引，无需再次遍历）
            img_context = self.build_img_context(parsed_data, line_index)
            if img_context is not None:
                target_images_context.append((img_name, image_path, img_context))

        return target_images_context

    def build_img_context(self, parsed_data: dict, line_index: int) -> Tuple[str, str, str]:
        """
        根据预解析数据获取图片上下文

        优化策略：利用预建立的索引，避免重复遍历
        - line_to_title 映射：O(1)获取所属标题
        - sorted_title_indices：预排序的标题索引，支持二分查找
        """
        md_lines = parsed_data['md_lines']
        title_index = parsed_data['title_index']
        line_to_title = parsed_data['line_to_title']
        sorted_title_indices = parsed_data['sorted_title_indices']

        # 获取所属标题（O(1)查找）
        head_index = line_to_title.get(line_index, 0)
        head_title = title_index.get(head_index, "")

        # 获取上文内容
        pre_content = md_lines[head_index + 1:line_index]
        pre_context = self.image_context_limit(pre_content, "front")

        # 获取下文内容 - 使用二分查找优化
        end_index = self.find_next_title_index(sorted_title_indices, line_index, len(md_lines))
        post_content = md_lines[line_index + 1:end_index]
        post_context = self.image_context_limit(post_content, "back")

        return (head_title, pre_context, post_context)

    def find_next_title_index(self, sorted_title_indices: list, line_index: int, max_index: int) -> int:
        """
        查找当前行之后的下一个标题索引

        优化策略：使用二分查找代替线性遍历
        原方案：for title_idx in sorted(title_index.keys()) - O(k) 线性遍历
        优化后：使用 bisect 模块进行二分查找 - O(log k)

        性能提升：从 O(k) 降至 O(log k)，其中 k 为标题数量
        例如：100个标题，从100次比较降至7次比较
        """
        import bisect

        # 使用二分查找找到第一个大于 line_index 的标题位置
        pos = bisect.bisect_right(sorted_title_indices, line_index)

        # 如果找到，返回该标题索引；否则返回文档末尾
        return sorted_title_indices[pos] if pos < len(sorted_title_indices) else max_index

    def image_context_limit(self, substr_content: list, substr_type: str) -> str:
        """限制上下文内容长度，截取前或后200字符"""
        current_content = []
        final_content = []

        # 按空行和图片分割段落
        for line in substr_content:
            clean_line = line.strip()
            if not clean_line:  # 空行
                if current_content:
                    final_content.append("\n".join(current_content))
                    current_content = []
            else:
                # 遇到图片则结束当前段落
                if re.match(r"^!\[.*?\]\(.*?\)$", clean_line):
                    if current_content:
                        final_content.append("\n".join(current_content))
                        current_content = []
                    continue
                current_content.append(line)

        if current_content:
            final_content.append("\n".join(current_content))

        # front 类型需要反转（从图片向上取）
        if substr_type == "front":
            final_content.reverse()

        # 限制总字符数为200
        max_char = 200
        total = 0
        selected = []
        for para in final_content:
            para_len = len(para)
            if (total + para_len) > max_char and selected:
                break
            selected.append(para)
            total += para_len

        if substr_type == "front":
            selected.reverse()

        return "\n\n".join(selected)

    def create_image_summary(self, md_path, target_images_context):
        """调用视觉模型生成图片摘要（待实现）"""
        summaries = {}
        for img_name, img_path, img_context in target_images_context:
            img_file_path = str(img_path/img_name)
            summary = self.get_summary_singleImg(md_path, img_file_path, img_context)
            summaries[img_name] = summary
        return summaries

    def get_summary_singleImg(self, md_path, img_file_path, img_context):
        # 原则：把图片 + 上下文信息，提交vlm，生成摘要
        head_title, pre_context, post_context = img_context
        data = []
        if head_title:
            data.append(head_title)
        if pre_context:
            data.append(pre_context)
        if post_context:
            data.append(post_context)
        context = "\n".join(data)

        image_data_str = ""
        # 读取图片内容，二进制内容，使用base64把图片转换字符串
        with open(img_file_path, "rb") as f:
            image_data_str = base64.b64encode(f.read()).decode("utf-8")

        # 开始调用vlm视觉模型, 创建client
        config = get_config()
        # 使用VLM专用配置（通义千问）
        client = OpenAI(
            api_key=config.vl_model_api_key,
            base_url=config.vl_model_api_base
        )
        document_name = md_path.stem
        messages = [
            {"role": "user",
             "content": [
                 {
                     "type": "text",
                     "text": f"""任务：为Markdown文档中的图片生成一个简短的中文标题。
                                 背景信息：
                                     1. 所属文档标题："{document_name}"
                                     2. 图片上下文：{context}
                                     请结合图片视觉内容和上述上下文信息，用中文简要总结这张图片的内容，
                                     生成一个精准的中文标题（不要包含"图片"二字）。""",
                 },
                 {
                     "type": "image_url",
                     "image_url": {
                         "url": f"data:image/jpeg;base64,{image_data_str}"
                     }
                 }
             ]
             }
        ]
        # 调用
        response = client.chat.completions.create(
            model=config.vl_model,
            messages=messages,
        )

        summary = response.choices[0].message.content.strip()
        return summary

    def upload_img_update_md(self, md_path, md_content, images_summaries, target_images_context):
        """上传图片到 MinIO 并更新 MD 内容（待实现）"""
        # 1 上传图片到minio服务，生成可以访问地址
        remote_urls = {}
        # 创建minio客户端对象
        minio_client = get_minio_client()
        config = get_config()
        # 上传图片，获取上传每个图片信息（图片路径，图片名称等）
        for img_name, img_path, _ in target_images_context:
            img_file_path = str(img_path/img_name)
            object_name = f"{md_path.stem}/{img_name}"
            minio_client.fput_object(
                config.minio_bucket,
                object_name,
                img_file_path,
            )
            remote_url = (
                "http://"
                + config.minio_endpoint +
                "/" + config.minio_bucket + "/" + object_name
            )
            remote_urls[img_name] = remote_url
        new_md_content = md_content
        count = 0
        for img_name, img_summary in images_summaries.items():
            # 根据摘要文件名称 获取对应访问路径
            remote_url = remote_urls.get(img_name)
            if not remote_url:
                continue
            # 把摘要和对应路径更新到md内容里面

            # 先尝试替换 Markdown 格式：![alt](path)
            replace_pattern_md = re.compile(
                r"!\[(.*?)\]\((.*?" + re.escape(img_name) + r".*?)\)",
                re.IGNORECASE)
            md_matches = replace_pattern_md.findall(new_md_content)

            # 再尝试替换 HTML 格式：<img src="path" />
            replace_pattern_html = re.compile(
                r'<img\s+src=["\'](.*?' + re.escape(img_name) + r'.*?)["\'][^>]*>',
                re.IGNORECASE)
            html_matches = replace_pattern_html.findall(new_md_content)

            # 根据原格式进行替换
            if md_matches:
                new_md_content = replace_pattern_md.sub(f"![{img_summary}]({remote_url})", new_md_content)
                count += len(md_matches)

            if html_matches:
                new_md_content = replace_pattern_html.sub(f'<img src="{remote_url}" alt="{img_summary}" />', new_md_content)
                count += len(html_matches)

        print(f"count: {count}")
        return new_md_content

if __name__ == '__main__':
    md_image_node = MdImageNode()
    state = {
        "md_path": r"D:\dev\hak180产品安全手册\auto\hak180产品安全手册.md"
    }
    md_image_node.process(state)