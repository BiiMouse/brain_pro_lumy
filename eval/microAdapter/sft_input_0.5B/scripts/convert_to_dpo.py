"""CSV → DPO preference 转换：把 DPO_Questions.csv 变成 LLaMA-Factory 偏好训练集。

铁律不变：训练格式 = 推理格式。instruction 构造与 convert_to_alpaca.py 完全同款
（单源加载线上 ANSWER_PROMPT + 段包装 + md5 确定性合成分）——复用 SFT 题目时，
两个数据集里同一题的 instruction 字节相同，模型看到的是同一个 prompt，只是
训练信号从"模仿 output"变成"chosen 比 rejected 更好"。

DPO 数据形态（LLaMA-Factory ranking 数据集）：
- 每条 {instruction, input, chosen, rejected}
- input 留空（与 alpaca 三字段习惯一致，qwen template 下 input 拼在 instruction 后）
- 注册时 dataset_info.json 需标 "ranking": true

score 合成沿用 alpaca 版逻辑：neg top ≥ 0.4 拒答闸门（低于闸门线上到不了 LLM）。

用法（项目根目录下）:
    .venv/Scripts/python.exe eval/microAdapter/sft_input_0.5B/convert_to_dpo.py

产出:
    eval/microAdapter/sft_input_0.5B/dpo_preference.json       偏好训练集
    eval/microAdapter/sft_input_0.5B/dataset_info_dpo.json     LLaMA-Factory 注册片段（含 ranking:true）
上传云端时两个文件都拷到 LLaMA-Factory/data/ 下，合并注册进 dataset_info.json。
"""
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
CSV = HERE.parent / "DPO_Questions.csv"
CHUNKS = (HERE.parent.parent.parent.parent / "knowledge" / "front" / "temp_data" / "20260804"
          / "78dc0628-08d8-4d5e-8eb4-bfe3a5ed14f8" / "chunks.json")
QUERY_PROMPT = HERE.parent.parent.parent.parent / "knowledge" / "prompts" / "query" / "query_prompt.py"
OUT_JSON = HERE.parent / "dpo_preference.json"
OUT_INFO = HERE.parent / "dataset_info_dpo.json"

GATE_THRESHOLD = 0.4  # 生产拒答闸门（config.rag_refuse_threshold 默认 0.4）


def load_answer_prompt() -> str:
    """单源加载线上 ANSWER_PROMPT（与 convert_to_alpaca.py 同款，不复制）。"""
    spec = importlib.util.spec_from_file_location("query_prompt", QUERY_PROMPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ANSWER_PROMPT


def normalize(text: str) -> str:
    lines = [ln.lstrip("•\t").rstrip() for ln in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines).strip())


def split_contexts(ctx: str):
    if not ctx or not ctx.strip():
        return []
    parts = re.split(r"(?m)^---\s*$", ctx)
    return [p.strip("\n").strip() for p in parts if p.strip()]


def find_chunk_title(seg: str, chunks) -> str:
    seg_n = normalize(seg)
    for c in chunks:
        if seg_n in normalize(c["content"]):
            return c.get("title", "")
    return ""


def synth_score(question: str, i: int, base: float, step: float, floor: float) -> float:
    """确定性合成分（md5 种子）——与 convert_to_alpaca.py 字节级同款：
    同一题在 SFT 与 DPO 两个数据集里得到相同分数序列。"""
    h = int(hashlib.md5(f"{question}:{i}".encode("utf-8")).hexdigest()[:8], 16)
    jitter = (h % 40) / 1000.0
    return round(max(floor, base - i * step + jitter), 4)


def wrap_context(segs, question: str, typ: str, chunks) -> str:
    if not segs:
        return "无参考答案"
    if typ == "pos":
        base, step, floor = 0.92, 0.05, 0.55
    else:
        base, step, floor = 0.62, 0.04, 0.45
    docs = []
    for i, seg in enumerate(segs):
        score = synth_score(question, i, base, step, floor)
        if i == 0 and typ == "neg":
            assert score >= GATE_THRESHOLD, f"neg top 分 {score} 低于闸门"
        meta = {"score": score, "url": "", "title": find_chunk_title(seg, chunks)}
        docs.append(f"[{i}]:{meta}\n{seg}")
    return "\n\n".join(docs)


def main():
    df = pd.read_csv(CSV, encoding="utf-8", keep_default_na=False)
    chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))
    prompt_tpl = load_answer_prompt()

    samples = []
    for _, row in df.iterrows():
        typ = row["type"].strip()
        item = row["item_names"].strip()
        q = row["questions"].strip()
        segs = split_contexts(row["contexts"])

        instruction = prompt_tpl.format(
            context=wrap_context(segs, q, typ, chunks),
            history="暂无历史",
            item_names=str([item]),
            question=f"{item}：{q}",
        )
        assert not re.search(r"\{(context|history|item_names|question)\}", instruction), q
        samples.append({
            "instruction": instruction,
            "input": "",
            "chosen": row["chosen"].strip(),
            "rejected": row["rejected"].strip(),
        })

    OUT_JSON.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_INFO.write_text(
        json.dumps({"hak180_dpo": {
            "file_name": OUT_JSON.name,
            "ranking": True,
            "columns": {"prompt": "instruction", "query": "input",
                        "chosen": "chosen", "rejected": "rejected"},
        }}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    from collections import Counter
    flaws = Counter(df["flaw"].str.strip())
    print(f"✅ {len(samples)} 对 → {OUT_JSON.name}")
    print("  配方:", " / ".join(f"{k} {v}" for k, v in sorted(flaws.items())))
    print(f"✅ 注册片段（ranking:true）→ {OUT_INFO.name}\n")
    print("—— 样例 instruction 尾部（截 240 字）——")
    print(samples[0]["instruction"][-240:])
    print("—— chosen / rejected ——")
    print(samples[0]["chosen"])
    print(samples[0]["rejected"])


if __name__ == "__main__":
    main()
