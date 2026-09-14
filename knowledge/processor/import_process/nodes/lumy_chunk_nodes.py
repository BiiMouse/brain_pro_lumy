### Lumy 链路A（语义）：从 pdf_tables.json 分块（带页码）+ 专用 Milvus 集合

"""
为什么 lumy 模式不走 MinerU：
  pdfplumber 产物（pdf_tables.json）已含 页文本 + 表格 + 页码，
  直接分块即得"页码精确"的语义切片；MinerU md 反而要二次恢复页码。
  （brain 模式继续走 MinerU，两模式互不影响。）

分块策略：
  - 表格 → 线性化为文本块（表头 + 行），超 25 行切片且每片重复表头
  - 页文本 → 段落累积 ~700 字符成块，短块向后合并
  - 自动剔除页眉页脚（在 ≥50% 页面重复出现的行）
  - chunk 携带 page/page_end/file_title/item_name(家族列表)
    查询侧用 file_title 标量过滤（多家族PDF的 item_name 是拼接串，
    Milvus `in` 是精确匹配，不能作过滤键）
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from knowledge.processor.import_process.base import BaseNode
from knowledge.processor.import_process.nodes.import_milvus_node import (
    ImportMilvusNode,
)
from knowledge.processor.import_process.state import ImportGraphState

# 分块参数
TEXT_TARGET_CHARS = 700     # 文本块目标大小
TEXT_MIN_CHARS = 120        # 低于此长度的块并入下一块
TABLE_SLICE_ROWS = 25       # 表格每片行数


def find_running_lines(pages: List[Dict[str, Any]]) -> set:
    """页眉页脚检测：在 ≥50% 页面（至少3页）逐行重复出现的行"""
    line_pages: Dict[str, set] = {}
    for p in pages:
        for line in (p.get("text") or "").splitlines():
            key = line.strip()
            if key:
                line_pages.setdefault(key, set()).add(p["page_no"])
    threshold = max(3, int(len(pages) * 0.5))
    return {k for k, v in line_pages.items() if len(v) >= threshold}


def linearize_table(table: Dict[str, Any]) -> List[str]:
    """表格 → 文本行列表（表头 + 数据行）"""
    rows = table.get("rows") or []
    if not rows:
        return []
    header = " | ".join(rows[0])
    lines = [f"列: {header}"]
    for r in rows[1:]:
        lines.append(" | ".join(r))
    return lines


class LumyDocumentSplitNode(BaseNode):
    """lumy 链路A 节点：pdf_tables.json + models.json(家族) → 带页码 chunks"""
    name = "lumy_document_split"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        pdf_tables_path = state.get("pdf_tables_path")
        models_path = state.get("models_path")
        if not pdf_tables_path:
            raise ValueError("pdf_tables_path 为空")
        with open(pdf_tables_path, encoding="utf-8") as f:
            pdf_data = json.load(f)

        families = []
        if models_path and Path(models_path).exists():
            with open(models_path, encoding="utf-8") as f:
                families = [x["family_name"] for x in json.load(f).get("families", [])]
        item_name = ",".join(families)
        file_title = state.get("file_title") or Path(pdf_data["file_name"]).stem

        pages = pdf_data["pages"]
        running = find_running_lines(pages)
        chunks: List[Dict[str, Any]] = []

        # 1. 表格块（每表一块，超长切片重复表头）
        for p in pages:
            for t in p.get("tables", []):
                lines = linearize_table(t)
                if not lines:
                    continue
                title = (t.get("title") or f"表格")[:80]
                header_line = lines[0]
                body = lines[1:]
                for s in range(0, len(body), TABLE_SLICE_ROWS):
                    piece = body[s:s + TABLE_SLICE_ROWS]
                    content = f"[表格:{title}](第{p['page_no']}页)\n{header_line}\n" + "\n".join(piece)
                    chunks.append({
                        "content": content, "title": title,
                        "parent_title": "",  # 共享 chunks schema 的非空标量字段
                        "file_title": file_title, "item_name": item_name,
                        "page": p["page_no"], "page_end": p["page_no"],
                    })

        # 2. 文本块（段落累积，剔页眉页脚）
        buf: List[str] = []
        buf_page = None

        def flush(end_page):
            nonlocal buf, buf_page
            text = "\n".join(buf).strip()
            if text and len(text) >= TEXT_MIN_CHARS:
                chunks.append({
                    "content": text,
                    "title": buf[0][:80],
                    "parent_title": "",  # 共享 chunks schema 的非空标量字段
                    "file_title": file_title, "item_name": item_name,
                    "page": buf_page, "page_end": end_page,
                })
            buf, buf_page = [], None

        for p in pages:
            for line in (p.get("text") or "").splitlines():
                key = line.strip()
                if not key or key in running:
                    continue
                if buf_page is None:
                    buf_page = p["page_no"]
                buf.append(key)
                if sum(len(x) for x in buf) >= TEXT_TARGET_CHARS:
                    flush(p["page_no"])
        flush(pages[-1]["page_no"] if pages else 1)

        # 3. 调试备份
        out_dir = Path(pdf_tables_path).parent
        with open(out_dir / "lumy_chunks.json", "w", encoding="utf-8") as f:
            json.dump(chunks, f, ensure_ascii=False, indent=1)

        state["chunks"] = chunks
        self.log_step("done", f"{file_title}: {len(chunks)} 块 "
                              f"(页眉页脚剔除 {len(running)} 行) → lumy_chunks.json")
        return state


class LumyImportMilvusNode(ImportMilvusNode):
    """lumy 专用 Milvus 入库：独立集合，不与 brain 数据混存

    集合名：环境变量 LUMY_CHUNKS_COLLECTION（默认 kb_lumy_chunks_v1）
    """
    name = "lumy_import_milvus"

    def _collection_name(self) -> str:
        return os.getenv("LUMY_CHUNKS_COLLECTION", "kb_lumy_chunks_v1")
