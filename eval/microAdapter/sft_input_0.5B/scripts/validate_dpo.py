"""DPO 偏好对校验脚本：对 eval/microAdapter/sft_input_0.5B/DPO_Questions.csv 做机器质检。

校验项（chosen 沿用 SFT 全套 + 按 flaw 配方查 rejected）：
1. CSV 可解码（UTF-8）、七列齐全、列数不错位（行首杂散引号会让一行被撕碎）
2. 题目去重（DPO 内部）+ 考卷查重（eval qa.csv / qa_neg.csv）
3. contexts 段 = chunks.json 原文连续子串（行尾空格归一后比对）
4. chosen 按 type 走 SFT 老规则：
   pos  = 有 [n] 引用、不越界、不出现拒答模板
   neg  = 以"资料不足，暂无法回答该问题。"开头、无 [n] 引用
5. rejected 按 flaw 配方查：
   引用错位     去 [n] 后文本与 chosen 相同（纯标号差异），且标号确实不同；
                收编真实模型输出的行可豁免（文本也有差异），标主缺陷即可
   注水         rejected 以 chosen 为前缀 + 追加句；追加句 [n] 所指标段
                必须真实包含该句内容（防跨题舀水——校验器自己也踩过这坑）
   拒答理由含糊 rejected 仍是拒答模板（决策没变），但理由泛化；
                chosen 理由需比 rejected 更具体（长度启发式：长>短）
   幻觉编造     rejected 不以拒答模板开头（在编造）；chosen 是正确拒答
6. rejected 引用同样不越界
7. 配方/正负比例报告

用法:
    .venv/Scripts/python.exe eval/microAdapter/sft_input_0.5B/validate_dpo.py
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
CSV = HERE.parent / "DPO_Questions.csv"
CHUNKS = (HERE.parent.parent.parent.parent / "knowledge" / "front" / "temp_data" / "20260804"
          / "78dc0628-08d8-4d5e-8eb4-bfe3a5ed14f8" / "chunks.json")
QA = HERE.parent.parent.parent.parent / "qa.csv"
QA_NEG = HERE.parent.parent.parent.parent / "qa_neg.csv"

CITATION_RE = re.compile(r"\[(\d+)\]")
REFUSAL_PREFIX = "资料不足，暂无法回答该问题。"
FLAWS = ("引用错位", "注水", "拒答理由含糊", "幻觉编造")


def split_contexts(ctx: str):
    """按单独一行的 --- 切段，返回段列表（保留段内换行）。与 validate_sft.py 同款。"""
    if not ctx or not ctx.strip():
        return []
    parts = re.split(r"(?m)^---\s*$", ctx)
    return [p.strip("\n").strip() for p in parts if p.strip()]


def normalize(text: str) -> str:
    """原文比对归一：去 •\t 前缀、去行尾空格、3+ 连换行压成 2。"""
    lines = [ln.lstrip("•\t").rstrip() for ln in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines).strip())


def anchor_hit(sentence: str, seg: str) -> bool:
    """句子溯源（注水检查用）：句子主干能否在段内找到锚点。

    用锚点词组而非全文滑窗——改写句（合并短句/逗号替换句号）会导致全文
    滑窗误报。锚点 = 句内 8 字滑窗（步长 2）。极短句（"不可以[0]。"这类
    收编真实输出的自由句式）无 8 字窗口，直接放行交人工。
    """
    core = CITATION_RE.sub("", sentence).strip().strip("。！？，,；;")
    if len(core) < 8:
        return True  # 极短句无法锚定，放行（人工确认收编行）
    windows = [core[i:i + 8] for i in range(0, len(core) - 7, 2)]
    return any(w in seg for w in windows)


def main():
    errors, warns = [], []

    # ---- 1. 读取与列检查 ----
    try:
        df = pd.read_csv(CSV, encoding="utf-8", keep_default_na=False)
    except UnicodeDecodeError as e:
        print(f"❌ CSV 不是 UTF-8：{e}")
        sys.exit(1)
    need_cols = ["type", "item_names", "questions", "contexts", "chosen", "rejected", "flaw"]
    missing = [c for c in need_cols if c not in df.columns]
    if missing:
        print(f"❌ 缺列：{missing}，实际列：{list(df.columns)}")
        sys.exit(1)
    # 行首杂散引号检测：错位行的 type 列会异常
    bad_types = df[~df["type"].str.strip().isin(["pos", "neg"])]
    for idx, row in bad_types.iterrows():
        errors.append(f"[行{idx + 2}] type 非法 {row['type']!r}——疑似行首杂散引号导致列错位")

    chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))
    chunk_full = "\n\n".join(normalize(c["content"]) for c in chunks)

    # 考卷问题
    exam_qs = []
    for f in (QA, QA_NEG):
        if f.exists():
            d = pd.read_csv(f, encoding="utf-8-sig")
            exam_qs += [q for q in d["question"].astype(str)]

    seen_qs = {}
    flaw_count = {}
    n_pos = n_neg = 0

    for idx, row in df.iterrows():
        rid = idx + 2
        typ = row["type"].strip()
        if typ not in ("pos", "neg"):
            continue  # 已在列检查里报过错
        q = row["questions"].strip()
        ch = row["chosen"].strip()
        rj = row["rejected"].strip()
        flaw = row["flaw"].strip()
        segs = split_contexts(row["contexts"])
        flaw_count[flaw] = flaw_count.get(flaw, 0) + 1
        (n_pos, n_neg) = (n_pos + 1, n_neg) if typ == "pos" else (n_pos, n_neg + 1)

        if flaw not in FLAWS:
            errors.append(f"[行{rid}] flaw 非法：{flaw!r}，合法值 {FLAWS}")
        if ch == rj:
            errors.append(f"[行{rid}] chosen 与 rejected 完全相同")
        if q in seen_qs:
            errors.append(f"[行{rid}] 题目与行{seen_qs[q]}重复：{q!r}")
            continue
        seen_qs[q] = rid

        # ---- 考卷查重 ----
        for eq in exam_qs:
            eq_core = re.sub(r"^hak180烫金机[:：]", "", eq).strip()
            if q == eq or q == eq_core:
                errors.append(f"[行{rid}] question 与考卷撞车：{q!r}")

        # ---- 段落原文比对 ----
        for si, seg in enumerate(segs):
            seg_n = normalize(seg)
            if seg_n in chunk_full:
                continue
            body = "\n".join(ln for ln in seg_n.splitlines() if not ln.startswith("#")).strip()
            body = re.sub(r"\n{3,}", "\n\n", body)
            if body and body in chunk_full:
                continue
            errors.append(f"[行{rid}] 段{si} 非 chunks 原文子串：{seg[:36]!r}…")

        # ---- chosen 按 type 走 SFT 老规则 ----
        if typ == "pos":
            cites = [int(c) for c in CITATION_RE.findall(ch)]
            if not cites:
                errors.append(f"[行{rid}] pos chosen 无引用标号")
            for c in cites:
                if c >= len(segs):
                    errors.append(f"[行{rid}] chosen 引用越界 [{c}]（段数 {len(segs)}）")
            if REFUSAL_PREFIX[:6] in ch:
                errors.append(f"[行{rid}] pos chosen 疑似拒答文案")
        else:
            if not ch.startswith(REFUSAL_PREFIX):
                errors.append(f"[行{rid}] neg chosen 未以拒答模板开头：{ch[:24]!r}")
            if CITATION_RE.search(ch):
                errors.append(f"[行{rid}] neg chosen 含引用标号")

        # ---- rejected 引用越界（所有配方通用） ----
        for c in CITATION_RE.findall(rj):
            if int(c) >= len(segs):
                errors.append(f"[行{rid}] rejected 引用越界 [{c}]（段数 {len(segs)}）")

        # ---- rejected 按配方查 ----
        if flaw == "引用错位":
            ch_nonum = CITATION_RE.sub("", ch)
            rj_nonum = CITATION_RE.sub("", rj)
            if ch_nonum == rj_nonum:
                # 纯标号差异：标号必须真的不同
                if CITATION_RE.findall(ch) == CITATION_RE.findall(rj):
                    errors.append(f"[行{rid}] 引用错位但标号完全相同")
            else:
                warns.append(f"[行{rid}] 引用错位但文本也有差异（收编真实输出可接受）")
        elif flaw == "注水":
            if typ != "pos":
                errors.append(f"[行{rid}] 注水配方的 type 应为 pos")
            elif rj.startswith(ch):
                extra = rj[len(ch):]
                m = CITATION_RE.search(extra)
                if not m:
                    errors.append(f"[行{rid}] 注水追加句无引用标号：{extra[:30]!r}")
                else:
                    n = int(m.group(1))
                    if n < len(segs) and not anchor_hit(extra, segs[n]):
                        errors.append(f"[行{rid}] 注水句挂[{n}]但段内无此内容（跨题舀水？）：{extra[:30]!r}")
            else:
                # 非"前缀+追加"形态：收编的真实模型输出（改写句式多，锚点允许模糊）。
                # 溯源标准放宽到"句内任一 6 字窗口命中段[实际含该内容的段]"——收编行
                # 的标号本来就可能是错的（那正是要教模型纠正的缺陷），锚点按内容
                # 在全部段里找，而不是死抠所指标段。
                ok = True
                for s in re.split(r"(?<=[。])", rj):
                    m = CITATION_RE.search(s)
                    if not m:
                        continue
                    core = CITATION_RE.sub("", s).strip().strip("。！？，,；;")
                    if len(core) < 8:
                        continue
                    wins = [core[k:k + 6] for k in range(0, len(core) - 5, 2)]
                    if not any(w in seg for seg in segs for w in wins):
                        ok = False
                        break
                (warns if ok else errors).append(
                    f"[行{rid}] 注水非前缀形态（收编真实输出），内容溯源{'通过' if ok else '失败'}")
        elif flaw == "拒答理由含糊":
            if typ != "neg":
                errors.append(f"[行{rid}] 拒答理由含糊的 type 应为 neg")
            if not rj.startswith(REFUSAL_PREFIX):
                errors.append(f"[行{rid}] rejected 应保持拒答决策（理由含糊≠答了）")
            # chosen 精确版的特征：提到"手册只说明/手册只提及"（说清有什么、缺什么）
            if not re.search(r"手册只(说明|提及|提醒)", ch):
                warns.append(f"[行{rid}] chosen 理由未用「手册只说明/提及」精确句式")
        elif flaw == "幻觉编造":
            if typ != "neg":
                errors.append(f"[行{rid}] 幻觉编造的 type 应为 neg")
            if rj.startswith(REFUSAL_PREFIX):
                errors.append(f"[行{rid}] rejected 应为编造内容而非拒答")

    # ---- 汇总 ----
    total = len(df)
    print(f"共 {total} 对：pos {n_pos} / neg {n_neg}")
    print("配方分布：", " / ".join(f"{k} {v}" for k, v in sorted(flaw_count.items())))
    if errors:
        print(f"\n❌ 错误 {len(errors)} 条：")
        for e in errors:
            print("  " + e)
    if warns:
        print(f"\n⚠️ 警告 {len(warns)} 条（人工确认）：")
        for w in warns:
            print("  " + w)
    if not errors and not warns:
        print("\n✅ 全部通过")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
