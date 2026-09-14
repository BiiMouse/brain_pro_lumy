### Lumy 链路B-步骤1 PDF表格与文本提取（pdfplumber）

"""
从规格书 PDF 提取页级结构化数据（Lumy 结构化链路的解析基础）：
  - 每页表格：rows（含合并单元格填充）、bbox、表上方最近标题
  - 每页表格区域之外的正文文本（供 LLM 区域标注使用）
  - 跨页续表合并：重复表头匹配 / 几何位置延续（页底→页顶 + 列数一致）

为什么用 pdfplumber 而不是 MinerU：
  - 链路B 需要精确的表格单元格 + 页码，pdfplumber 基于矢量线坐标提取，精度高、速度快
  - MinerU 继续服务链路A（语义分块），两条链路各自取长
  - 5 份 PDF 均为原生文本型（非扫描件），无需 OCR/多模态
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pdfplumber

from knowledge.processor.import_process.base import BaseNode, T
from knowledge.processor.import_process.state import ImportGraphState


# 表格提取参数：默认线策略（规格书表格都有边框线）
TABLE_SETTINGS = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "snap_tolerance": 4,
    "join_tolerance": 4,
    "intersection_tolerance": 4,
}

# 跨页续表判定的几何阈值（相对页面高度比例）
PREV_BOTTOM_RATIO = 0.80   # 前表底部需低于页高 80%（表延伸到页底）
CUR_TOP_RATIO = 0.30       # 后表顶部需高于页高 30%（从页顶开始）
# 重复表头匹配的相似度阈值
HEADER_MATCH_RATIO = 0.5


# ==================== 单元格清洗与合并单元格填充 ====================

def clean_cell(cell: Optional[str]) -> str:
    """单元格清洗：None→空串，内部换行→空格，去首尾空白"""
    if cell is None:
        return ""
    return " ".join(str(cell).split())


def clean_rows(raw_rows: List[List[Optional[str]]]) -> List[List[str]]:
    """整表清洗：清洗单元格 + 删除全空行 + 删除全空列（不做任何合并填充）"""
    rows = [[clean_cell(c) for c in row] for row in raw_rows]
    # 删除全空行
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return []
    # 删除全空列（pdfplumber 偶尔产生尾部空列）
    n_cols = max(len(r) for r in rows)
    rows = [r + [""] * (n_cols - len(r)) for r in rows]
    keep_cols = [j for j in range(n_cols) if any(r[j] for r in rows)]
    return [[r[j] for j in keep_cols] for r in rows]


def fill_merged_cells(table, raw_rows: List[List[Optional[str]]]) -> List[List[str]]:
    """基于 cell bbox 的精确合并单元格填充

    pdfplumber 中被合并覆盖的位置返回 None，但合并格自身的 bbox 会
    在 Table.rows[i].cells[j] 中体现（宽/高覆盖多个行/列条带）。
    因此：
      - 纵向合并（bbox 底边覆盖下方行条带）→ 值向下填充
      - 横向合并（bbox 右边覆盖右侧列条带）→ 值向右填充
    区别于盲目填充：真正"空的单元格"（bbox 只占一个条带）不会被填充。
    """
    rows = [[clean_cell(c) for c in row] for row in raw_rows]
    try:
        trows = table.rows
    except Exception:
        return rows
    n = len(trows)
    if n != len(rows) or n == 0:
        return rows

    # 列条带 x 范围：从该列任意非空 cell 的 bbox 收集
    n_cols = max(len(r) for r in rows)
    col_ranges = [None] * n_cols
    for i in range(n):
        cells = trows[i].cells
        for j in range(min(len(cells), n_cols)):
            c = cells[j]
            if c is not None and col_ranges[j] is None:
                col_ranges[j] = (c[0], c[2])

    # 1. 纵向：cell bbox 底边覆盖后续行条带 → 向下填充
    for i in range(n):
        cells = trows[i].cells
        for j in range(min(len(cells), len(rows[i]))):
            cell = cells[j]
            if cell is None:
                continue
            cbottom = cell[3]
            k = i + 1
            while k < n and trows[k].bbox[1] < cbottom - 1.0:
                if j < len(rows[k]) and not rows[k][j] and rows[i][j]:
                    rows[k][j] = rows[i][j]
                k += 1

    # 2. 横向：cell bbox 右边覆盖右侧列条带 → 向右填充
    for i in range(n):
        cells = trows[i].cells
        for j in range(min(len(cells), len(rows[i]))):
            cell = cells[j]
            if cell is None:
                continue
            cright = cell[2]
            k = j + 1
            while k < n_cols and col_ranges[k] is not None:
                if col_ranges[k][0] >= cright - 1.0:
                    break
                if k < len(rows[i]) and not rows[i][k] and rows[i][j]:
                    rows[i][k] = rows[i][j]
                k += 1
    return rows


# ==================== 单页提取 ====================

def nearest_title_above(page: pdfplumber.page.Page,
                        table_bbox: tuple) -> str:
    """找表格 bbox 上方最近的文本行，作为表格标题（供区域标注参考）"""
    try:
        lines = page.extract_text_lines()
    except Exception:
        return ""
    x0, top, x1, bottom = table_bbox
    candidates = [ln for ln in lines
                  if ln["bottom"] <= top and (top - ln["bottom"]) < 80]
    if not candidates:
        return ""
    candidates.sort(key=lambda ln: ln["bottom"])
    return candidates[-1]["text"].strip()


def extract_page(page: pdfplumber.page.Page, page_no: int) -> Dict[str, Any]:
    """提取单页：表格（含标题/bbox/行）+ 表格区域外的正文"""
    tables_found = page.find_tables(table_settings=TABLE_SETTINGS)

    tables = []
    remaining = page
    for t in tables_found:
        raw = t.extract()
        # 先做 bbox 精确合并填充（保持与 table.rows 对齐），再清洗删空行空列
        filled = fill_merged_cells(t, raw)
        rows = clean_rows(filled)
        if len(rows) < 2:
            # 单行不成表（多为页眉装饰线误判），跳过但不算表格
            continue
        tables.append({
            "page_no": page_no,
            "bbox": [round(v, 1) for v in t.bbox],
            "title": nearest_title_above(page, t.bbox),
            "n_rows": len(rows),
            "n_cols": len(rows[0]) if rows else 0,
            "rows": rows,
        })
        # 从页面裁掉表格区域，剩下的才是正文
        try:
            remaining = remaining.outside_bbox(t.bbox)
        except Exception:
            pass

    try:
        text = remaining.extract_text() or ""
    except Exception:
        text = ""

    return {"page_no": page_no, "text": text, "tables": tables}


# ==================== 跨页续表合并 ====================

def _header_similarity(row_a: List[str], row_b: List[str]) -> float:
    """两行表头的单元格相似度（忽略大小写/空串），返回 0~1"""
    if not row_a or len(row_a) != len(row_b):
        return 0.0
    hits = 0
    total = 0
    for a, b in zip(row_a, row_b):
        if not a and not b:
            continue
        total += 1
        if a.strip().lower() == b.strip().lower():
            hits += 1
    return hits / total if total else 0.0


def merge_cross_page_tables(pages: List[Dict[str, Any]],
                            page_heights: Dict[int, float]) -> List[Dict[str, Any]]:
    """跨页续表合并

    判定条件（相邻两页、列数一致）：
      a) 后表首行与前表首行（表头）相似度 >= HEADER_MATCH_RATIO → 重复表头，去表头后拼接
      b) 或几何延续：前表底部低于页高 80% 且后表顶部高于页高 30% → 直接拼接
    输出 merged_tables：{pages, title, n_cols, n_rows, rows}
    """
    merged: List[Dict[str, Any]] = []

    def table_geometry(pages_list, page_no, bbox):
        h = page_heights.get(page_no, 1000.0) or 1000.0
        return bbox[3] / h, bbox[1] / h  # (bottom_ratio, top_ratio)

    # 展平成 [(page_no, table)] 保持顺序
    flat = [(p["page_no"], t) for p in pages for t in p["tables"]]

    used = set()
    for idx, (page_no, table) in enumerate(flat):
        if id(table) in used:
            continue
        # 尝试与下一页的第一个未用表合并
        cur = {
            "pages": [page_no],
            "title": table["title"],
            "n_cols": table["n_cols"],
            "rows": [list(r) for r in table["rows"]],
        }
        search = idx + 1
        while search < len(flat):
            nxt_page_no, nxt_table = flat[search]
            if nxt_page_no != cur["pages"][-1] + 1:
                break  # 只合并物理相邻页
            if nxt_table["n_cols"] != cur["n_cols"]:
                break

            prev_bottom_r, _ = table_geometry(pages, cur["pages"][-1],
                                              _bbox_of(pages, cur["pages"][-1], table))
            _, cur_top_r = table_geometry(pages, nxt_page_no, nxt_table["bbox"])
            header_sim = _header_similarity(cur["rows"][0], nxt_table["rows"][0])

            is_repeat_header = header_sim >= HEADER_MATCH_RATIO
            is_geometric = (prev_bottom_r >= PREV_BOTTOM_RATIO
                            and cur_top_r <= CUR_TOP_RATIO)
            if not (is_repeat_header or is_geometric):
                break

            append_rows = (nxt_table["rows"][1:] if is_repeat_header
                           else nxt_table["rows"])
            cur["rows"].extend(list(r) for r in append_rows)
            cur["pages"].append(nxt_page_no)
            used.add(id(nxt_table))
            table = nxt_table  # 继续尝试连锁合并（跨 3 页以上）
            search += 1

        if len(cur["pages"]) > 1:
            cur["n_rows"] = len(cur["rows"])
            merged.append(cur)
    return merged


def _bbox_of(pages: List[Dict[str, Any]], page_no: int,
             table: Dict[str, Any]) -> List[float]:
    """从页列表里找回该表的 bbox（合并过程中 table 引用会被替换）"""
    if "bbox" in table:
        return table["bbox"]
    for p in pages:
        if p["page_no"] == page_no:
            for t in p["tables"]:
                if t["rows"] and table.get("rows") == t["rows"]:
                    return t["bbox"]
    return [0, 0, 0, 999]


# ==================== PDF 级提取 ====================

def extract_pdf(pdf_path: str) -> Dict[str, Any]:
    """整本 PDF 提取：页级表格+正文，并做跨页续表合并"""
    pdf_path = str(pdf_path)
    pages: List[Dict[str, Any]] = []
    page_heights: Dict[int, float] = {}

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            page_heights[i] = float(page.height)
            pages.append(extract_page(page, i))
        page_count = len(pdf.pages)

    merged_tables = merge_cross_page_tables(pages, page_heights)

    return {
        "file_name": Path(pdf_path).name,
        "pdf_path": pdf_path,
        "page_count": page_count,
        "pages": pages,
        "merged_tables": merged_tables,
    }


# ==================== LangGraph 节点封装 ====================

class PdfTableExtractNode(BaseNode):
    """链路B 节点：PDF → 页级表格/文本 JSON（供区域标注与型号提取消费）"""
    name = "pdf_table_extract"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        pdf_path = state.get("import_file_path")
        file_dir = state.get("file_dir", "")
        if not pdf_path:
            raise ValueError("import_file_path 为空")

        result = extract_pdf(pdf_path)

        # 输出到任务目录（与 MinerU 的 auto 目录约定平行）
        out_dir = Path(file_dir) / "lumy"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "pdf_tables.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)

        n_tables = sum(len(p["tables"]) for p in result["pages"])
        self.log_step("step1", f"{result['file_name']} 共{result['page_count']}页，"
                               f"提取表格{n_tables}个，跨页合并"
                               f"{len(result['merged_tables'])}组 → {out_path}")

        state["pdf_tables_path"] = str(out_path)
        state["pdf_page_count"] = result["page_count"]
        return state


# ==================== 独立运行入口（5 份 PDF 批量提取 + 验证摘要） ====================

if __name__ == "__main__":
    import sys

    ref_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("referencePDF")
    out_root = ref_dir / "lumy_extract"

    for pdf_file in sorted(ref_dir.glob("*.pdf")):
        print("=" * 60)
        print(f"提取: {pdf_file.name}")
        data = extract_pdf(str(pdf_file))

        out_dir = out_root / pdf_file.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "pdf_tables.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

        n_tables = sum(len(p["tables"]) for p in data["pages"])
        print(f"  页数={data['page_count']} 表格数={n_tables} "
              f"跨页合并组={len(data['merged_tables'])}")
        # 验证摘要：有表格的页 + 行数
        table_pages = [(p["page_no"], [t["n_rows"] for t in p["tables"]])
                       for p in data["pages"] if p["tables"]]
        print(f"  有表格的页: {table_pages[:25]}")
        for mt in data["merged_tables"]:
            print(f"  [合并] pages={mt['pages']} rows={mt['n_rows']} "
                  f"cols={mt['n_cols']} title={mt['title'][:40]}")
        print(f"  输出: {out_path}")
    print("=" * 60)
    print("全部完成")
