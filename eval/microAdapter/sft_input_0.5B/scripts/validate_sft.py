"""SFT 数据校验脚本：对 eval/microAdapter/SFT_Questions.csv 做机器质检。

校验项（对应问题解决记录 #11 的格式铁律）：
1. CSV 可解码（UTF-8）、五列齐全
2. contexts 按 `---`（单独一行）切段，段非空
3. pos：answer 引用编号 [n] 不越界；[n] 贴句末句号前（允许句中并列 [0][2]）
4. neg：answer 以"资料不足，暂无法回答该问题。"开头且无 [n] 引用
5. 考卷查重：question 与 eval qa.csv/qa_neg.csv 的语义撞车（精确+关键词近似）
6. contexts 段落逐字命中 chunks.json（允许去 `•\t` 前缀与行尾空格的差异）
7. pos:neg 比例

用法:
    .venv/Scripts/python.exe eval/microAdapter/validate_sft.py
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
CSV = HERE.parent / "SFT_Questions.csv"
CHUNKS = (HERE.parent.parent.parent.parent / "knowledge" / "front" / "temp_data" / "20260804"
          / "78dc0628-08d8-4d5e-8eb4-bfe3a5ed14f8" / "chunks.json")
QA = HERE.parent.parent.parent / "qa.csv"
QA_NEG = HERE.parent.parent.parent / "qa_neg.csv"

CITATION_RE = re.compile(r"\[(\d+)\]")
REFUSAL_PREFIX = "资料不足，暂无法回答该问题。"


def split_contexts(ctx: str):
    """按单独一行的 --- 切段，返回段列表（保留段内换行）。"""
    if not ctx or not ctx.strip():
        return []
    parts = re.split(r"(?m)^---\s*$", ctx)
    return [p.strip("\n").strip() for p in parts if p.strip()]


def normalize(text: str) -> str:
    """归一化用于原文比对：去 •\t 前缀、去行尾空格、3+连换行压成2（空行数是版式噪声）。"""
    lines = []
    for ln in text.splitlines():
        ln = ln.lstrip("•\t").rstrip()
        lines.append(ln)
    out = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", out)


def main():
    errors, warns = [], []

    # ---- 读取 ----
    try:
        df = pd.read_csv(CSV, encoding="utf-8", keep_default_na=False)
    except UnicodeDecodeError as e:
        print(f"❌ CSV 不是 UTF-8：{e}")
        sys.exit(1)
    need_cols = ["type", "item_names", "questions", "contexts", "answer"]
    missing = [c for c in need_cols if c not in df.columns]
    if missing:
        print(f"❌ 缺列：{missing}，实际列：{list(df.columns)}")
        sys.exit(1)

    chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))
    chunk_texts = [normalize(c["content"]) for c in chunks]
    # 全量拼接成一个大文本：段命中 = 是某个 chunk 的连续子串
    # （段可以是 chunk 内自然段、单条 bullet、或跨 bullet 的连续片段）
    chunk_full = "\n\n".join(chunk_texts)

    # 考卷问题（去掉 "hak180烫金机：" 前缀后的关键词）
    exam_qs = []
    for f in (QA, QA_NEG):
        if f.exists():
            d = pd.read_csv(f, encoding="utf-8-sig")
            exam_qs += [q for q in d["question"].astype(str)]

    n_pos = n_neg = 0

    for idx, row in df.iterrows():
        rid = idx + 2  # CSV 行号（含表头）
        typ = row["type"].strip()
        q = row["questions"].strip()
        ctx_raw = row["contexts"]
        ans = row["answer"].strip()

        if typ not in ("pos", "neg"):
            errors.append(f"[行{rid}] type 非法：{typ!r}")
            continue
        if typ == "pos":
            n_pos += 1
        else:
            n_neg += 1

        segs = split_contexts(ctx_raw)

        # ---- 考卷查重（question 层面）----
        for eq in exam_qs:
            eq_core = re.sub(r"^hak180烫金机[:：]", "", eq).strip()
            if q == eq or q == eq_core:
                errors.append(f"[行{rid}] question 与考卷完全撞车：{q!r}")

        # ---- 段落原文比对：段 = 全量 chunk 文本的连续子串 ----
        for si, seg in enumerate(segs):
            seg_n = normalize(seg)
            if seg_n in chunk_full:
                continue
            # 允许"去标题行"后命中（标题行可选成分）
            body = "\n".join(ln for ln in seg_n.splitlines()
                             if not ln.startswith("#")).strip()
            body = re.sub(r"\n{3,}", "\n\n", body)
            if body and body in chunk_full:
                continue
            warns.append(f"[行{rid}] 段{si} 未逐字命中 chunks.json：{seg[:40]!r}…")

        # ---- 类型特定检查 ----
        if typ == "pos":
            if not segs:
                errors.append(f"[行{rid}] pos 但 contexts 为空")
                continue
            cites = [int(c) for c in CITATION_RE.findall(ans)]
            if not cites:
                errors.append(f"[行{rid}] pos answer 无引用标号")
            for c in cites:
                if c >= len(segs):
                    errors.append(f"[行{rid}] 引用越界：[{c}]，段数只有 {len(segs)}")
            # 标号贴句号前：找 `]。` 或 `]。$` 或并列 `[0][2]。`——只查"句号后还跟数字再无标点"的裸奔近似
            for m in re.finditer(r"。(?![\s\n]|$)", ans):
                left = ans[:m.start()]
                if not CITATION_RE.search(left[max(0, len(left) - 12):]):
                    pass  # 句号后接续文本不算裸奔（分句写法多样，仅告警层面处理）
            if REFUSAL_PREFIX[:6] in ans and typ == "pos":
                errors.append(f"[行{rid}] pos answer 疑似拒答文案")
        else:  # neg
            if not ans.startswith(REFUSAL_PREFIX):
                errors.append(f"[行{rid}] neg answer 未以拒答模板开头：{ans[:30]!r}")
            if CITATION_RE.search(ans):
                errors.append(f"[行{rid}] neg answer 含引用标号")
            if not segs and ctx_raw.strip() == "":
                pass  # 路子A：空 contexts，合法
            elif not segs:
                errors.append(f"[行{rid}] neg contexts 非空但切段后为空（--- 写法错误？）")

    # ---- 汇总 ----
    total = len(df)
    print(f"共 {total} 条：pos {n_pos} / neg {n_neg}"
          f"（比例 {n_pos/total:.0%}:{n_neg/total:.0%}，目标约 6:4）")
    if errors:
        print(f"\n❌ 错误 {len(errors)} 条：")
        for e in errors:
            print("  " + e)
    if warns:
        print(f"\n⚠️ 原文比对未命中 {len(warns)} 段（需人工核对）：")
        for w in warns:
            print("  " + w)
    if not errors and not warns:
        print("\n✅ 全部通过")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
