"""knowledge 包初始化（整个项目的全局引导点）。

Python 在 import 任何 knowledge.* 子模块之前，都会先执行本文件。
因此这里适合放"必须先于一切业务代码生效"的全局设置。

⚠️ 线程数环境变量必须在这里设置：
torch 由 FlagEmbedding 间接引入（bge_rerank_util / bgem3_client_util 的模块顶部
import），torch 在被 import 的那一刻就初始化 OpenMP/MKL 运行时并读走线程数，
之后再改 os.environ 不生效。写在这里可保证先于 torch 生效。

注意：本文件只允许 import os，不要 import 项目内其他模块或重型第三方库，
否则会破坏"先于一切"的保证。
"""

import os

# CPU 并行线程数限制：必须在 import torch 之前执行
os.environ["OMP_NUM_THREADS"] = "8"
os.environ["MKL_NUM_THREADS"] = "8"
os.environ["OPENBLAS_NUM_THREADS"] = "8"
os.environ["VECLIB_MAXIMUM_THREADS"] = "8"
os.environ["NUMEXPR_NUM_THREADS"] = "8"
