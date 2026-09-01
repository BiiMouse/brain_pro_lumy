# Config A 基线存档（2026-09-01）

三组控制变量对比的 **A = DeepSeek-v4 + 好检索（强基线）**。B（Qwen2.5-7B 原始）、
C（Qwen2.5-7B 微调）沿用同一检索与索引，净收益 = C − B，自部署代价 = B − A。

## 配置快照

- **生成模型**：DeepSeek-v4（`OPENAI_API_BASE`，见 `knowledge/.env`）
- **检索**：本地 BGE embedding（BGEM3）+ bge-reranker-large（sigmoid 归一化，0~1）
- **拒答阈值**：`RAG_REFUSE_THRESHOLD=0.4`（阈值校准：可回答 min=0.780 ≫ 拒答 max=0.010，完全可分）
- **索引**：已冻结版本（chunking 是 A/B/C 共用控制变量，不再改动）
- **eval 代码**：`eval/eval_plus.py`（本次定稿含 session_id 独立化 + is_refusal 连续短语判定，
  详见项目根 `问题解决记录.md` 问题 8/9）
- **数据**：可回答 5 条（`eval/qa.csv`）+ 拒答负例 6 条（`eval/qa_neg.csv`）

## 结果（summary.txt 为准）

| 指标 | 值 |
|---|---|
| faithfulness | 0.9351 |
| answer_relevancy | 0.8684 |
| context_recall | 0.8000 |
| answer_correctness | 0.5427 |
| context_precision | 0.0775 |
| citation_rate / valid_rate（#4） | 1.0000 / 1.0000 |
| refusal_accuracy（#5） | 1.0000（6/6） |
| 误拒 | 0/5 |

## 已知短板（如实记录，不阻塞存档）

1. **context_precision 0.078**：检索质量信号（无关 chunk 排在含答案 chunk 前面），
   与问题 5 中「答案在 rerank 第 4 位」一致。计划：存完 A 后回头治检索/rerank，
   属三组共用的检索层，改了需同步评估对 A 基线的影响。
2. **Q5「桌面放置」correctness 低**：「边缘」被理解成纸张边缘而非桌面边缘——
   问题改写/语义理解的基线真实水平。

## 架构备注

- **拒答闸门在检索层**（reranker 分数 vs 阈值），不调用 LLM、不依赖 LLM 自觉。
  负例即使被 HyDE 节点编出"合理"的假设文档（如「推荐餐厅」负例生成出 GPS 定位、
  3264 家餐厅数据库的假手册），reranker 照样给 0.003 分拦截。B/C 沿用此防线。
- **is_refusal 用连续短语「资料不足，暂无法」判定**：三个拒答模板共用此开头。
  已知边界：裸 Qwen（Config B）可能不按模板说话，届时若拒答指标反常好，
  先怀疑规则漏计（模型用自己的话拒答而规则没匹配上），再考虑升级为 LLM 判拒答。
- **存档工件必须一次完整运行产出**：`--no-ragas` 会覆盖 `qa_result_plus.csv`
  且不带 RAGAS 列，不能与之前跑的结果手工拼接。
