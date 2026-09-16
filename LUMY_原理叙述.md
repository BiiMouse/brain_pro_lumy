# Lumy 半导体规格书问答系统 —— 原理叙述版

> 这是一份"讲解式"文档：按代码实际执行顺序，用大白话把"PDF 进来发生了什么"和"用户提问之后发生了什么"讲一遍。
> 对应代码入口：导入图 `create_graph_import_lumy()`、查询图 `create_query_graph_lumy()`（`knowledge/processor/*/main_graph.py`），环境变量 `KB_SCENARIO=lumy` 启用。

---

## 一、总体设计：一份 PDF，两条链路，两个索引

系统对每份规格书 PDF 做"一事两吃"：

- **链路 B（结构化链路）**：把 PDF 里的型号世界（家族/PPN/OPN/命名规则）抽成精确数据，存进 **PostgreSQL**，负责"查得准"——比如"TL432 系列有哪些型号"这种枚举、反查、规则解释类问题。
- **链路 A（语义链路）**：把 PDF 原文切成带页码的文本块，向量化后存进 **Milvus**，负责"查得全"——比如"供电电压范围是多少"这种要回到原文上下文的问题。

查询时两路证据汇合，让 LLM 带着页码引用回答。导入时先走链路 B 再走链路 A（B 的型号提取结果会被 A 拿去给分块打标），所以两条链路在图里是串行连接的：`entry → pdf_table_extract → region_label → model_extract → pg_import → lumy_split → bge_embedding → milvus`。

---

## 二、导入链路：PDF 是怎么被处理的

### 步骤 1：pdf_table_extract —— 用 pdfplumber 抽表格和正文

考虑到这 5 份规格书 PDF 都是**原生文本型**（不是扫描件），不需要 OCR，直接用 **pdfplumber** 做矢量解析。为什么不用老链路的 MinerU？因为链路 B 需要的是**精确的表格单元格 + 页码**，pdfplumber 基于边框线的坐标提取表格，单元格粒度和页码都是天然精确的；MinerU 转出来的是 markdown，表格结构会糊掉。所以干脆链路 A 也复用 pdfplumber 的产物，MinerU 在 lumy 模式下完全不参与。

具体流程是：对每一页，用"线策略"（`vertical_strategy: lines / horizontal_strategy: lines`，因为规格书的表格全都有边框线）找表格。找到之后做三件精细活：

1. **合并单元格填充**：pdfplumber 对被合并覆盖的位置返回 None。程序不盲目填充，而是读每个单元格的 bbox（坐标框）：某个格子的底边"越界"覆盖到下面几行的条带，说明它是纵向合并格，值向下填充；右边覆盖到右侧列条带，说明是横向合并格，值向右填充。真正空着的格子（bbox 只占一个条带）不会被误填。
2. **清洗**：None 变空串、内部换行压成空格、删掉全空行和全空列（pdfplumber 偶尔在尾部产生假列）。只有一行的"表"直接丢弃——那通常是页眉装饰线被误判成表格。
3. **找表标题**：取表格 bbox 上方 80 磅以内最近的文本行，当作这个表的标题（后面区域标注要用）。

表格抽完，把表格区域从页面上裁掉（`outside_bbox`），剩下的部分 `extract_text()` 得到的就是"表格外正文"——这样正文和表格不会重复计入。

最后做**跨页续表合并**：一个大表常常跨页断开，第 2 页还会重复一遍表头。判定条件是相邻两页、列数一致，且满足其一：(a) 后表首行与前表首行相似度 ≥ 0.5（重复表头，去掉表头再拼接）；(b) 几何延续——前表底部低于页高 80% 且后表顶部高于页高 30%（说明表"顶天立地"断开了，直接拼接）。支持连锁合并（一张表跨 3 页以上）。

产物落盘为 `pdf_tables.json`：每页的正文文本 + 每个表格的（页码、bbox、标题、行数据），外加跨页合并后的整表。这是后面所有步骤的"地面真相"。

### 步骤 2：region_label —— 先用正则锚点、再用 LLM，给每页打区域标签

一份两三百页的规格书里，只有少数区域藏着型号信息（选型表、订购表、命名规则、电气参数表），其他全是应用电路和文字描述。这一步回答"哪里有什么"。

做法是**正则锚点先行、LLM 补全、锚点纠偏**三层：

