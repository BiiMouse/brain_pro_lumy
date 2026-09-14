# Lumy 型号知识库（半导体规格书场景）

基于（brain）RAG 底座改造的**双索引型号知识库**：对 5 份电子元器件规格书
（max20029 / lm358 / tl431 / dcrcw / lm317）做**结构化型号提取（四层定义）+ 语义文本检索**，
支持六类问答，答案带**文件名 + 页码 + 证据**。

## 1. 架构

```
                     ┌──────────────── lumy 导入图（KB_SCENARIO=lumy）────────────────┐
 PDF ──► entry_node ─┤ 链路B(结构化): pdf_table_extract(pdfplumber,页码/跨页表/合并格) │
                     │                → region_label(LLM区域标注+正则锚点)            │
                     │                → model_extract(四层提取: 规则枚举+LLM语义)     │
                     │                → pg_import(PostgreSQL)                        │
                     │ 链路A(语义):   lumy_split(带页码分块) → bge_embedding          │
                     │                → milvus(kb_lumy_chunks_v1)                     │
                     └────────────────────────────────────────────────────────────────┘

                     ┌──────────────── lumy 查询图 ────────────────┐
 问题 ──► intent_entity(六类意图+实体) ─┬─► structured_lookup(PG: 严格/前缀对齐,   │
                                        │    层级遍历, 命名规则文法)                │
                                        └─► vector/HyDE 检索(Milvus, file_title过滤)│
                                            → RRF → Rerank → 证据引用答案/拒答       │
                     └────────────────────────────────────────────────┘
```

**四层型号定义**（Lumy v1.5）：产品家族 → PPN（家族+功能参数编码位）→ OPN（PPN+订购属性
编码位）。层级按**编码位的属性性质**判定（功能→PPN、订购→OPN），不按字符串位置；
PPN 不必是 OPN 的连续前缀（Maxim 交错情形）。

## 2. 环境与部署

- Python 3.10+，依赖：`pip install -r requirements.txt`
- `knowledge/.env` 在 brain 配置基础上追加：

```ini
KB_SCENARIO=lumy
PG_HOST=192.168.245.128
PG_PORT=5432
PG_USER=postgres
PG_PASSWORD=<密码>
PG_DB=lumy
# 可选（默认 kb_lumy_chunks_v1）
LUMY_CHUNKS_COLLECTION=kb_lumy_chunks_v1
```

- PostgreSQL（虚拟机 Docker）：

```bash
docker run -d --name pg-lumy -e POSTGRES_PASSWORD=<密码> -e POSTGRES_DB=lumy \
  -p 5432:5432 postgres:13
```

- 其余服务（Milvus/MongoDB/MinIO/BGE-M3/DeepSeek）与 brain 共用，见 `knowledge/.env`。

## 3. 运行

```bash
# 批量导入（结构化+语义双链路，幂等可重跑）
set KB_SCENARIO=lumy
python scripts/lumy_import_all.py referencePDF

# 单份导入
python -m knowledge.cli ingest referencePDF/max20029-max20029d.pdf

# 问答（CLI，笔试入口）
python -m knowledge.cli ask "MAX20029B系列有哪些产品型号？"
python -m knowledge.cli ask "MAX20029ATIA/V+的后缀代表什么？" --show-context

# 导出结构化提取结果（笔试交付物）
python -m knowledge.cli export-models -o eval/lumy_models.jsonl

# 自测问答评估（13题，覆盖六类）
python eval/lumy_eval.py
```

### 3.1 Web 检索前端（复用 brain 原有页面）

查询图与导入图都按 `KB_SCENARIO` 切换，原有前端直接可用：

```bash
set KB_SCENARIO=lumy
.venv/Scripts/python.exe knowledge/front/api/query_router.py
# 浏览器打开 http://127.0.0.1:8001/chat.html （SSE 流式，会话历史）
```

原导入前端同理（lumy 模式下上传 PDF 即走双链路导入）：

