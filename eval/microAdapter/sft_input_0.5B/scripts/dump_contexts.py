"""把 HAK180 入库切片文件导出成每 chunk 一份 txt，作为 SFT contexts 的照抄基准。

为什么：模型推理时看到的是 Milvus 里解析后的 chunk（带 `# 标题`、`•\t` bullet、
解析器的空格归一），不是 PDF 视觉版式。手抄 PDF 会造出生产里不存在的文本
（例：PDF 的"设备"小标题被解析器吃成空 `#` 标题；`Brother不建议` 无空格）。
本脚本把入库前的全量切片 chunks.json 一股脑导出，写数据时对着复制。

用法（项目根目录下）:
    .venv/Scripts/python.exe eval/microAdapter/dump_contexts.py

产出: eval/microAdapter/chunk_00.txt ~ chunk_15.txt（每份 = 一个 chunk 的 content 原文）
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
CHUNKS = (HERE.parent.parent.parent.parent / "knowledge" / "front" / "temp_data" / "20260804"
          / "78dc0628-08d8-4d5e-8eb4-bfe3a5ed14f8" / "chunks.json")


def main():
    data = json.loads(CHUNKS.read_text(encoding="utf-8"))
    print(f"共 {len(data)} 个 chunk\n")

    for i, c in enumerate(data):
        # 文件名里去掉标题的 '#' 和空白，保留可读性
        safe = re.sub(r"[#\s/]+", "", c["title"])[:20] or "untitled"
        out = HERE.parent / "chunks" / f"chunk_{i:02d}_{safe}.txt"
        out.write_text(c["content"], encoding="utf-8")
        print(f"chunk_{i:02d}_{safe}.txt  ({len(c['content'])} 字)")

    print("\n写 contexts 时对着这些 txt 复制：段 = chunk 内一个自然段/一条 bullet，"
          "文字逐字（可去 `•\t` 前缀和行尾空格）；标题行可选，保留必须 `# xxx` 原样。")


if __name__ == "__main__":
    main()
