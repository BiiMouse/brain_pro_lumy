"""SFT+DPO 后三方对比（第 6 课）：与 bare_baseline.py 同 6 条指令，喂 DPO 后的模型。

与 after_sft.py 的差异仅两处：
1. ADAPTER 换成 outputs/hak180_dpo_lora（DPO 轮产出）
2. 输出键名 sft_output → dpo_output，产物 after_dpo.json

三方对比 = baseline_bare.json（裸）/ after_sft.json（SFT）/ after_dpo.json（SFT+DPO）。
重点看 DPO 是否修掉第 4 课暴露的三短板：引用标号错位、拒答理由不精确、注水。

用法（云端 LLaMA-Factory/data/ 目录下）:
    python after_dpo.py

产出: after_dpo.json
"""
import json
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

HERE = Path(__file__).parent
DATA = HERE.parent / "sft_alpaca.json"
MODEL_PATH = "/root/rivermind-data/models/Qwen2.5-0.5B-Instruct/snapshots/master"
ADAPTER = "/root/rivermind-data/outputs/hak180_dpo_lora"
OUT = HERE / "after_dpo.json"
REFUSAL_PREFIX = "资料不足，暂无法回答该问题。"
MAX_NEW_TOKENS = 512

# 与 bare_baseline.py / after_sft.py 完全一致的固定抽样
PICK_POS = [0, 2, 9, 11]
DEFAULT_SYSTEM = "You are Qwen, created by Alibaba Cloud. You are a helpful assistant."


def pick(samples):
    EMPTY_MARK = "【参考内容】\n无参考答案"
    negs_empty = [i for i, s in enumerate(samples)
                  if s["output"].startswith(REFUSAL_PREFIX)
                  and EMPTY_MARK in s["instruction"]]
    negs_ctx = [i for i, s in enumerate(samples)
                if s["output"].startswith(REFUSAL_PREFIX)
                and EMPTY_MARK not in s["instruction"]]
    if not negs_empty or not negs_ctx:
        raise SystemExit("负样本抽样失败（数据集形态变化？）")
    return PICK_POS + [negs_empty[0], negs_ctx[0]]


def main():
    samples = json.loads(DATA.read_text(encoding="utf-8"))
    idxs = pick(samples)
    print(f"抽中索引: {idxs}")

    tok = AutoTokenizer.from_pretrained(MODEL_PATH)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH, torch_dtype="auto", device_map="auto")

    from peft import PeftModel
    model = PeftModel.from_pretrained(model, ADAPTER)
    model.eval()
    print(f"adapter 已加载: {ADAPTER}")

    results = []
    for n, i in enumerate(idxs, 1):
        s = samples[i]
        messages = [
            {"role": "system", "content": DEFAULT_SYSTEM},
            {"role": "user", "content": s["instruction"]},
        ]
        inputs = tok.apply_chat_template(
            messages, add_generation_prompt=True, return_tensors="pt")
        input_ids = inputs.input_ids.to("cuda")
        with torch.no_grad():
            out = model.generate(
                input_ids, max_new_tokens=MAX_NEW_TOKENS,
                do_sample=False, temperature=None, top_p=None, top_k=None)
        gen = tok.decode(out[0][input_ids.shape[1]:], skip_special_tokens=True)

        q = s["instruction"][s["instruction"].rfind("【用户问题】"):-len("请回答：")].strip()
        results.append({
            "idx": i,
            "kind": "neg" if s["output"].startswith(REFUSAL_PREFIX) else "pos",
            "question": q,
            "expected": s["output"],
            "dpo_output": gen,
        })
        print(f"\n===== [{n}/{len(idxs)}] ({results[-1]['kind']}) {q}")
        print(f"----- 期望 -----\n{s['output']}")
        print(f"----- DPO 后输出 -----\n{gen}")

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\n✅ {len(results)} 条 → {OUT}")


if __name__ == "__main__":
    main()