1. **确定性锚点**：一组关键词规则（"selector guide"→选型表、"ordering information"→订购表、"device nomenclature"→命名规则、"electrical characteristics"→电气参数表……）。分强弱：关键词出现在**表格标题或表格首行**里是强锚点（区域标题就贴着表格）；出现在页面文本头 300 字符内是弱锚点，但要先排除两类误报——目录页（一页里出现 3 处以上".....16"这种点线引导符就判定是目录）和交叉引用（"See the Ordering Information table for..."这种句子里的关键词不算）。
2. **LLM 区域划分**：把 pdf_tables.json 压成逐页摘要（每页正文前 160 字 + 各表格的标题/行列数/首行），喂给 LLM（JSON 输出模式），让它划出 `[page_start, page_end, type, title]` 的区域块。
3. **锚点纠偏**：LLM 划的区域如果和锚点冲突，以锚点为准——每个锚点页必须被同类型区域覆盖，没有就强制插入一个单页区域。宁可区域重叠，不可区域缺失。

产物 `regions.json`。每个区域带 role 标签（`model_source` / `opn_source` / `param_source` / `body` / `noise`），下一步的提取引擎**只消费带 role 标签的区域，不扫原始页面**——这是层级保障的第一层：位置对了，提取才有意义。

### 步骤 3：model_extract —— 四层型号体系落地（规则枚举 + LLM 语义 + 三重校验）

这是链路 B 的核心，把"四层定义"（家族 Family → PPN 功能型号 → OPN 订购型号 → 命名规则）从区域数据里抽出来。原则是：**型号字符串只从结构化位置产生，绝不做全文正则扫描**——全文扫描会把封装名（SOT-23）、文档编号（SLVS044Z）、认证号（AEC-Q200）全捞进来。

**第一层：规则枚举（确定性提取）**。不同来源用不同的专用提取器：

- **Selector Guide 表**：横向合并填充后的"分组行"（≥2 个非空单元格且全部相同）就是家族名；分组行下面的型号行是完整订购型号。逐行状态机式扫描。
- **对比表**：表头里的单 token 单元格是家族名（"LM358B LM358BA" 按空白拆开逐个判，"LM317 (Legacy Chip)" 取括号前部分）。
- **附录订购表**：找 "Orderable part" 列，整列就是 OPN 权威清单——这是最可靠的 OPN 来源，纯规则完成。
- **EC 表节标题**："Electrical Characteristics, TL431C, TL432C" 这种节标题正则抓型号（tl431 的档位组合来源）。
- **订购区文本**："Part Number: XXX" 形式的显式示例（被动元件规格书常见）。

所有候选 token 过一遍**反规则黑名单**：文档编号正则（`SL|LU|SB|SN` 开头+数字）、封装名正则（SOT/SOIC/TSSOP/DBV...）、图表号（Figure/Table 开头）、认证标准号（AEC-Q/MIL-STD）、噪声词表（PART/PACKAGE/ROHS...），再加形状约束（字母开头、≥3 位、含至少一个数字——纯字母缩写多半是噪声）。

**第二层：LLM 语义层**。把 Selector/对比表序列化（超 60 行截断）、命名规则区文本、订购表首屏拼成载荷（限 28000 字符），让 LLM 做四层判定：家族归类、PPN 判定（哪些 token 是功能位/订购位）、命名规则文法解码（"MAX20029ATI_/V+" 每一段是什么含义）。注意提取引擎用的是**专用长超时 LLM 客户端（180s）**，不复用查询侧的 30s 客户端——批量生成大 JSON 30 秒根本不够。还有一条纪律：命名规则**只解码不展开**（不去穷举所有组合，组合交给 OPN 枚举）。

**第三层：三重校验**。

- **源文锚定**：每个候选 token 必须在原文语料里"作为独立词"出现过（`TL4` 不能只在 `TL431` 内部当子串）。这一条同时防 LLM 幻觉和截断误报。
- **封面交叉校验**：封面页上的型号 token 应该都被家族集合覆盖，覆盖不了的报 issue。
- **LLM 复核归属**：前缀匹配失败的孤儿 OPN（比如军品号 5962-xxxx），再让 LLM 做一次家族归属。

中间还有两个精巧的确定性问题要处理：

