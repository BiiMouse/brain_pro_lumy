"""bge-reranker-base 下载验证 + 速度/分数预览。

与 scripts/bench_reranker_threads.py 使用完全相同的 8 条 pair 负载，
可直接对比 large 的实测数据（8线程: ml=512 32.7s / ml=256 16.4s，logit 3.963/3.862）。

用法：
    ./.venv/Scripts/python.exe scripts/test_bge_reranker_base.py
"""

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_reranker_threads import build_pairs  # noqa: E402  复用相同负载定义

import knowledge  # noqa: F401,E402  线程数 env 引导（先于 torch）
import torch  # noqa: E402
from FlagEmbedding import FlagReranker  # noqa: E402

MODEL_DIR = r"D:\ai_models\bge_models\BAAI\bge-reranker-base"

t0 = time.perf_counter()
model = FlagReranker(
    model_name_or_path=MODEL_DIR,
    device="cpu",
    use_fp16=False,
)
print(f"模型加载耗时: {time.perf_counter() - t0:.1f}s", flush=True)
print(f"参数量(粗估): {sum(p.numel() for p in model.model.parameters()) / 1e6:.0f}M", flush=True)

torch.set_num_threads(8)

# 与 bench 脚本一致的负载构造
from bench_reranker_threads import QUERY, DOC  # noqa: E402
pairs = build_pairs(n_pairs=8, doc=DOC)

warmup = build_pairs(n_pairs=2, doc=DOC[:80])
model.compute_score(sentence_pairs=warmup, max_length=256)  # 预热
print("预热完成，开始计时", flush=True)

for ml in (512, 256):
    t0 = time.perf_counter()
    scores = model.compute_score(sentence_pairs=pairs, max_length=ml)
    elapsed = time.perf_counter() - t0
    print(f"base 8线程 ml={ml}: {elapsed:6.2f}s   (示例 logit: {round(scores[0], 4)})",
          flush=True)

print("\n对照 large(8线程): ml=512 32.7s (3.963) / ml=256 16.4s (3.862)", flush=True)