```bash
set KB_SCENARIO=lumy
.venv/Scripts/python.exe knowledge/front/api/import_router.py
# 浏览器打开 import.html 上传页
```

**切回 brain 场景**：不设 `KB_SCENARIO`（默认 brain），导入/查询图均为原逻辑，行为不变。

## 4. 交付物清单

| 交付物 | 位置 |
|---|---|
| 代码 | `knowledge/processor/import_process/nodes/`（pdf_table_extract / region_label / model_extract / pg_import / lumy_chunk_nodes）、`knowledge/processor/query_process/nodes/`（intent_entity / structured_lookup / lumy_search_nodes / answer_node_lumy）、`knowledge/cli.py`、`scripts/lumy_import_all.py` |
| DDL | `knowledge/schema/lumy_pg.sql` |
| 结构化提取结果 | `eval/lumy_models.jsonl`（由 export-models 导出） |
| 自测问答及结果 | `eval/lumy_qa.json` + `eval/lumy_result.md`（13 题，六类覆盖） |
| 解析中间产物 | `referencePDF/lumy_extract/<pdf>/`（pdf_tables / regions / models JSON） |

## 5. 方案说明

### 5.1 解析方式（pdfplumber，纯文本层，无 OCR）
5 份均为原生文本型 PDF。pdfplumber 按矢量线坐标提取表格：
- **合并单元格**：按 cell bbox 覆盖的行/列条带精确填充（纵向如 MAX20029 家族名列跨行，
  横向如 dcrcw 阻值跨列），空单元格不会被误填；
- **跨页续表**：相邻页 + 列数一致 +（重复表头匹配 或 表底≥80%页高且后表起于页顶 30%），
  tl431 EC 表跨 9 页合并 86 行、lm358 封装附录跨 8 页合并 196 行；
- **页眉页脚剔除**：在 ≥50% 页面重复出现的行自动剔除。

### 5.2 区域标注与型号提取（层级保障四道防线）
1. **区域角色先行**：正则锚点（表格标题/首行强锚 + 页首弱锚，剔除目录条目与
   "See the ..."交叉引用）+ LLM 区域划分。提取只消费 model_source / opn_source 区域，
   不做全文扫描——同一字符串在订购表列是封装属性、在正文是被引器件，结构性区分。
2. **结构化枚举**：Selector Guide 逐行（分组行=家族）、对比表表头/分节、附录
   "Orderable part" 列、EC 节标题、技术规格表头（被动元件尺寸家族）。
3. **LLM 语义层**：功能位/订购位分类、命名规则文法解码、异常 OPN（军品 5962-*）家族
   归属；DeepSeek 仅做边界点调用。
4. **反规则与锚定**：封装名/图号/文档编号/认证号黑名单；家族与 PPN 必须是原文独立词
   （防幻觉与截断误报）；封面 token 交叉校验；PPN/OPN 同串去重。

### 5.3 分块与检索策略
- **双索引**：PG 存四层结构化数据（families/ppns/opns/naming_rules，attributes JSONB）；
  Milvus kb_lumy_chunks_v1 存语义块（表格线性化 25 行/片重复表头 + 文本 ~700 字符/块，
  chunk 带 page/page_end/file_title）。
- **查询路由**：六类意图（model_list/model_detail/rule_explain/param_query/cross_compare/
  no_answer）；结构化检索先行（严格对齐→前缀对齐下沉），其命中的文件供向量检索
  file_title 过滤；向量+HyDE 经 RRF(k=60) → BGE-Reranker 精排。
- **证据契约**：每条结论标 [文件 第N页]/[型号库]；参数保留单位/测试条件/typ-max；
  跨文档分列来源；双源皆空或低于拒答阈值(0.4)时明确拒答。

### 5.4 提取纪律（不展开）
命名规则只作文法解码（naming_rules.expanded=false）；型号枚举仅来自文档逐条列出处
（MAX20029=18 个 OPN 来自 Selector Guide，非 A×温度×封装组合；dcrcw 阻值×容差×E 系列
不做笛卡尔积，仅记录 2 个显式示例 OPN）。