- **OPN 剥后缀得 PPN**：`MAX20029ATIA/V+` 剥掉 `/V+` 得到 PPN。优先用 LLM 解码出来的后缀表，正则兜底（`/XX`、`+XX`、`#XX` 形式的短尾缀）——LLM 偶发漏报后缀时保证 PPN 层不塌陷。
- **孤儿 PPN 派生家族**：一堆 PPN 没有家族归属时（TL431AC、TL431I、TL431B...），按"去掉尾部 1-2 个字母档位码"归并基名，≥2 个成组才派生出家族 TL431。只处理家族为空的 PPN，不动已有归属——避免把 LM317A 错并进 LM317。

OPN 附着家族用**最长前缀优先**，PPN 精确包含优先于家族前缀。产物 `models.json`：families / ppns / opns / naming_rules / 校验报告。

### 步骤 4：pg_import —— 写入 PostgreSQL（幂等）

把 models.json + regions.json 写入 PG。建表 DDL 全部 `IF NOT EXISTS`（幂等）；同一文件重复导入时先 `DELETE FROM pdf_sources WHERE file_name = ...` 级联清空子表再插入——所以重跑导入不会产生脏数据（PG 侧永远是每个文件一份最新数据，这点和 Milvus 不同，见链路 A 的已知问题）。

**存储结构**（DDL 见 `knowledge/schema/lumy_pg.sql`）——一张主表挂四张业务表加一张区域表，层级就是四层型号定义本身：

```
pdf_sources（一份 PDF 一行：file_name 唯一 / page_count / parsed_at）
   │  id ← pdf_id 外键（ON DELETE CASCADE，删主表自动清子表）
   ├── regions        区域标注：page_start/pkage_end/region_type/role
   ├── families       家族层：family_name / family_type(normal|wildcard|...) / evidence_page
   ├── ppns           PPN 层：family_name / ppn / attributes(JSONB) / evidence
   ├── opns           OPN 层：family_name / ppn / opn / package / packing
   └── naming_rules   命名规则：pattern / positions(JSONB：逐段含义) / expanded
```

两个设计要点：

- **家族/PPN/OPN 之间用名称关联，不用外键 id**——同一家族（如 TL431）出现在多份 PDF 时，按名称 JOIN 天然跨文档；每张表内 `UNIQUE (pdf_id, name)` 保证同文件不重。
- **`ppns.attributes` 和 `naming_rules.positions` 是 JSONB 列**——Selector Guide 行转成的属性对（如 `{"扩频": "+3%"}`）可以直接用包含运算符查询，不用为每种参数建列。

实测行数（正式批量导入后）：pdf_sources 5 行，regions 40，families 34，ppns 66，opns 553，naming_rules 8。

**怎么连**：连接参数在 `knowledge/.env`（`PG_HOST/PG_PORT/PG_USER/PG_PASSWORD/PG_DB`，默认 192.168.245.128:5432，库名 lumy）。PG 跑在虚拟机里，查询前先确认虚拟机已开机。用 psql 连接：

```bash
psql -h 192.168.245.128 -p 5432 -U postgres -d lumy
```

**查询例子**（结果均已按入库数据核实，可直接对着查）：

例 1 —— OPN 反查：用户给出完整订购型号，查它属于哪个 PPN/家族、什么封装、证据在哪页：

```sql
SELECT o.opn, o.ppn, o.family_name, s.file_name, o.package, o.evidence_page
FROM opns o JOIN pdf_sources s ON s.id = o.pdf_id
WHERE o.opn = 'TL432BIDBZR';
-- opn          | ppn      | family | file_name | package           | page
-- TL432BIDBZR  | TL432BI  | TL432  | tl431.pdf | SOT-23 (DBZ) | 3  | 46
```

例 2 —— 家族下钻："MAX20029B 系列有哪些型号"（model_list 意图的结构化检索就长这样）：

```sql
SELECT p.ppn, COUNT(o.id) AS opn_count
FROM ppns p LEFT JOIN opns o ON o.pdf_id = p.pdf_id AND o.ppn = p.ppn
WHERE p.family_name = 'MAX20029B'
GROUP BY p.ppn ORDER BY p.ppn;
-- MAX20029BATIA | 1
-- MAX20029BATIB | 1
-- ...（共 7 个 PPN：ATIA~ATIH，各 1 个 OPN）
```

例 3 —— JSONB 属性查询："哪些 PPN 的扩频是 +3%"（传统列结构做不到，JSONB 的价值所在）：

```sql
SELECT p.ppn, p.attributes->>'扩频' AS spread
FROM ppns p JOIN pdf_sources s ON s.id = p.pdf_id
WHERE s.file_name LIKE 'max20029%'
  AND p.attributes @> '{"扩频": "+3%"}'::jsonb
ORDER BY p.ppn;
-- 共 12 行，如 MAX20029ATIB / MAX20029BATIB / MAX20029CATIB / ...
```

