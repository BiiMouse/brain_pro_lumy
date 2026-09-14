"""裸 Qwen2.5-0.5B-Instruct 定性基线（第 3 课）：SFT 前的 "before" 照片。

从 sft_alpaca.json 抽固定 6 条（4 pos + 2 neg），instruction 原样喂裸模型，
逐条记录生成输出 → baseline_bare.json。第 4 课 SFT 后用同一批指令重跑对比。

固定抽样（不打乱、不随机）：按 output 是否以拒答模板开头区分 pos/neg，
取前 4 条 pos + 第 1 条空 contexts neg + 第 1 条带段 neg——覆盖全部样本形态。

用法（云端 LLaMA-Factory/data/ 目录下）:
    python bare_baseline.py

产出: baseline_bare.json（与 sft_alpaca.json 同目录）
"""
import json
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

HERE = Path(__file__).parent
DATA = HERE.parent / "sft_alpaca.json"
MODEL_PATH = "/root/rivermind-data/models/Qwen2.5-0.5B-Instruct/snapshots/master"
OUT = HERE / "baseline_bare.json"
REFUSAL_PREFIX = "资料不足，暂无法回答该问题。"
MAX_NEW_TOKENS = 512

# 固定挑 6 条：多样性靠手选索引（写死，重跑可复现）
# pos: 0 拆解(2段) / 2 烫金膜盒(3段带标题) / 9 油漆稀释剂(长段) / 11 搬运
# neg: 第一条空 contexts / 第一条带干扰段
PICK_POS = [0, 2, 9, 11]


def pick(samples):
    # 空 contexts 的判定必须锚定结构位置："无参考答案"四个字出现在每条
    # instruction 里（ANSWER_PROMPT 规则 3 的模板文本），散词 not in 恒 False
    # ——与问题解决记录 #9 is_refusal 教训同源：判据锚定结构，不锚散词。
    EMPTY_MARK = "【参考内容】\n无参考答案"
    negs_empty = [i for i, s in enumerate(samples)
                  if s["output"].startswith(REFUSAL_PREFIX)
                  and EMPTY_MARK in s["instruction"]]
    negs_ctx = [i for i, s in enumerate(samples)
                if s["output"].startswith(REFUSAL_PREFIX)
                and EMPTY_MARK not in s["instruction"]]
    if not negs_empty:
        raise SystemExit("数据集中没有'空参考'负样本（参考内容区=无参考答案），无法抽样")
    if not negs_ctx:
        raise SystemExit("数据集中没有'带段'负样本，无法抽样")
    print(f"neg 统计：空参考 {len(negs_empty)} 条 / 带段 {len(negs_ctx)} 条")
    return PICK_POS + [negs_empty[0], negs_ctx[0]]


def main():
    samples = json.loads(DATA.read_text(encoding="utf-8"))
    idxs = pick(samples)
    print(f"抽中索引: {idxs}")

    tok = AutoTokenizer.from_pretrained(MODEL_PATH)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH, torch_dtype="auto", device_map="auto")
    model.eval()

    results = []
    for n, i in enumerate(idxs, 1):
        s = samples[i]
        prompt = s["instruction"]
        messages = [{"role": "user", "content": prompt}]
        # 与 smoke.py 同款调用（坑 d 已修）：取 .input_ids、device_map
        inputs = tok.apply_chat_template(
            messages, add_generation_prompt=True, return_tensors="pt")
        input_ids = inputs.input_ids.to("cuda")
        with torch.no_grad():
            out = model.generate(
                input_ids, max_new_tokens=MAX_NEW_TOKENS,
                do_sample=False, temperature=None, top_p=None, top_k=None)
        gen = tok.decode(out[0][input_ids.shape[1]:], skip_special_tokens=True)

        # 记录：截短的题面 + 期望 output（来自训练集）+ 裸模型实际输出
        q = prompt[prompt.rfind("【用户问题】"):-len("请回答：")].strip()
        results.append({
            "idx": i,
            "kind": "neg" if s["output"].startswith(REFUSAL_PREFIX) else "pos",
            "question": q,
            "expected": s["output"],
            "bare_output": gen,
        })
        print(f"\n===== [{n}/{len(idxs)}] ({results[-1]['kind']}) {q}")
        print(f"----- 期望（训练集 answer）-----\n{s['output']}")
        print(f"----- 裸模型输出 -----\n{gen}")

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\n✅ {len(results)} 条 → {OUT}")


if __name__ == "__main__":
    main()
