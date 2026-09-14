### Lumy 链路B-步骤3 型号提取引擎（四层定义落地）

"""
职责：从区域标注后的解析数据中提取 家族/PPN/OPN/命名规则，产出 models.json。

分层策略（层级保障第 2/3/4 层）：
  1. 规则枚举（确定性）：Selector Guide 逐行、对比表表头/分节、附录 Orderable part 列、
     EC 表节标题——型号字符串只从这些结构化位置产生，不做全文正则扫描。
  2. LLM 语义层：四层判定（功能位/订购位分类）、命名规则文法解码、异常 OPN 家族归属。
  3. 反规则过滤 + 封面交叉校验 + LLM 复核，三层保障无封装名/图号/文档编号误提。
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

from knowledge.processor.import_process.base import BaseNode
from knowledge.processor.import_process.state import ImportGraphState
from knowledge.prompts.upload.model_extract_prompt import (
    MODEL_EXTRACT_SYSTEM_PROMPT, MODEL_EXTRACT_USER_TEMPLATE,
    OPN_ATTR_SYSTEM_PROMPT, OPN_ATTR_USER_TEMPLATE,
)
from knowledge.utils.retry_util import retry_on_rate_limit

# 显式加载 knowledge/.env（本文件位于 knowledge/processor/import_process/nodes/ 下）
load_dotenv(Path(__file__).resolve().parents[3] / ".env")


def get_llm_long(response_format: bool = True, timeout: float = 180.0):
    """提取引擎专用 LLM 客户端：生成大 JSON 需要长超时

    不复用 llm_client_util（其 30s 超时适合交互查询，不适合批量提取）。
    """
    model_kwargs = {}
    if response_format:
        model_kwargs["response_format"] = {"type": "json_object"}
    return ChatOpenAI(
        model=os.getenv("ITEM_MODEL"),
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_API_BASE"),
        temperature=0.0,
        extra_body={"enable_thinking": False},
        model_kwargs=model_kwargs,
        timeout=timeout,
        request_timeout=timeout,
    )


# ==================== 反规则黑名单 ====================

# 文档编号：SLVS044Z / SLOS068AB / SLVS543S ...
DOCNUM_RE = re.compile(r"^(?:SL|LU|SB|SN|SBO)[A-Z]{1,4}\d{2,}[A-Z]*$")
# 封装名称（含带引脚数后缀）
PACKAGE_RE = re.compile(
    r"^(?:SOT-?\d+|SOIC|TSSOP|VSSOP|PDIP|CDIP|LCCC|SO|SOP|MSOP|SC70|SC-70|"
    r"WLP|QFN|TQFN|LQFN|DFN|LGA|BGA|DSBGA|SMA|SMB|TO-?\d+|FK|JG|NDE|KCT|"
    r"DCY|DBV|DBZ|DCK|PK|PS|P|D)(?:[- ( (]|$)", re.IGNORECASE)
# 图号/表号
FIGREF_RE = re.compile(r"^(?:Figure|Fig\.?|Table)\s", re.IGNORECASE)
# 认证/标准编号：AEC-Q200 / MIL-PRF-38535 / MIL-STD-883 ...
STDNUM_RE = re.compile(r"^(?:AEC-?Q\d+|MIL-(?:PRF|STD)-?\d+|JESD\d+|IEC\d+|EN\d+)$",
                       re.IGNORECASE)
# 纯噪声词
NOISE_WORDS = {
    "PART", "PARTS", "PACKAGE", "TYPE", "SIZE", "CODE", "QUANTITY", "STATUS",
    "ACTIVE", "OBSOLETE", "PRODUCTION", "DESCRIPTION", "SPECIFICATION",
    "SPECIFICATIONS", "FEATURES", "APPLICATIONS", "VISHAY", "TI", "MAXIM",
    "ANALOG", "DEVICES", "INCORPORATED", "TEXAS", "INSTRUMENTS", "ROHS",
    "TUBE", "TR", "RT1", "RT7", "RF", "R82", "E24", "E96", "G3", "G4", "E3", "E4",
}
# 型号 token 形状：字母开头≥3位大写字母数字（允许 - / # + . ）或军品号 5962-xxxx
MODEL_TOKEN_RE = re.compile(
    r"^(?:[A-Z][A-Z0-9]{2,}[A-Z0-9/#+.\-]*|\d{4}-\d{5,}[A-Z0-9]*)$")


def is_model_token(tok: str) -> bool:
    """候选型号 token 的形状 + 反规则过滤"""
    tok = tok.strip()
    if not tok or len(tok) < 3 or len(tok) > 30:
        return False
    if not MODEL_TOKEN_RE.match(tok):
        return False
    if (DOCNUM_RE.match(tok) or PACKAGE_RE.match(tok) or FIGREF_RE.match(tok)
            or STDNUM_RE.match(tok)):
        return False
    if tok in NOISE_WORDS:
        return False
    # 至少含一个数字（纯字母缩写多为噪声）
    if not any(c.isdigit() for c in tok):
        return False
    return True


def strip_footnotes(tok: str) -> str:
    """去掉型号尾部脚注符号（**、†、‡、(1) 这类组）——绝不能剥数字

    注意：字符类里若混入裸数字，会把 CRCW0402 剥成 CRCW040、DCYG3 剥成 DCYG。
    """
    return re.sub(r"(?:[*†‡]|\(\d\))+$", "", tok.strip())


def is_standalone_in(tok: str, corpus: str) -> bool:
    """源文锚定：token 必须作为独立词出现（不能是更长 token 的子串）

    防两类问题：LLM 幻觉（原文没有）与截断误报（'TL4' 只存在于 'TL431' 内部）。
    """
    return re.search(
        rf"(?<![A-Z0-9/#+.\-]){re.escape(tok)}(?![A-Z0-9])", corpus) is not None


# ==================== 区域载荷构建 ====================

def load_regions(regions_path: str) -> List[Dict[str, Any]]:
    with open(regions_path, encoding="utf-8") as f:
        return json.load(f)["regions"]


def pages_of_type(pdf_data: Dict, regions: List[Dict], rtype: str) -> List[int]:
    pages = []
    for r in regions:
        if r.get("type") == rtype:
            pages.extend(range(r["page_start"], r["page_end"] + 1))
    return sorted(set(p for p in pages if 1 <= p <= pdf_data["page_count"]))


def get_tables_on_pages(pdf_data: Dict, pages: List[int]) -> List[Dict]:
    by_page = {p["page_no"]: p for p in pdf_data["pages"]}
    out = []
    for pno in pages:
        page = by_page.get(pno)
        if page:
            for t in page.get("tables", []):
                t = dict(t)
                t["page_no"] = pno
                out.append(t)
    return out


def get_text_on_pages(pdf_data: Dict, pages: List[int]) -> str:
    by_page = {p["page_no"]: p for p in pdf_data["pages"]}
    parts = []
    for pno in pages:
        page = by_page.get(pno)
        if page and page.get("text"):
            parts.append(f"[第{pno}页] {page['text']}")
    return "\n".join(parts)


def serialize_table(t: Dict, max_rows: int = 60) -> str:
    rows = t["rows"][:max_rows]
    body = "\n".join(" | ".join(r) for r in rows)
    more = f"\n...（共{t['n_rows']}行，已截断）" if t["n_rows"] > max_rows else ""
    return f"第{t['page_no']}页 表《{t['title'][:40]}》{t['n_rows']}x{t['n_cols']}：\n{body}{more}"


# ==================== 规则枚举：各来源提取器 ====================

def is_family_group_row(row: List[str]) -> Optional[str]:
    """家族分组行：≥2 个非空单元格且全部相同（横向合并填充后的特征）"""
    non_empty = [c for c in row if c]
    if len(non_empty) >= 2 and len(set(non_empty)) == 1:
        tok = strip_footnotes(non_empty[0])
        if is_model_token(tok):
            return tok
    return None


def extract_from_selector(tables: List[Dict]) -> Dict[str, Any]:
    """Selector Guide 表：分组行=家族，型号行=OPN/PPN（含参数行）

    适用于逐条列出完整型号字符串的表（如 MAX20029）。
    """
    families, models = [], []
    for t in tables:
        header = t["rows"][0] if t["rows"] else []
        header_l = " ".join(header).lower()
        if "selector" not in (t.get("title") or "").lower() and "part" not in header_l:
            continue
        current_family = None
        for row in t["rows"][1:]:
            group = is_family_group_row(row)
            if group:
                current_family = group
                families.append({"name": group, "evidence_page": t["page_no"],
                                 "source": "selector_guide"})
                continue
            cand = strip_footnotes(row[0]) if row else ""
            if is_model_token(cand) and cand != current_family:
                models.append({
                    "token": cand,
                    "family": current_family,
                    "page": t["page_no"],
                    "header": header,
                    "row": row,
                })
    return {"families": families, "models": models}


def extract_from_comparison(tables: List[Dict]) -> Dict[str, Any]:
    """对比表：表头单元格 + 单 token 独占单元格 → 家族名（去 Legacy/New 括注）

    单元格可能含多个 token（如表头 'LM358B LM358BA'），按空白拆开逐个判定。
    """
    names = []
    for t in tables:
        title_l = (t.get("title") or "").lower()
        if "comparison" not in title_l and "family" not in title_l:
            continue
        for row in t["rows"]:
            for cell in row:
                # "LM317 (Legacy Chip)" → 取括号前的部分，再按空白拆多 token
                base = re.split(r"[（(]", cell)[0].strip()
                for tok in base.split():
                    tok = strip_footnotes(tok)
                    if (is_model_token(tok) and tok not in names
                            and not re.fullmatch(r"[0-9.]+(?:A|V|Hz|dB|W)?", tok)):
                        names.append(tok)
    return {"families": [n for n in names]}


def extract_ec_section_models(pdf_data: Dict, ec_pages: List[int]) -> List[str]:
    """EC 表节标题中的型号（如 'Electrical Characteristics, TL431C, TL432C'）"""
    text = get_text_on_pages(pdf_data, ec_pages)
    found = []
    for m in re.finditer(
            r"(?:Electrical Characteristics|特性)[,，:\s]*((?:[A-Z][A-Z0-9]{2,}[A-Z0-9]*[,，\s]+){1,6}[A-Z][A-Z0-9]{2,}[A-Z0-9]*)",
            text):
        for tok in re.split(r"[,，\s]+", m.group(1).strip()):
            tok = strip_footnotes(tok)
            if is_model_token(tok) and tok not in found:
                found.append(tok)
    return found


def extract_opns_from_addendum(tables: List[Dict]) -> List[Dict[str, Any]]:
    """附录/订购表：'Orderable part' 列 → OPN 清单（权威枚举，规则完成）"""
    opns = []
    for t in tables:
        header = t["rows"][0] if t["rows"] else []
        header_l = [h.lower() for h in header]
        part_col = next((i for i, h in enumerate(header_l)
                         if "orderable part" in h or h == "part" or h.startswith("part number")
                         or "ordering" in h or h.startswith("part")), None)
        if part_col is None:
            continue
        pkg_col = next((i for i, h in enumerate(header_l) if "package" in h), None)
        qty_col = next((i for i, h in enumerate(header_l) if "qty" in h or "quantity" in h), None)
        for row in t["rows"][1:]:
            if part_col >= len(row):
                continue
            tok = strip_footnotes(row[part_col])
            if not is_model_token(tok):
                continue
            opns.append({
                "opn": tok,
                "package": row[pkg_col] if pkg_col is not None and pkg_col < len(row) else "",
                "packing": row[qty_col] if qty_col is not None and qty_col < len(row) else "",
                "evidence_page": t["page_no"],
                "source": "addendum",
            })
    return opns


def extract_opns_from_ordering_text(tables: List[Dict],
                                    region_text: str) -> List[Dict[str, Any]]:
    """订购区文本/碎片表中的显式 OPN 示例（被动元件：'Part Number: XXX' 形式）"""
    opns = []
    seen = set()
    haystacks = [region_text] + [c for t in tables for r in t["rows"] for c in r]
    for hay in haystacks:
        for m in re.finditer(r"Part\s*Number[:：\s]+([A-Z0-9][A-Z0-9/.\-]{5,})", hay):
            tok = strip_footnotes(m.group(1).strip())
            if is_model_token(tok) and tok not in seen:
                seen.add(tok)
                opns.append({"opn": tok, "package": "", "packing": "",
                             "evidence_page": None, "source": "ordering_text"})
    return opns


# ==================== LLM 语义层 ====================

def _invoke_json(llm, messages) -> Dict[str, Any]:
    @retry_on_rate_limit(max_retries=3, initial_delay=1.0)
    def _invoke():
        return llm.invoke(messages)
    content = _invoke().content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    return json.loads(content)


def llm_extract_semantics(file_name: str, cover_text: str,
                          payload: str) -> Dict[str, Any]:
    """LLM 语义提取：家族/PPN 判定 + 命名规则文法解码"""
    llm = get_llm_long()
    messages = [
        SystemMessage(content=MODEL_EXTRACT_SYSTEM_PROMPT),
        HumanMessage(content=MODEL_EXTRACT_USER_TEMPLATE.format(
            file_name=file_name, cover_text=cover_text[:1500],
            model_region_payload=payload[:28000],
        )),
    ]
    data = _invoke_json(llm, messages)
    for key in ("families", "ppns", "naming_rules"):
        data.setdefault(key, [])
    return data


def llm_assign_unmatched(families: List[str], ppns: List[str],
                         unmatched: List[str]) -> Dict[str, Any]:
    """LLM 归属：前缀匹配失败的 OPN（军品号等）→ 家族"""
    if not unmatched:
        return {"assignments": [], "issues": []}
    llm = get_llm_long()
    messages = [
        SystemMessage(content=OPN_ATTR_SYSTEM_PROMPT),
        HumanMessage(content=OPN_ATTR_USER_TEMPLATE.format(
            families=", ".join(families), ppns=", ".join(ppns[:60]),
            unmatched_opns="\n".join(unmatched[:80]),
        )),
    ]
    return _invoke_json(llm, messages)


def build_corpus(pdf_data: Dict) -> str:
    """全文语料：页面文本 + 所有表格单元格（用于源文锚定校验）"""
    parts = [p.get("text") or "" for p in pdf_data["pages"]]
    for p in pdf_data["pages"]:
        for t in p.get("tables", []):
            for row in t["rows"]:
                parts.extend(row)
    return "\n".join(parts)


def extract_spec_header_families(spec_tables: List[Dict]) -> List[str]:
    """技术规格表表头行 → 家族枚举（被动元件：尺寸系列即家族）

    表格首行通常是横跨的 'TECHNICAL SPECIFICATIONS'，第二行是
    DESCRIPTION | D10/CRCW0402 | D11/CRCW0603 | ... 尺寸列头。
    """
    names = []
    for t in spec_tables:
        for row in t["rows"][:2]:
            for cell in row:
                for tok in cell.split():
                    tok = strip_footnotes(tok)
                    if is_model_token(tok) and tok not in names:
                        names.append(tok)
    return names


# ==================== 合并、附着与校验 ====================

def attach_opn(opn: str, families: List[str],
               ppn_index: Dict[str, str]) -> Tuple[Optional[str], Optional[str]]:
    """OPN → (family, ppn) 归属：最长前缀优先，PPN 精确包含优先于家族前缀"""
    best_len, best_family = 0, None
    for fam in families:
        if opn.startswith(fam) and len(fam) > best_len:
            best_len, best_family = len(fam), fam
    # OPN 可能就是某个 PPN（如 degenerate 家族 LM317 本身）
    best_ppn_len, best_ppn = 0, None
    for ppn in ppn_index:
        if opn == ppn and len(ppn) > best_ppn_len:
            best_ppn_len, best_ppn = len(ppn), ppn
        elif opn.startswith(ppn) and len(ppn) > best_ppn_len:
            best_ppn_len, best_ppn = len(ppn), ppn
    if best_ppn:
        return ppn_index.get(best_ppn, best_family), best_ppn
    return best_family, None


def ordering_suffixes(naming_rules: List[Dict]) -> List[str]:
    """从命名规则中收集纯订购后缀（用于从完整型号剥离出 PPN）"""
    suffixes = []
    for rule in naming_rules:
        for pos in rule.get("positions", []):
            if pos.get("kind") == "ordering" and pos.get("segment"):
                seg = pos["segment"].strip()
                if re.fullmatch(r"[/+#.\-]+[A-Z0-9]*", seg) and 1 <= len(seg) <= 6:
                    suffixes.append(seg)
    return suffixes


def strip_ordering(opn: str, suffixes: List[str]) -> str:
    """剥离尾部订购后缀得到 PPN

    两级策略：LLM 解码的后缀表优先（如 '/V+'），
    再用确定性正则兜底（'/XX'、'+XX'、'#XX' 形式的短订购尾缀）——
    LLM 偶发漏报后缀时保证 PPN 层不塌陷。
    """
    for suf in sorted(suffixes, key=len, reverse=True):
        if opn.endswith(suf) and len(opn) - len(suf) >= 4:
            return opn[: -len(suf)]
    stripped = re.sub(r"[/#+][A-Z0-9+]{1,4}$", "", opn)
    if len(stripped) >= 4 and stripped != opn:
        return stripped
    return opn


def cover_check(pdf_data: Dict, families: List[str]) -> Dict[str, Any]:
    """封面交叉校验：封面页的型号 token 应被家族集合覆盖"""
    cover_text = (pdf_data["pages"][0].get("text") or "")
    cover_tokens = {strip_footnotes(t) for t in re.findall(
        r"\b[A-Z][A-Z0-9]{2,}[A-Z0-9/#+.\-]*\b", cover_text)}
    cover_tokens = {t for t in cover_tokens
                    if is_model_token(t) and not DOCNUM_RE.match(t)}
    fam_set = set(families)
    missing = sorted(t for t in cover_tokens
                     if not any(f == t or t.startswith(f) for f in fam_set))
    return {"cover_tokens": sorted(cover_tokens), "uncovered": missing}


# ==================== 主流程 ====================

class ModelExtractNode(BaseNode):
    """链路B 节点：区域数据 → 四层型号数据 models.json"""
    name = "model_extract"

    def process(self, state: ImportGraphState) -> ImportGraphState:
        pdf_tables_path = state.get("pdf_tables_path")
        regions_path = state.get("regions_path")
        with open(pdf_tables_path, encoding="utf-8") as f:
            pdf_data = json.load(f)
        regions = load_regions(regions_path)

        result = self.extract(pdf_data, regions)
        out_path = Path(pdf_tables_path).parent / "models.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        self.log_step("done", f"家族{len(result['families'])} PPN{len(result['ppns'])} "
                              f"OPN{len(result['opns'])} 规则{len(result['naming_rules'])} → {out_path}")
        state["models_path"] = str(out_path)
        return state

    # ---------- 提取主流程 ----------
    def extract(self, pdf_data: Dict, regions: List[Dict]) -> Dict[str, Any]:
        file_name = pdf_data["file_name"]
        corpus = build_corpus(pdf_data)

        # ---- 1. 区域定位 ----
        selector_pages = pages_of_type(pdf_data, regions, "selector_guide")
        comparison_pages = pages_of_type(pdf_data, regions, "comparison")
        nomen_pages = pages_of_type(pdf_data, regions, "nomenclature")
        ordering_pages = pages_of_type(pdf_data, regions, "ordering_info")
        addendum_pages = pages_of_type(pdf_data, regions, "package_addendum")
        ec_pages = pages_of_type(pdf_data, regions, "ec_table")
        # 被动元件：技术规格表也参与家族枚举
        spec_tables = [t for t in get_tables_on_pages(pdf_data, ec_pages)
                       if any("TECHNICAL SPEC" in (r[0] if r else "") for r in t["rows"][:1])]

        selector_tables = get_tables_on_pages(pdf_data, selector_pages)
        comparison_tables = (get_tables_on_pages(pdf_data, comparison_pages)
                             + [t for t in spec_tables])

        # ---- 2. 规则枚举 ----
        sel = extract_from_selector(selector_tables)
        cmp_res = extract_from_comparison(comparison_tables)
        ec_models = extract_ec_section_models(pdf_data, ec_pages)

        # OPN 权威枚举：附录 Orderable part 列
        addendum_tables = get_tables_on_pages(pdf_data, addendum_pages + ordering_pages)
        opns = extract_opns_from_addendum(addendum_tables)
        # Selector Guide 的完整型号串也是 OPN 枚举来源（如 MAX20029ATIA/V+）
        for m in sel["models"]:
            opns.append({"opn": m["token"], "package": "", "packing": "",
                         "evidence_page": m["page"], "source": "selector_guide"})
        # 订购区文本中的显式示例（被动元件：'Part Number: XXX'）
        ordering_tables = get_tables_on_pages(pdf_data, ordering_pages)
        opns.extend(extract_opns_from_ordering_text(
            ordering_tables, get_text_on_pages(pdf_data, ordering_pages)))

        # ---- 3. LLM 语义层 ----
        payload_parts = []
        for t in selector_tables + comparison_tables:
            payload_parts.append(serialize_table(t))
        payload_parts.append("【命名规则区文本】\n" + get_text_on_pages(pdf_data, nomen_pages))
        if ordering_pages:
            payload_parts.append("【订购区表格（含命名规则列）】")
            payload_parts.extend(serialize_table(t, max_rows=12)
                                 for t in ordering_tables)
        if ec_models:
            payload_parts.append("【EC表节标题中出现的型号】\n" + ", ".join(ec_models))
        if addendum_pages:
            payload_parts.append("【附录订购表首屏（参考）】\n" +
                                 serialize_table(addendum_tables[0], max_rows=15)
                                 if addendum_tables else "")
        cover_text = (pdf_data["pages"][0].get("text") or "")
        llm_res = llm_extract_semantics(file_name, cover_text,
                                        "\n\n".join(p for p in payload_parts if p))

        # ---- 4. 合并家族（含源文锚定校验：token 必须在原文出现） ----
        families: List[Dict] = []
        seen_family = set()

        def add_family(name, ftype="normal", notes="", page=None):
            if (name and name not in seen_family and is_model_token(name)
                    and is_standalone_in(name, corpus)):
                seen_family.add(name)
                families.append({"family_name": name, "family_type": ftype,
                                 "notes": notes, "evidence_page": page})
            elif name and name not in seen_family and is_model_token(name):
                self.logger.warning(f"[锚定过滤] 家族 '{name}' 非原文独立词，丢弃")

        for f in llm_res["families"]:
            add_family(f.get("name"), f.get("type", "normal"),
                       f.get("notes", ""), f.get("evidence_page"))
        for f in sel["families"]:
            add_family(f["name"], page=f["evidence_page"])
        for name in cmp_res["families"]:
            add_family(name)
        for name in extract_spec_header_families(spec_tables):
            add_family(name, ftype="wildcard", notes="被动元件尺寸系列")
        family_names = [f["family_name"] for f in families]

        # ---- 5. PPN 层 ----
        ppns: List[Dict] = []
        seen_ppn = set()

        def add_ppn(ppn, family, attributes, page, evidence):
            if ppn and ppn not in seen_ppn and is_model_token(ppn):
                if not is_standalone_in(ppn, corpus):
                    self.logger.warning(f"[锚定过滤] PPN '{ppn}' 非原文独立词，丢弃")
                    return
                seen_ppn.add(ppn)
                ppns.append({"ppn": ppn, "family": family,
                             "attributes": attributes or {},
                             "evidence_page": page, "evidence": evidence[:200]})

        # 5.1 LLM 判定的 PPN
        for p in llm_res["ppns"]:
            add_ppn(p.get("ppn"), p.get("family"), p.get("attributes"),
                    p.get("evidence_page"), p.get("evidence", ""))
        # 5.2 Selector 行 → 完整型号剥离订购后缀得 PPN
        suffixes = ordering_suffixes(llm_res["naming_rules"])
        header_map = {m["token"]: m for m in sel["models"]}
        for m in sel["models"]:
            ppn = strip_ordering(m["token"], suffixes)
            attrs = {}
            if m["header"] and len(m["header"]) == len(m["row"]):
                attrs = {h: v for h, v in zip(m["header"][1:], m["row"][1:]) if v}
            add_ppn(ppn, m["family"] or "", attrs, m["page"],
                    " | ".join(m["row"][:8]))
        # 5.3 对比表家族 → 单 PPN 退化（家族即 PPN）
        for name in cmp_res["families"]:
            add_ppn(name, name, {}, None, "comparison-family")
        # 5.4 EC 节标题型号（tl431 档位组合）
        for tok in ec_models:
            fam = next((f for f in family_names if tok.startswith(f)), "")
            add_ppn(tok, fam, {}, None, "EC-section")

        ppn_index = {p["ppn"]: p["family"] for p in ppns}

        # 5.5 孤儿 PPN 家族派生：家族缺失时按"去掉尾部1-2个字母档位码"归并基名
        #     （如 TL431AC/TL431I/... → 家族 TL431；只处理 family 为空的 PPN，
        #      不触碰已有家族归属，避免把 LM317A 错并进 LM317）
        orphan_groups: Dict[str, List[Dict]] = {}
        for p in ppns:
            if p["family"] in ("", None):
                base = re.sub(r"[A-Z]{1,2}$", "", p["ppn"])
                if (base and base != p["ppn"] and len(base) >= 4
                        and is_standalone_in(base, corpus)):
                    orphan_groups.setdefault(base, []).append(p)
        for base, group in orphan_groups.items():
            if len(group) >= 2:
                add_family(base, notes=f"由{len(group)}个档位PPN派生")
                for p in group:
                    p["family"] = base
                family_names.append(base)
                ppn_index = {q["ppn"]: q["family"] for q in ppns}
            elif base in seen_family:
                for p in group:
                    p["family"] = base

        # 5.6 PPN 与 OPN 同串去重（完整订购串属于 OPN 层，如 MAX20029ATIA/V+）
        opn_strings = {o["opn"] for o in opns}
        before = len(ppns)
        ppns = [p for p in ppns if p["ppn"] not in opn_strings]
        if before != len(ppns):
            self.logger.info(f"PPN/OPN 同串去重：{before} → {len(ppns)}")

        # 5.7 PPN 家族字段归一：LLM 可能写 'TL43x' 这类通配名，统一映射到家族清单
        for p in ppns:
            if p["family"] not in seen_family:
                p["family"] = next(
                    (f for f in family_names if p["ppn"].startswith(f)), "")
        ppn_index = {p["ppn"]: p["family"] for p in ppns}

        # ---- 6. OPN 附着 ----
        unmatched = []
        out_opns: List[Dict] = []
        seen_opn = set()
        for o in sorted({o["opn"] for o in opns}):
            entry = next(x for x in opns if x["opn"] == o)
            fam, ppn = attach_opn(o, family_names, ppn_index)
            if fam is None:
                unmatched.append(o)
            if o not in seen_opn:
                seen_opn.add(o)
                out_opns.append({"opn": o, "ppn": ppn or "", "family": fam or "",
                                 "package": entry.get("package", ""),
                                 "packing": entry.get("packing", ""),
                                 "evidence_page": entry.get("evidence_page"),
                                 "source": entry.get("source", "")})

        # ---- 7. LLM 归属异常 OPN ----
        issues: List[str] = []
        if unmatched:
            assign = llm_assign_unmatched(family_names,
                                          [p["ppn"] for p in ppns], unmatched)
            amap = {a["opn"]: a.get("family") for a in assign.get("assignments", [])}
            for o in out_opns:
                if o["opn"] in amap:
                    o["family"] = amap[o["opn"]] or ""
                    o["ppn"] = ""
                    o["notes"] = "LLM归属"
            issues.extend(assign.get("issues", []))

        # ---- 8. 封面交叉校验 ----
        cc = cover_check(pdf_data, family_names)
        if cc["uncovered"]:
            issues.append(f"封面 token 未被家族覆盖: {cc['uncovered']}")

        # ---- 9. 命名规则（LLM 解码）----
        naming_rules = []
        for rule in llm_res["naming_rules"]:
            rule["expanded"] = False  # 纪律：只解码不展开
            naming_rules.append(rule)

        return {
            "file_name": file_name,
            "families": families,
            "ppns": ppns,
            "opns": out_opns,
            "naming_rules": naming_rules,
            "cover_check": cc,
            "issues": issues,
        }


# ==================== 独立运行入口（5 份 PDF 批量提取 + 验证摘要） ====================

if __name__ == "__main__":
    import sys
    from knowledge.processor.import_process.base import setup_logging

    setup_logging()
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("referencePDF/lumy_extract")

    for tables_json in sorted(root.glob("*/pdf_tables.json")):
        work_dir = tables_json.parent
        regions_json = work_dir / "regions.json"
        if not regions_json.exists():
            print(f"[SKIP] {work_dir.name}: 缺 regions.json")
            continue
        print("=" * 60)
        print(f"提取: {work_dir.name}")
        state = {"pdf_tables_path": str(tables_json),
                 "regions_path": str(regions_json)}
        node = ModelExtractNode()
        try:
            state = node(state)
        except Exception as e:
            print(f"[FAIL] {e}")
            continue
        with open(state["models_path"], encoding="utf-8") as f:
            r = json.load(f)
        print(f"  家族({len(r['families'])}): {[f['family_name'] for f in r['families']]}")
        print(f"  PPN({len(r['ppns'])}): {[p['ppn'] for p in r['ppns']][:24]}")
        print(f"  OPN({len(r['opns'])}): {[o['opn'] for o in r['opns']][:12]}")
        print(f"  命名规则: {[(n.get('family'), n.get('pattern')) for n in r['naming_rules']]}")
        print(f"  未归属OPN: {[o['opn'] for o in r['opns'] if not o['family']][:10]}")
        print(f"  issues: {r['issues'][:5]}")
    print("=" * 60)
    print("全部完成")