例 4 —— 前缀对齐（查询链路严格匹配失败后的降级策略就是它，`LIKE '前缀%'` 列出下一级清单）：

```sql
SELECT o.opn, o.ppn FROM opns o
WHERE o.opn LIKE 'MAX20029B%' ORDER BY o.opn LIMIT 10;
```

### 步骤 5～7：lumy_split → bge_embedding → milvus（链路 A，语义索引）

**切分发生在导入时，一次性完成**——具体位置在链路 B 全部走完（pg_import）之后，拿到 models.json 的家族清单再开始切（家族名要写进每个 chunk 的元数据）。查询时**不做任何切分**，检索的都是导入时切好的块。

分块**不走 MinerU**：pdfplumber 产物已经含"页文本 + 表格 + 页码"，直接分块就天然得到页码精确的切片；~~MinerU~~ 转出 markdown 反而要二次恢复页码。切分原则按块类型分两套：

**表格块（一表一块，超长再切）**：
- 每个表格线性化成文本：第一行 `列: 表头 | 表头 | ...`，之后每行数据一条 ` | ` 分隔记录，块开头标 `[表格:标题](第N页)`。
- 超过 **25 行**的表切片，**每片都重复表头**——保证每个切片脱离上下文也独立可读（规格书里三四十行的参数大表很常见）。
- 跨页合并过的续表在这里按合并后的整表处理，所以一个长表不会被页边界切成两半。

**文本块（段落累积成块）**：
- 逐页逐行累积，到约 **700 字符**封一块（目标值不是硬上限，凑过线就切）。
- 短于 **120 字符**的尾块并入下一块，避免产生碎片块。
- **页眉页脚剔除**：一行文本在 ≥50% 的页面（至少 3 页）重复出现，判定为页眉页脚，切分前直接丢弃（实测 dcrcw 剔了 5 行、lm317/max20029 各 2 行）。 

**每个 chunk 携带的元数据**：`page / page_end`（页码，答案引用全靠它）、`file_title`（文件名 stem）、`item_name`（该 PDF 全部家族名的逗号拼接串）、`title`（块首行）。这里有个设计细节：**查询侧过滤用的是 file_title 而不是 item_name**——多家族 PDF 的 item_name 是拼接串（"CRCW0402,CRCW0603,..."），Milvus 的 `in` 是精确匹配，拿它过滤必漏；file_title 是单一值，才能做标量过滤。

**向量化**：嵌入输入不是裸 content，而是 `item_name + "\n" + content`——把家族名拼进嵌入文本，提高"问家族名"时整篇块的召回。BGE-M3 模型同时产出 dense + sparse 两种向量（dense 管语义、sparse 管关键词命中），每批 20 条。入库到**独立集合** `kb_lumy_chunks_v1`（不复用 brain 的集合，两套数据不混存），主键 `auto_id` 自增。

**实测数据（正式批量导入，import_all.log 为证）**：

| PDF | 总块数 | 表格块 | 文本块 | 页眉页脚剔除 |
|---|---|---|---|---|
| dcrcw（10 页） | 34 | 17 | 17 | 5 行 |
| lm317 | 94 | 40 | 54 | 2 行 |
| lm358 | 156 | 77 | 79 | 0 行 |
| max20029-max20029d | 47 | 18 | 29 | 2 行 |
| tl431 | 165 | 83 | 82 | 0 行 |
| **合计** | **496** | 235 | 261 | — |

块长分布：中位数约 750 字符（正文字块贴着 700 目标值），最长 ~7.5K（max20029 一个未切片的大表）。

> ⚠️ **已知问题：Milvus 重复入库**。PG 入库是幂等的（同文件先 DELETE 再 INSERT），但 Milvus 节点是纯 insert + auto_id 主键，**没有按文件清理旧数据的逻辑**——重跑导入会累积重复块。当前集合实测 577 条 = 正式批次的 496 + 早期开发时重复导入的 dcrcw(34) 和 max20029-max20029d(47)。检索侧影响有限（重复块只是多占配额、RRF 里同一内容不同 id 不叠分），但如需干净数据，应先 drop 集合再整批重导。

### 附：export-models —— eval/lumy_models.jsonl 是怎么来的

