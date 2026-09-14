### Lumy 链路B-步骤2 LLM 区域标注节点

"""
对 pdf_table_extract 产出的逐页摘要做区域划分（Selector Guide / 订购表 /
命名规则 / EC 表 / 封装附录...），为型号提取引擎提供"哪里有什么"的定位。

设计要点（层级保障第 1 层）：
  - 提取引擎之后只消费带 role 标签的区域，不扫原始页面
  - 正则锚点先行（高确定性关键词直接命中），LLM 负责补全与划界
  - LLM 结果与锚点冲突时以锚点为准，缺失的锚点强制补入
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from langchain_core.messages import SystemMessage, HumanMessage

from knowledge.processor.import_process.base import BaseNode
from knowledge.processor.import_process.state import ImportGraphState
from knowledge.prompts.upload.region_label_prompt import (
    REGION_LABEL_SYSTEM_PROMPT, REGION_LABEL_USER_TEMPLATE,
)
from knowledge.utils.llm_client_util import get_llm_client
from knowledge.utils.retry_util import retry_on_rate_limit


# ==================== 确定性锚点：关键词 → (type, role) ====================
# 命中页面文本或表格标题即成立，优先级高于 LLM 判断
ANCHOR_RULES: List[Dict[str, Any]] = [
    {"keyword": "selector guide", "type": "selector_guide", "role": "model_source"},
    {"keyword": "device comparison table", "type": "comparison", "role": "model_source"},
    {"keyword": "device nomenclature", "type": "nomenclature", "role": "model_source"},
    {"keyword": "ordering information", "type": "ordering_info", "role": "opn_source"},
    {"keyword": "order information", "type": "ordering_info", "role": "opn_source"},
    {"keyword": "package option addendum", "type": "package_addendum", "role": "opn_source"},
    {"keyword": "packaging information", "type": "package_addendum", "role": "opn_source"},
    {"keyword": "electrical characteristics", "type": "ec_table", "role": "param_source"},
    {"keyword": "technical specifications", "type": "ec_table", "role": "param_source"},
    {"keyword": "table of contents", "type": "toc", "role": "noise"},
]

TYPE_TO_ROLE = {
    "selector_guide": "model_source", "comparison": "model_source",
    "nomenclature": "model_source", "ordering_info": "opn_source",
    "package_addendum": "opn_source", "ec_table": "param_source",
    "features": "body", "body": "body", "toc": "noise",
}


def build_page_digests(pdf_data: Dict[str, Any],
                       text_head_chars: int = 160) -> str:
    """把 pdf_tables.json 压成 LLM 可读的逐页摘要"""
    lines = []
    for page in pdf_data["pages"]:
        parts = [f"[第{page['page_no']}页]"]
        text_head = " ".join((page.get("text") or "").split())[:text_head_chars]
        if text_head:
            parts.append(f"文本:{text_head}")
        for t in page.get("tables", []):
            first_row = " | ".join(c[:12] for c in t["rows"][0][:6]) if t["rows"] else ""
            parts.append(f"表格《{t['title'][:30]}》{t['n_rows']}x{t['n_cols']} 首行: {first_row}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def _is_toc_page(page_text: str) -> bool:
    """目录页判定：出现 3 处以上点线引导符（....16）"""
    return len(re.findall(r"\.{4,}\s*\d+", page_text)) >= 3


def _clean_cross_refs(page_text: str, keyword: str) -> str:
    """从页面文本中剔除交叉引用与目录条目，避免误报锚点

    - "See the Ordering Information table for..." → 交叉引用，非区域标题
    - "Selector Guide..........16" → 目录条目
    """
    text = re.sub(rf"(?i)see\s+(?:the\s+)?[^\n.]*{re.escape(keyword)}",
                  " ", page_text)
    text = re.sub(rf"(?i){re.escape(keyword)}[\s.]*\.{3,}\s*\d+", " ", text)
    return text


def find_anchors(pdf_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """确定性锚点

    强锚点：关键词出现在表格标题或表格首行（区域标题就贴着表格）
    弱锚点：关键词出现在页面文本头部 300 字符内（章节标题在页首），
            且该页不是目录页、已剔除交叉引用
    同页同类型强锚点优先，弱锚点去重。
    """
    anchors = []
    for page in pdf_data["pages"]:
        page_no = page["page_no"]
        page_text = (page.get("text") or "")

        strong_hits, weak_hits = set(), set()
        for t in page.get("tables", []):
            # 表格标题 + 表格首行（有的规格书标题写在表格第一行内）
            table_haystack = " ".join(
                [(t.get("title") or ""), *[c for c in t["rows"][0][:8]]]
            ).lower() if t.get("rows") else (t.get("title") or "").lower()
            for rule in ANCHOR_RULES:
                if rule["keyword"] in table_haystack:
                    strong_hits.add(rule["keyword"])

        if not _is_toc_page(page_text):
            head = " ".join(page_text[:300].split()).lower()
            for rule in ANCHOR_RULES:
                kw = rule["keyword"]
                cleaned = _clean_cross_refs(head, kw)
                if kw in cleaned:
                    weak_hits.add(kw)

        for kw in strong_hits | (weak_hits - strong_hits):
            rule = next(r for r in ANCHOR_RULES if r["keyword"] == kw)
            anchors.append({
                "page": page_no,
                "type": rule["type"],
                "role": rule["role"],
                "keyword": kw,
                "strength": "strong" if kw in strong_hits else "weak",
            })
    return anchors


def call_llm_label(file_name: str, page_count: int,
                   page_digests: str) -> List[Dict[str, Any]]:
    """调用 LLM 做区域划分，返回 regions 列表"""
    llm = get_llm_client(response_format=True)
    messages = [
        SystemMessage(content=REGION_LABEL_SYSTEM_PROMPT),
        HumanMessage(content=REGION_LABEL_USER_TEMPLATE.format(
            file_name=file_name, page_count=page_count,
            page_digests=page_digests,
        )),
    ]

    @retry_on_rate_limit(max_retries=3, initial_delay=1.0)
    def _invoke():
        return llm.invoke(messages)

    resp = _invoke()
    content = resp.content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    data = json.loads(content)
    regions = data.get("regions", [])

    # 规范化：页码钳制到合法范围，role 按 type 映射兜底
    for r in regions:
        r["page_start"] = max(1, min(int(r.get("page_start", 1)), page_count))
        r["page_end"] = max(r["page_start"],
                            min(int(r.get("page_end", r["page_start"])), page_count))
        r["role"] = TYPE_TO_ROLE.get(r.get("type", "body"), "body")
    return regions


def merge_anchor_overrides(regions: List[Dict[str, Any]],
                           anchors: List[Dict[str, Any]],
                           page_count: int) -> List[Dict[str, Any]]:
    """锚点纠偏：LLM 区域里 type 与锚点冲突的页，拆出锚点单页区域

    简化策略：每个锚点页确保存在同 type 的区域覆盖它；没有则插入
    单页区域（后续提取按页消费，允许区域轻微重叠）。
    """
    def page_type_map(regs):
        mapping = {}
        for r in regs:
            for p in range(r["page_start"], r["page_end"] + 1):
                mapping.setdefault(p, r["type"])
        return mapping

    current = page_type_map(regions)
    additions = []
    for a in anchors:
        if current.get(a["page"]) != a["type"]:
            additions.append({
                "type": a["type"], "title": f"[anchor:{a['keyword']}]",
                "page_start": a["page"], "page_end": a["page"],
                "role": a["role"],
            })
            current[a["page"]] = a["type"]
    regions.extend(additions)
    regions.sort(key=lambda r: (r["page_start"], r["page_end"]))
    return regions


# ==================== LangGraph 节点封装 ====================

class RegionLabelNode(BaseNode):
    """链路B 节点：逐页摘要 → 区域划分 regions.json"""
    name = "region_label"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        pdf_tables_path = state.get("pdf_tables_path")
        if not pdf_tables_path:
            raise ValueError("pdf_tables_path 为空（请先运行 pdf_table_extract）")
        with open(pdf_tables_path, encoding="utf-8") as f:
            pdf_data = json.load(f)

        # 1. 确定性锚点
        anchors = find_anchors(pdf_data)
        self.log_step("step1", f"锚点命中 {len(anchors)} 处")

        # 2. LLM 区域划分
        digests = build_page_digests(pdf_data)
        regions = call_llm_label(pdf_data["file_name"],
                                 pdf_data["page_count"], digests)
        self.log_step("step2", f"LLM 划分 {len(regions)} 个区域")

        # 3. 锚点纠偏
        regions = merge_anchor_overrides(regions, anchors,
                                         pdf_data["page_count"])

        result = {
            "file_name": pdf_data["file_name"],
            "page_count": pdf_data["page_count"],
            "regions": regions,
            "anchors": anchors,
        }
        out_path = Path(pdf_tables_path).parent / "regions.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        self.log_step("step3", f"区域标注完成 → {out_path}")

        state["regions_path"] = str(out_path)
        return state


# ==================== 独立运行入口（5 份 PDF 批量标注 + 验证摘要） ====================

if __name__ == "__main__":
    import sys
    from knowledge.processor.import_process.base import setup_logging

    setup_logging()
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("referencePDF/lumy_extract")

    for tables_json in sorted(root.glob("*/pdf_tables.json")):
        print("=" * 60)
        state = {"pdf_tables_path": str(tables_json)}
        node = RegionLabelNode()
        try:
            state = node(state)
        except Exception as e:
            print(f"[FAIL] {tables_json.parent.name}: {e}")
            continue
        with open(state["regions_path"], encoding="utf-8") as f:
            result = json.load(f)
        print(f"{result['file_name']}:")
        for r in result["regions"]:
            print(f"  p{r['page_start']}-{r['page_end']} {r['type']:<18} "
                  f"{r['role']:<13} {r['title'][:36]}")
        print(f"  锚点: {[(a['page'], a['type']) for a in result['anchors']]}")
    print("=" * 60)
    print("全部完成")
