# Lumy 自测问答结果

- 总题数: 13，通过: 13，通过率: 100%
## Q1 MAX20029B系列包含哪些产品型号？
```
MAX20029B 系列在型号库中列出的具体 PPN/产品型号共 7 个，均来自 [max20029-max20029d.pdf 第16页][型号库]，每项 `opn_count` 为 1：

| 序号 | 型号 |
|---|---|
| 1 | MAX20029BATIA |
| 2 | MAX20029BATIB |
| 3 | MAX20029BATIC |
| 4 | MAX20029BATID |
| 5 | MAX20029BATIE |
| 6 | MAX20029BATIF |
| 7 | MAX20029BATIH |

规格书订购信息中，MAX20029B 系列对应条目写作 `MAX20029BATI_/V+`，温度范围为 `-40°C to +125°C`，封装为 `28 TQFN-EP*` [max20029-max20029d 第17页]。

说明：规格书检索片段以 `MAX20029BATI_/V+` 形式列出订购项，其中后缀未在片段中逐一展开；结构化型号库则列出了具体后缀 A、B、C、D、E、F、H。两者无冲突。
```

## Q2 TL432 家族有哪些精度与温度等级组合的型号？
```
**结论**：按 [型号库] 的 TL432 家族 PPN 列表，以及 [tl431.pdf 第3页]、[tl431.pdf 第32页] 的型号解码规则，TL432 家族可辨识出 **9 个“初始精度 × 工作温度”后缀组合型号**。无后缀基础 PPN `TL432` 未给出精度/温度后缀，不能确定其组合等级。

**代码含义**

- 初始精度/参考电压容差，条件为 **25°C**：  
  - `B` = **0.5%**  
  - `A` = **1%**  
  - `Blank` = **2%**  
  来源：[tl431.pdf 第1页]、[tl431.pdf 第3页]、[tl431.pdf 第32页]。原文未标注 typ/max/min 属性。
- 工作自由空气温度 `T_A`：  
  - `C` = **0°C to 70°C**  
  - `I` = **-40°C to 85°C**  
  - `Q` = **-40°C to 125°C**  
  来源：[tl431.pdf 第3页]、[tl431.pdf 第32页]。原文未标注 typ/max/min 属性。
- `Blank` 精度在型号中不写 `A/B`，例如 `TL432C` 表示 Blank 精度 + C 温度等级。来源：[tl431.pdf 第32页]。

**TL432 精度与温度等级组合型号表**

| 型号/PPN | 精度代码 / 初始精度（25°C） | 温度代码 / 工作自由空气温度 `T_A` | 证据 |
|---|---|---|---|
| `TL432BC` | `B` / **0.5%** | `C` / **0°C to 70°C** | 型号：[型号库]；精度/温度释义：[tl431.pdf 第3页]、[tl431.pdf 第32页] |
| `TL432BI` | `B` / **0.5%** | `I` / **-40°C to 85°C** | 型号：[型号库]；精度/温度释义：[tl431.pdf 第3页]、[tl431.pdf 第32页] |
| `TL432BQ` | `B` / **0.5%** | `Q` / **-40°C to 125°C** | 型号：[型号库]；精度/温度释义：[tl431.pdf 第3页]、[tl431.pdf 第32页] |
| `TL432AC` | `A` / **1%** | `C` / **0°C to 70°C** | 型号：[型号库]；精度/温度释义：[tl431.pdf 第3页]、[tl431.pdf 第32页] |
| `TL432AI` | `A` / **1%** | `I` / **-40°C to 85°C** | 型号：[型号库]；精度/温度释义：[tl431.pd
```

## Q3 TL432BIDBZR 属于哪个产品家族和PPN？封装是什么？
```
| 项目 | 结果 | 来源 |
|---|---|---|
| 产品家族（family） | TL432 | [型号库] |
| PPN | TL432BI | [型号库] |
| 封装 | SOT-23 (DBZ)，3 引脚 | [型号库]；[tl431 第46页] |

补充：文档第46页也列出 **TL432BIDBZR** 的封装为 **SOT-23 (DBZ)**、Pins 为 **3**，包装数量为 **3000**，载带为 **LARGE T&R**。[tl431 第46页]
```