`eval/lumy_models.jsonl`（5 行，一行一份 PDF）**不是提取过程直接产出的，而是从 PostgreSQL 导出的快照**，由 CLI 的 export-models 子命令生成（`knowledge/cli.py` 的 `cmd_export_models`）：

```bash
python -m knowledge.cli export-models          # 默认输出 eval/lumy_models.jsonl
```

它不重跑任何提取，纯 SQL 导出：先 `SELECT id, file_name FROM pdf_sources` 枚举已导入的 PDF；再对每份 PDF 按 `pdf_id` 查四张子表（families / ppns / opns / naming_rules，各按名称排序），`ppns.attributes` 的 JSONB 原样带出；最后每份 PDF 拼成一个 dict 写一行 JSONL。

完整血缘链：

```
PDF
 → pdfplumber 抽表格/正文        (pdf_table_extract)
 → 锚点+LLM 区域标注              (region_label)
 → 规则枚举+LLM语义+三重校验      (model_extract)  ← models.json（落盘中间产物）
 → 幂等入库                       (pg_import)      ← PostgreSQL（权威存储）
 → export-models 四条SQL平铺导出  (cli.py)         ← eval/lumy_models.jsonl（交付快照）
```

也就是说，jsonl 每行 = 导出时刻 PG 里该 PDF 的四层型号数据全量，内容与 `referencePDF/lumy_extract/*/models.json` 一致。它是给评测/交付用的**扁平快照**——上游重新导入后需要重新执行 export-models 才会更新，文件不会自动同步。

---

## 三、查询链路：用户提问之后发生了什么

查询图：`intent_entity → structured_lookup → (search_embedding ∥ search_embedding_hyde) → rrf → rerank → answer_output`。

### 步骤 1：intent_entity —— LLM 意图识别 + 实体抽取 + 查询改写

当用户提问，先做意图识别。意图分成 **6 大类**（这 6 个类别是笔试题要求的）：`model_list`（问某系列有哪些型号）、`model_detail`（问具体型号的信息）、`rule_explain`（问命名规则/后缀含义）、`param_query`（问参数）、`cross_compare`（跨型号/跨文档比较）、`no_answer`（明显超纲，如价格、交期、库存）。

这里用 LLM 做，具体流程是：把最近 6 条历史对话 + 当前问题套进 prompt，让 LLM 输出一个严格 JSON：`{intent, models, params, files, rewritten_query}`。models 保留原样包括后缀（`MAX20029ATIA/V+` 不能被截断）；rewritten_query 是补全指代后的完整问题（"它的耐压是多少" → "LM317 的耐压是多少"）。失败安全降级为 `param_query`——走向量检索兜底，识别挂了不至于整条链路报错。

### 步骤 2：structured_lookup —— 结构化查询（就是查 PostgreSQL）

什么是结构化查询呢，就是拿上一步抽出的型号实体去查 PG 型号库，产出带证据页码的 `structured_docs`。

**结构化查询和向量检索的关系是串行的**：结构化查询先行，因为它除了产出证据之外，还有一个副作用——从命中的型号反查出**所在文件清单**（entity_files），这份清单接下来会作为向量检索的过滤条件。也就是说结构化查询为语义检索"圈定了文档范围"。

具体对齐策略是**严格对齐优先，失败降级前缀对齐**：

- 严格对齐：先查 OPN 精确匹配，再查 PPN 精确，再查家族精确。命中即返回（带文件名、证据页码、封装、包装、JSONB 属性）。
- 前缀对齐（通配下沉）：严格匹配全部落空时，说明用户输入的是前缀或家族名，`LIKE 'token%'` 列出下一级清单——输入家族名就列出它的 PPN 们，输入 PPN 就列出它的 OPN 们。

另外按意图做定向补充：`model_list` 意图额外查"家族 → PPN 清单（带每个 PPN 的 OPN 计数）"；`rule_explain` 意图额外查 naming_rules 文法表（逐段含义）。一次最多处理 4 个型号 token，防止实体爆炸。

### 步骤 3：multi_search 分发 —— 向量检索与 HyDE 检索双路并行

结构化查询结束后进入检索分发。这里有两路，**这两路之间是并行的**（LangGraph 从 multi_search 虚节点同时扇出两条边）：

