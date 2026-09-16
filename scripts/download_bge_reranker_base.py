"""下载 bge-reranker-base 到本地模型目录（reranker-large 的 A/B 对照组）。

用法：
    ./.venv/Scripts/python.exe scripts/download_bge_reranker_base.py

说明：
- 走 hf-mirror 镜像（国内直连 HF 不通）
- 仓库里有三份等价权重（model.safetensors / pytorch_model.bin / onnx/model.onnx），
  只拉 safetensors 一份，省约 2.2GB；transformers 加载本地目录时优先读 safetensors
- snapshot_download 自带断点续传，中断后重跑即可
"""

import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from huggingface_hub import snapshot_download

TARGET_DIR = r"D:\ai_models\bge_models\BAAI\bge-reranker-base"

path = snapshot_download(
    repo_id="BAAI/bge-reranker-base",
    local_dir=TARGET_DIR,
    ignore_patterns=["pytorch_model.bin", "onnx/*", "*.gitattributes"],
)
print(f"下载完成: {path}")