## Q4 LM317DCYG3 对应的 PPN 是什么？DCY 是什么封装？
```
结论先说清楚口径差异：

| 口径 | 结果 | 来源 |
|---|---|---|
| 型号库中的 `opn` | `LM317DCYG3` | [型号库] |
| 型号库中的 `ppn` 字段 | `LM317` | [型号库] |
| 文档中 “Orderable part number / 可订购料号” | `LM317DCYG3` | [lm317 第30页] |

因此：

1. **如果你说的“PPN”是型号库字段名**：  
   `LM317DCYG3` 对应的 `ppn` 是 **`LM317`**。  
   同时型号库给出：`family = LM317`，`package = SOT-223 (DCY) | 4`，`packing = 80 | TUBE`。[型号库]

2. **如果你说的“PPN（可订购料号）”是指文档里的 Orderable part number**：  
   `LM317DCYG3` 本身就是可订购料号；文档第30页 “PACKAGING INFORMATION” 表中，`LM317DCYG3` 列在 `Orderable part number` 下，封装为 `SOT-223 (DCY)`，引脚数 `4`，包装数量 `80`，载体 `TUBE`，状态 `Active`，工作温度 `0 to 125°C`。[lm317 第30页]

3. **后缀 `DCY` 代表什么封装**：  
   `DCY` 代表 **SOT-223 封装，4 引脚**。  
   - 文档第30页：`LM317DCYG3` 的 Package 为 `SOT-223 (DCY)`，Pins 为 `4`。[lm317 第30页]  
   - 文档第34页：`LM317DCYG3 | DCY | SOT-223 | 4 | 80`。[lm317 第34页]  
   - 文档第1页 Package Information：`LM317 | DCY (SOT-223, 4) | 6.5mm × 7mm`。[lm317 第1页]  
   - 型号库：`package = SOT-223 (DCY) | 4`。[型号库]

所以可概括为：  
**可订购料号：`LM317DCYG3`；型号库 `ppn` 字段：`LM317`；后缀 `DCY` = SOT-223，4 引脚封装。**
```

## Q5 MAX20029ATIA/V+ 型号的后缀 /V+ 代表什么含义？
```
MAX20029ATIA/V+ 中的 **“/V+”是环境/订购后缀**，由两部分组成：

| 后缀部分 | 含义 | 来源 |
|---|---|---|
| `/V` | 表示汽车级合格器件，符合 **AEC-Q100** | [max20029-max20029d.pdf 第16页] |
| `+` | 表示 **无铅（Pb-free）/RoHS 合规封装** | [max20029-max20029d.pdf 第16页] |
| `/V+` | 合起来归类为 Environmental/ordering suffix，含义为：**汽车级、无铅** | [型号库] |

因此，**MAX20029ATIA/V+ 的“/V+”表示：该型号为汽车级、符合 AEC-Q100，并采用无铅/RoHS 合规封装。**  
[max20029-max20029d.pdf 第16页] [型号库]

补充说明：  
- MAX20029ATIA/V+ 中，`/V+` 前面的 `A` 不是 `/V+` 的一部分。按命名规则，它对应空白区 `_`，是**工厂可编程输出配置字母**，用于表示 IOUT、VOUT、扩频、PG timeout 等配置。  
  [型号库]  
- 文档也说明：应将所需后缀字母从 Selector Guide 插入空白区 `_`，以表示工厂可选功能。  
  [max20029-max20029d.pdf 第16页]  
- 订购信息表中，`MAX20029ATI_/V+` 的温度范围为 **-40°C to +125°C**，封装为 **28 TQFN-EP***。  
  [max20029-max20029d.pdf 第17页]
```

## Q6 LM317 的命名规则 LM317yyyz 中 yyy 和 z 分别代表什么？
```
在 LM317 的命名规则 `LM317yyyz` 中：

| 字段 | 含义 | 示例 |
|---|---|---|
| `yyy` | 封装代码（Package designator） | `DCY` = SOT-223，`KCS` = TO-220，`KTT` = TO-263 [型号库] [lm317.pdf 第28页] |
| `z` | 封装数量/包装代码（Package quantity designator） | `R` = 大卷带，空 = 管装 [型号库] [lm317.pdf 第28页] |

规格书原文也明确说明：  
`yyy is the package designator. z is the package quantity designator.` [lm317.pdf 第28页]

结构化检索结果与文档检索结果对该命名规则的定义一致，未发现冲突。[型号库] [lm317.pdf 第28页]
```

## Q7 MAX20029 的输入电压工作范围是多少？
```
MAX20029 的输入（供电）电压工作范围：

- 参数：Supply Voltage Range，符号：VPV_
- 条件：Fully operational
- 范围：最小 3.0 V，最大 5.5 V；检索片段中未给出典型值（typ）
- 来源：[max20029-max20029d 第3页]

补充说明：  
[型号库] 中的结构化数据只给出 MAX20029 的输出范围为 1V 到 4.0V、最多四路 1.5A 通道，这不是输入电压范围。输入电压工作范围应以上述规格书第 3 页的 Supply Voltage Range 为准。
```