- **向量检索（search_embedding）**：用改写后的问题做 embedding，在 Milvus 的 lumy 集合里检索。过滤表达式是 `file_title in [结构化命中的文件]`；结构化没命中任何文件时不加过滤、全库检索。
- **HyDE 检索（search_embedding_hyde）**：先让 LLM 针对问题生成一篇"假设答案文档"（用长超时客户端——假设文档生成偶发超时），再用这篇假设文档做 embedding 去检索。直觉是：答案和文档片段的向量相似度，往往比问题和文档片段的相似度更高（问题问法千奇百怪，答案长得都像文档）。

### 步骤 4：join → rrf —— 两路结果融合

两路检索汇合（join 虚节点）后，用 **RRF（Reciprocal Rank Fusion）** 融合：每个 chunk 的得分 = Σ 权重 / (60 + 该 chunk 在本路的排名)，两路权重各 1.0。同一个 chunk 两路都命中就叠加得分，按总分降序。RRF 的好处是只用排名不用原始分——两路检索的分数量纲完全不同，直接相加没有意义。

### 步骤 5：rerank —— BGE 精排

RRF 之后用 BGE-Reranker 做精排（cross-encoder 对"问题-文档"对逐一打分，比双塔 embedding 准）。CPU 模式下 reranker 推理慢（50-100ms/篇），所以限制最多输入 20 篇（按 RRF 得分取头部）。精排后的 `reranked_docs` 携带 `page / page_end / file_title` 证据字段——答案引用页码全靠它们。

### 步骤 6：answer_output —— 拒答闸门 + 证据引用式生成

最后一步是答案生成节点，先过**双源拒答闸门**：

- 结构化检索命中了任何记录 → 视为证据充分，直接放行（哪怕向量检索全空——"TL432 有哪些 PPN"这种问题 PG 一条 SQL 就是完整答案，不需要向量证据）。
- 结构化为空时看向量侧：reranked_docs 为空，或 top1 分数低于拒答阈值（0.4）→ 拒答，返回"未找到足够相关的资料 + 建议（确认型号拼写/确认文档已导入）"。宁可不答，不编造。

通过闸门后构建 prompt，上下文是**两部分拼接**：结构化检索结果（型号库精确数据，带页码）+ 向量检索片段（规格书原文，带文件与页码，按预算截断）。prompt 里写死了**证据契约**：每条事实性结论必须标注 `[文件名 第N页]` 或 `[型号库]`；参数必须保留数值+单位+测试条件+typ/max 属性，原文没有的不许编；跨文档比较要分列来源，数据冲突要明示。

生成用长超时纯文本客户端（长清单类答案如"TL432 的 20 个 PPN 罗列"会超过 30s；且必须关 JSON 模式，否则答案被当 JSON 解析）。支持 SSE 流式逐字输出，流式中断自动降级为整段生成，保证一定有答案。最后把问答对写入 MongoDB 历史。

---

## 四、一图流总结

```
导入（每份 PDF）:
  pdfplumber 抽表格+正文(+页码, 跨页续表合并)          ← pdf_tables.json
    → 锚点+LLM 区域标注                                 ← regions.json
    → 规则枚举 + LLM 语义 + 源文锚定/封面/复核三重校验    ← models.json (四层型号)
    → PostgreSQL (pdf_sources ← families/ppns/opns/naming_rules, JSONB attributes)
    → 分块(表格线性化/正文700字符, 带页码) → BGE向量 → Milvus kb_lumy_chunks_v1
    → [交付快照] cli export-models: PG四表平铺导出 eval/lumy_models.jsonl

查询（每个问题）:
  LLM 意图识别(6类) + 实体抽取 + 查询改写
    → 结构化查询 PG (严格对齐→前缀对齐; 产出证据+entity_files文件过滤)   ┐串行
    → 向量检索 ∥ HyDE 检索 (Milvus, file_title 过滤)                     ┘先B后A
    → RRF 融合 (rank-based, 两路各权重1.0)
    → BGE Reranker 精排 (≤20篇, 带页码证据字段)
    → 双源拒答闸门 (结构化命中即充分; 否则向量top1≥0.4)
    → 证据契约生成 ([文件 第N页]/[型号库] 引用, 参数保留单位与条件)
```

设计上最核心的一条主线：**能用确定性规则的绝不用 LLM（锚点、规则枚举、反规则过滤、前缀对齐），LLM 只用在语义判断的刀刃上（区域划界、四层判定、意图识别、假设文档、答案生成），且每个 LLM 输出都被确定性校验兜底（锚点纠偏、源文锚定、封面交叉校验、安全降级）。**
