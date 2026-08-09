### 步骤2 PDF转换MD文档


# 用于 JSON 格式化输出
import json

#  面向对象的文件路径处理库
from pathlib import Path

import os
import subprocess
from typing import Tuple

from knowledge.processor.import_process.base import BaseNode, setup_logging
from knowledge.processor.import_process.state import ImportGraphState
from knowledge.processor.import_process.exceptions import ValidationError, FileProcessingError, PdfConversionError

# pdf转换md节点
# 1.对参数校验，目录是否存在
# 2.利用MinerU工具解析pdf成为md
# 3.获取md的path
# 4.返回数据

"""
PdfToMdNode 类继承自 BaseNode 类
"""


class PdfToMdNode(BaseNode):
    def process(self, state: ImportGraphState) -> ImportGraphState:
        # 1. 校验并获取路径（返回 Path 对象）
        pdf_path, output_dir = self.validate_path(state)

        # 2. 调用 MinerU 工具将 PDF 转换为 MD
        exit_code = self.execute_mineru(pdf_path, output_dir)

        if exit_code != 0:
            raise PdfConversionError("MinerU解析PDF失败")

        # 3. 获取生成的 MD 文件路径
        md_path_str = self.get_md_paths(pdf_path, output_dir)

        # 4. 更新 state 并返回
        state['md_path'] = md_path_str
        print(f"state: {state}")
        return state

    def validate_path(self,
                      state: ImportGraphState) -> Tuple[Path, Path]:
        self.log_step("step1", "对状态的路径输入参数做校验")

        # 1. 从 state 获取原始字符串路径
        pdf_path_str = state.get('import_file_path', '')
        output_dir_str = state.get('file_dir', '')

        # 2. 校验 PDF 路径非空
        if not pdf_path_str:
            raise ValidationError("解析的文件不存在")

        # 3. 字符串转为 Path 对象
        pdf_path = Path(pdf_path_str)
        print(f"PDF文件路径: {pdf_path_str}")

        # 4. 校验 PDF 文件真实存在
        if not pdf_path.exists():
            raise FileProcessingError("解析的文件路径不存在")

        # 5. 输出目录为空时，使用 PDF 文件所在目录作为兜底
        if not output_dir_str:
            output_dir_str = str(pdf_path.parent)

        # 6. 输出目录转为 Path 对象
        output_dir = Path(output_dir_str)

        # 7. 返回 Path 对象（用于后续 MinerU 调用）
        return pdf_path, output_dir

    # mineru转换pdf方法
    def execute_mineru(self, pdf_path: Path, output_dir: Path):
        """使用 MinerU 工具将 PDF 转换为 Markdown"""
        self.log_step("执行MinerU解析PDF")

        # 1. 设置环境变量
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        os.environ["HF_HOME"] = r"D:\dev\models"
        os.environ["MODELSCOPE_CACHE"] = r"D:\dev\models"
        os.environ["HUGGINGFACE_HUB_CACHE"] = r"D:\dev\models\hub"

        # 2. 构建命令行参数
        cmd = [
            "mineru", "-p",
            str(pdf_path),
            "-o",
            str(output_dir),
            "--source", "local",
            "--device", "cpu",
            "--backend", "pipeline",
            "--batch-size", "1"
        ]

        # 3. 执行命令行（子进程执行命令行）, 在子进程中执行外部命令，不会阻塞主进程
        proc = subprocess.Popen(
            args=cmd,  # 命令列表：["mineru", "-p", "..."]
            stdout=subprocess.PIPE,  # 标准输出捕获到管道
            stderr=subprocess.STDOUT,  # 标准错误重定向到标准输出
            errors="replace",  # 替换无法解码的字符
            text=True,  # 输出内容为字符串而非字节
            encoding="utf-8",  # 使用 UTF-8 编解码
            bufsize=1  # 按行缓冲
        )

        # 4. 实时获取并记录日志
        for line in proc.stdout:
            self.logger.info(f"执行MinerU日志{line}")

        # 5. 等待子进程完成。 作用：阻塞主进程，等待子进程执行完毕，返回退出码
        # 执行流程图：
        #   主进程          子进程（MinerU）
        #     │               │
        #     ├─ Popen ─────→ │ 启动
        #     │               │ 解析 PDF...
        #     │               ├─────────→ 日志输出（for line 遍历）
        #     │               │           ↓
        #     │               │        主进程记录日志
        #     ├─ wait() ──────┤ 等待完成
        #     │               │ 返回退出码
        #     │ ← exit_code ──┘
        #     │
        #     ↓ 继续执行
        exit_code = proc.wait()

        self.logger.info(f"MinerU解析的退出码：{exit_code}")
        if exit_code == 0:
            self.logger.info(f"MinerU成功解析PDF文件：{pdf_path.name}")
        else:
            self.logger.error(f"MinerU解析PDF文件：{pdf_path.name}失败")

        # 6. 返回退出码
        return exit_code

    # 获取生成的 Markdown 文件路径
    @classmethod
    def get_md_paths(cls, pdf_path: Path, output_dir: Path) -> str:
        """根据 PDF 文件名和输出目录，构建 MinerU 生成的 MD 文件路径"""
        file_name = pdf_path.stem  # 获取文件名（不含扩展名）
        md_path = (
                output_dir / file_name / "auto" / f"{file_name}.md"
        )  # MinerU 的输出路径结构: 输出目录/文件名/auto/文件名.md
        return str(md_path)  # 返回字符串路径


if __name__ == '__main__':
    setup_logging()
    pdf_to_md_node = PdfToMdNode()
    pdf_to_md_node_init_state = {
        "import_file_path": r"D:\AIpractise\shopkeer_brain\knowledge\processor\import_process\import_temp_dir\hak180产品安全手册.pdf",
        "file_dir": r"D:\dev"}
    processed_result = pdf_to_md_node.process(
        pdf_to_md_node_init_state)
    print(json.dumps(processed_result,
                     indent=4, ensure_ascii=False))