## Q8 LM358B 的供电电压范围和每通道静态电流是多少？
```
- **供电电压范围**：**3 V 至 36 V**（推荐工作条件中的最小值 3 V、最大值 36 V）[lm358 第5页]；结构化型号库同样给出 **3 to 36 V** [型号库]。

- **每通道静态/电源电流**：**典型值 0.3 mA**（typ，每通道）[lm358 第1页]；结构化型号库同样给出 **0.3 mA** 每通道典型值 [型号库]。

- 检索结果中未给出该 **0.3 mA 的最大值/最小值**，也未显示其额外测试条件；这些信息知识库中未找到。

- 备注：绝对最大额定值中 LM358B 的供电电压为 **±20 V 或 40 V** [lm358 第4页]，不要与推荐工作范围 **3 V 至 36 V** 混淆。
```

## Q9 TL431 B 等级在 25°C 时的基准电压容差是多少？
```
TL431 B 等级在 25°C 时的基准电压（Vref）容差为：**0.5%**。

依据如下：

- **文档原文**：[tl431 第1页] Features 中写明：  
  - Reference voltage tolerance at 25°C  
  - **0.5% (B grade)**
- **型号库数据**：[型号库] 中 TL431BQ、TL431BI、TL431BC 的 `initial_accuracy` 均为：  
  - **0.5% (B)**

补充说明：  
检索片段中 [tl431 第12页] 有 Vref 表格数据：  
- min：**2483 mV**  
- typ：**2495 mV**  
- max：**2507 mV**  
- 测试条件：V_KA = V_ref，I_KA = 10 mA，T_A = 25°C  

但该第12页片段**未直接标注为 B 等级**，因此不能单独作为“B 等级”标签的直接证据。按 [tl431 第1页] 和 [型号库] 的明确标注，TL431 B 等级在 25°C 的 Vref 容差是 **0.5%**。
```

## Q10 MAX20029 和 LM317 的封装有什么差异？
```
结论：在给定资料中，MAX20029 的封装信息集中为 **28 TQFN-EP\***；LM317 则提供多种封装选项：**SOT-223(DCY)、TO-263(KTT)、TO-220(KCS,KCT)**。二者在封装类型、引脚数、可选封装数量及尺寸信息完整度上不同。

| 对比项 | MAX20029 | LM317 |
|---|---|---|
| 封装类型 | 订购信息中列出的型号均为 **28 TQFN-EP\*** [max20029-max20029d 第17页] | 封装选项：**SOT-223(DCY)/TO-263(KTT)/TO-220(KCS,KCT)** [型号库]；与文档 Package Information 一致 [lm317 第1页] |
| 引脚数 | **28**（从“28 TQFN-EP*”读取）[max20029-max20029d 第17页] | SOT-223(DCY)：**4**；TO-263(KTT)：**3**；TO-220(KCS,KCT)：**3** [lm317 第1页] |
| 封装尺寸 | 未在检索结果中给出 TQFN-EP 尺寸、高度、引脚间距等 | DCY (SOT-223, 4)：**6.5mm × 7mm**；KTT (TO-263, 3)：**10.16mm × 15.24mm**；KCS, KCT (TO-220, 3 (3) \| )：**10.16mm × 4.55mm** [lm317 第1页] |
| 封装高度/外型图 | 未在检索结果中给出 | TO-263 KTT0003B：**4.83 mm max height** [lm317 第38页]；TO-220 KCS0003B：**19.65 mm max height** [lm317 第40页] |
| 热焊盘/散热相关 | TQFN 封装底部有 **exposed thermal pad**，用于低热阻散热 [max20029-max20029d 第14页] | TO-263 封装图标注 **EXPOSED METAL** [lm317 第38页]；其他封装未在本次检索结果中说明 |
| 温度范围 | 订购信息中 TEMP RANGE 为 **-40°C to +125°C** [max20029-max20029d 第17页] | 结构化数据中推荐工作温度为 **0 to 125 °C** [型号库]；但这是器件工作温度，不是封装差异 |

主要差异归纳：

1. **MAX20029 是单一封装形态：28 TQFN-EP\***  
   - 给定订购信息中，MAX20029ATI_/V+、MAX20029BATI_/V+、MAX20029CATI_/V+、MAX20029DATI_/V+ 均为 **28 TQ
```

