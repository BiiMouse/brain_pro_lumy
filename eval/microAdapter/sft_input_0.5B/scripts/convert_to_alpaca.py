"""CSV → alpaca 转换：把 SFT_Questions.csv 变成 LLaMA-Factory 训练集。

铁律：训练格式 = 推理格式（问题解决记录 #11）。逐字段对齐生产链路：
- instruction = 线上 ANSWER_PROMPT 原文填空（importlib 单源加载 query_prompt.py，不复制）
    {context}     段按 answer_node.format_reranker_docs 包装成
                  `[n]:{'score':.., 'url':.., 'title':..}\\n内容`，段间 \\n\\n；
                  空 contexts → "无参考答案"（answer_node.py:98 空检索的渲染）
    {history}     "暂无历史"（answer_node.py:99）
    {item_names}  str(['HAK180烫金机'])——生产 format(list) 的字面形态
    {question}    "HAK180烫金机：{csv问题}"——对齐线上 rewritten_query
                  "包含商品名称的独立完整问题"的形态（与 eval qa.csv 前缀同款）
- output = answer 原文
- score 确定性合成（md5 种子，重跑结果不变）：pos top≈0.9 档（对齐 eval 可回答集
  top 0.78+）；neg 必须全部 ≥ 0.4 拒答闸门——低于闸门 check_context_sufficient
  直接硬拒、不调 LLM，那种 prompt 线上永远到不了模型，教了也白教
- title = 段落所属 chunk 的 title（chunks.json 反查，含 `# ` 前缀，同 Milvus 存量）
- url = ''（chunk 无独立 url 字段，生产 doc.get("url","") 默认空）

用法（项目根目录下）:
    .venv/Scripts/python.exe eval/microAdapter/convert_to_alpaca.py

产出:
    eval/microAdapter/sft_alpaca.json        训练集（alpaca: instruction/input/output）
    eval/microAdapter/dataset_info_sft.json  LLaMA-Factory dataset_info 注册片段
上传云端时两个文件都拷到 LLaMA-Factory/data/ 下，并在 dataset_info.json 合并注册。
"""
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
CSV = HERE.parent / "SFT_Questions.csv"
CHUNKS = (HERE.parent.parent.parent.parent / "knowledge" / "front" / "temp_data" / "20260804"
          / "78dc0628-08d8-4d5e-8eb4-bfe3a5ed14f8" / "chunks.json")
QUERY_PROMPT = HERE.parent.parent.parent.parent / "knowledge" / "prompts" / "query" / "query_prompt.py"
OUT_JSON = HERE.parent / "sft_alpaca.json"
OUT_INFO = HERE.parent / "dataset_info_sft.json"

GATE_THRESHOLD = 0.4  # 生产拒答闸门（config.rag_refuse_threshold 默认 0.4）


def load_answer_prompt() -> str:
    """单源加载线上 ANSWER_PROMPT——线上改了 prompt 重跑本脚本即同步，永不漂移。"""
    spec = importlib.util.spec_from_file_location("query_prompt", QUERY_PROMPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ANSWER_PROMPT


def normalize(text: str) -> str:
    """与 validate_sft.py 同款归一化：去 •\\t 前缀、行尾空格、3+ 连换行压成 2。"""
    lines = [ln.lstrip("•\t").rstrip() for ln in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines).strip())


def split_contexts(ctx: str):
    """按单独一行 --- 切段（与 validate_sft.py 同款）。"""
    if not ctx or not ctx.strip():
        return []
    parts = re.split(r"(?m)^---\s*$", ctx)
    return [p.strip("\n").strip() for p in parts if p.strip()]


def find_chunk_title(seg: str, chunks) -> str:
    """反查段落所属 chunk 的 title（多个 chunk 含同段时取第一个）。"""
    seg_n = normalize(seg)
    for c in chunks:
        if seg_n in normalize(c["content"]):
            return c.get("title", "")
    return ""


def synth_score(question: str, i: int, base: float, step: float, floor: float) -> float:
    """确定性合成 rerank 分：md5 种子（重跑不变），逐段递减模拟 rerank 排序。"""
    h = int(hashlib.md5(f"{question}:{i}".encode("utf-8")).hexdigest()[:8], 16)
    jitter = (h % 40) / 1000.0  # ±0.04 内抖动，避免分数整齐得像人造
    return round(max(floor, base - i * step + jitter), 4)


def wrap_context(segs, question: str, typ: str, chunks) -> str:
    """复刻 answer_node.format_reranker_docs 的段包装。"""
    if not segs:
        return "无参考答案"
    if typ == "pos":
        base, step, floor = 0.92, 0.05, 0.55
    else:  # neg：top 必须 ≥ 闸门（该场景是"过了闸门但答不了"，靠 LLM 第二道防线拒）
        base, step, floor = 0.62, 0.04, 0.45
    docs = []
    for i, seg in enumerate(segs):
        score = synth_score(question, i, base, step, floor)
        if i == 0 and typ == "neg":
            assert score >= GATE_THRESHOLD, f"neg top 分 {score} 低于闸门，线上到不了 LLM"
        meta = {
            "score": score,
            "url": "",  # 生产 doc.get("url", "") 默认空
            "title": find_chunk_title(seg, chunks),
        }
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
        ans = row["answer"].strip()

        instruction = prompt_tpl.format(
            context=wrap_context(segs, q, typ, chunks),
            history="暂无历史",
            item_names=str([item]),
            question=f"{item}：{q}",
        )
        # 填空完整性自检：不允许残留任何占位符
        assert not re.search(r"\{(context|history|item_names|question)\}", instruction), q
        samples.append({"instruction": instruction, "input": "", "output": ans})

    OUT_JSON.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_INFO.write_text(
        json.dumps({"hak180_sft": {"file_name": OUT_JSON.name}},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")

    n_pos = int((df["type"].str.strip() == "pos").sum())
    print(f"✅ {len(samples)} 条 → {OUT_JSON.name}（pos {n_pos} / neg {len(samples) - n_pos}）")
    print(f"✅ LLaMA-Factory 注册片段 → {OUT_INFO.name}\n")
    # 预览第一条 pos 的 instruction 头部（检查段包装形态）
    first = samples[0]["instruction"]
    print("—— 样例 instruction 开头（截 700 字）——")
    print(first[:700])
    print("—— ……（中略）——")
    print(first[-260:])
    print("—— output ——")
    print(samples[0]["output"])


if __name__ == "__main__":
    main()
