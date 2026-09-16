"""Reranker CPU 性能基准：线程数 × max_length 对 compute_score 耗时的影响。

背景：bge-reranker-large(560M) 在 i5-11320H(4C8T) CPU 上精排 8 条 pair 耗时 78s，
需要量化两个零成本杠杆的实际收益：
  1. 线程数：env(OCP/MKL) 只在 torch import 时读一次，但 torch.set_num_threads()
     可在运行时随时改，所以一个进程内就能扫多组线程数。
  2. max_length：交叉编码器算力 ∝ 序列长度²，截断收益是平方级的。

用法：
    ./.venv/Scripts/python.exe scripts/bench_reranker_threads.py

pair 构造：中文按 BERT 词表约 1 字 ≈ 1 token，query ~25 字 + doc 300 字 ≈ 325 token，
接近线上真实分布（已验证多数 doc 不足 512）。
"""

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import torch  # noqa: E402  import knowledge 已保证 env 先于 torch 生效
from knowledge.utils.bge_rerank_util import get_reranker_model  # noqa: E402

QUERY = "TL432精密可调分流基准源在电路中的典型应用方式和关键参数范围是什么？" * 1
DOC = ("该系列器件是精密可调分流基准源，具有低温漂、低动态输出阻抗、"
       "宽工作电流范围等特点，可用于隔离型反馈电路、误差放大器参考、"
       "电压监测与比较器基准等场景。其输出电压可通过两只外接电阻在"
       "Vref到36V之间任意设置，典型温漂为30ppm/℃，工作电流0.4mA起。") * 4


def build_pairs(n_pairs: int, doc: str):
    return [(QUERY, doc) for _ in range(n_pairs)]


def bench(model, pairs, label: str, **kwargs) -> float:
    torch.cuda.synchronize() if torch.cuda.is_available() else None
    t0 = time.perf_counter()
    scores = model.compute_score(sentence_pairs=pairs, **kwargs)
    elapsed = time.perf_counter() - t0
    if not isinstance(scores, list):
        scores = [scores]
    print(f"  {label:<28} {elapsed:7.2f}s   (示例分数: {round(scores[0], 4)})",
          flush=True)
    return elapsed


def main():
    model = get_reranker_model()
    print(f"\ntorch 默认线程数: {torch.get_num_threads()}，"
          f"逻辑核: {torch.get_num_interop_threads() if hasattr(torch, 'get_num_interop_threads') else 'N/A'}",
          flush=True)

    pairs = build_pairs(n_pairs=8, doc=DOC)
    pair_tokens = len(QUERY) + len(DOC)  # 中文 1字≈1token 粗估
    print(f"测试负载: 8 pairs × ~{pair_tokens} token\n", flush=True)

    # ---- 第一组：线程数扫描（max_length 固定 512）----
    print("== 线程数扫描 (max_length=512) ==", flush=True)
    warmup = build_pairs(2, DOC[:80])
    bench(model, warmup, "预热(2条短pair)")
    for n in (4, 8):
        torch.set_num_threads(n)
        bench(model, pairs, f"线程数={n}")

    # ---- 第二组：max_length 扫描（线程数固定 8）----
    print("\n== max_length 扫描 (线程数=8) ==", flush=True)
    torch.set_num_threads(8)
    for ml in (512, 256):
        bench(model, pairs, f"max_length={ml}", max_length=ml)

    # ---- 第三组：组合最优 ----
    print("\n== 组合 (线程数=8 + max_length=256) 已含上一组，复测一次稳定性 ==",
          flush=True)
    bench(model, pairs, "max_length=256 复测", max_length=256)

    print("\n完成。", flush=True)


if __name__ == "__main__":
    main()