## Q11 LM358B 和 LM2904 的供电电压范围有什么差异？
```
结论对比：

| 型号 | 供电电压范围 | 来源与说明 |
|---|---:|---|
| LM358B | 3 V 至 36 V | [型号库]；文档 Family Comparison 表中 Supply voltage 列也列 LM358B/LM358BA 为 3 to 36 V，单位 V，未标注 typ/max/min [lm358.pdf 第1页] |
| LM2904（非 B） | 3 V 至 26 V | [型号库]；文档 Family Comparison 表中 Supply voltage 列也列 LM2904 为 3 to 26 V，单位 V，未标注 typ/max/min [lm358.pdf 第1页] |

差异要点：

- 下限相同：LM358B 和 LM2904 均为 3 V [型号库；lm358.pdf 第1页]。
- 上限不同：LM358B 为 36 V，LM2904 为 26 V [型号库；lm358.pdf 第1页]。
- 因此 LM358B 的供电电压范围更宽，上限比 LM2904 高 10 V（36 V − 26 V）[基于上述数据计算]。
- 注意不要混淆：LM2904B/LM2904BA 在文档中为 3 V 至 36 V；LM2904V/LM2904AV 为 3 V 至 30 V，单位 V [lm358.pdf 第1页]。

补充：第4页表格中的供电电压额定值项（V_S = ([V+] – [V–])）列的是最大值属性：LM358B/LM358BA、LM2904B/LM2904BA 为 ±20 或 40 V；LM2904 为 ±13 或 26 V，单位 V [lm358.pdf 第4页]。该表标题为 over operating ambient temperature range (unless otherwise noted)，这是最大值额定值信息，不等同于上面的供电电压范围。

数据一致性：型号库与文档第1页 Family Comparison 对 LM358B = 3 V 至 36 V、LM2904 = 3 V 至 26 V 的结论一致，未发现冲突 [型号库；lm358.pdf 第1页]。
```

## Q12 TL431 的价格是多少？
```
知识库中未找到 TL431 的价格信息。

1. **结构化检索结果**
   - 仅显示型号/系列信息：`ppn: TL431`、`family: TL431`，且 `attributes` 为空，未包含价格字段。[型号库]

2. **文档检索结果**
   - 检索到的文档内容主要是 TI 规格书中的订购信息表格，例如：
     - 第42页表格列包括：Orderable part number、Status、Material type、Package、Pins、Package qty、Carrier、RoHS、Lead finish/Ball material、MSL rating/Peak reflow、Op temp、Part marking，但**没有价格列**。[tl431 第42页]
     - 第36页、第43页等也同样是订购、封装、温度、MSL 等信息，未出现价格、货币单位或报价。[tl431 第36页][tl431 第43页]
   - 因此，现有文档检索结果不足以回答价格问题。

3. **缺少的信息**
   - TL431 的具体价格
   - 货币单位
   - 对应数量/起订量
   - 报价日期或有效期
   - 购买渠道或经销商/TI 官方定价信息

结论：**知识库中未找到 TL431 的价格信息**。如需价格，建议查询 TI 官网或授权分销商的实时报价。
```

## Q13 LM317 现在的库存和交期怎么样？
```
**结论：知识库中未找到 LM317 的库存和交期相关信息。**  
现有资料只能查到部分订单状态/包装信息，不能回答“现在的库存数量”或“交期/lead time”。

**依据：**

- 结构化检索结果中，LM317 的字段包括 PSRR、封装选项、芯片版本、输出电流、推荐工作温度、输入电压范围、负载调整率精度；**没有库存、交期字段** [型号库]。
- 文档检索结果第30页为 PACKAGING INFORMATION / Orderable part number 表，列包含 Status、Material type、Package、Pins、Package qty、Carrier、RoHS、Lead finish、MSL、Op temp、Part marking；**没有库存数量或交期/lead time** [lm317 第30页]。
- 第29页仅说明机械、封装和可订购信息，且数据可能变更；**未提供库存或交期** [lm317 第29页]。

**可查到的相关但不等同于库存/交期的信息：**

| 型号 | 第30页可见信息 | 来源 |
|---|---|---|
| LM317DCY | Status=Active，Material type=Production，SOT-223(DCY)，4 pins，Package qty=80 TUBE 或 2500 LARGE T&R | [lm317 第30页] |
| LM317KCS | Status=NRND，Material type=Production，TO-220(KCS)，3 pins，Package qty=50 TUBE | [lm317 第30页] |
| LM317KTTR | Status=Active，Material type=Production，DDPAK/TO-263(KTT)，3 pins，Package qty=500 LARGE T&R | [lm317 第30页] |

注意：上述 `Status` 是产品生命周期/订单状态，`Material type=Production` 表示量产状态，`Package qty` 是包装数量，**都不是实时库存或交期** [lm317 第30页]。

**缺少的信息：**  
实时库存数量、可售库存、在途库存、交期/lead time、发货周期、MOQ 等。要回答“现在”的库存和交期，需要查询实时库存/供应链系统或外部订购渠道；这些信息未包含在当前知识库中。
```
