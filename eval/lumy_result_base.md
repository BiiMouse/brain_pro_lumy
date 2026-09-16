# Lumy 自测问答结果-改用reranker-base模型后

- 总题数: 13，通过: 13，通过率: 100%

| ID | 类型 | 问题 | 结果 | 失败原因 | 用时 |
|---|---|---|---|---|---|
| Q1 | model_list | MAX20029B系列包含哪些产品型号？ | ✓ |  | 69s |
| Q2 | model_list | TL432 家族有哪些精度与温度等级组合的型号？ | ✓ |  | 57s |
| Q3 | model_detail | TL432BIDBZR 属于哪个产品家族和PPN？封装是什么 | ✓ |  | 31s |
| Q4 | model_detail | LM317DCYG3 对应的 PPN 是什么？DCY 是什么 | ✓ |  | 27s |
| Q5 | rule_explain | MAX20029ATIA/V+ 型号的后缀 /V+ 代表什么 | ✓ |  | 49s |
| Q6 | rule_explain | LM317 的命名规则 LM317yyyz 中 yyy 和  | ✓ |  | 54s |
| Q7 | param_query | MAX20029 的输入电压工作范围是多少？ | ✓ |  | 39s |
| Q8 | param_query | LM358B 的供电电压范围和每通道静态电流是多少？ | ✓ |  | 33s |
| Q9 | param_query | TL431 B 等级在 25°C 时的基准电压容差是多少？ | ✓ |  | 25s |
| Q10 | cross_compare | MAX20029 和 LM317 的封装有什么差异？ | ✓ |  | 50s |
| Q11 | cross_compare | LM358B 和 LM2904 的供电电压范围有什么差异？ | ✓ |  | 41s |
| Q12 | no_answer | TL431 的价格是多少？ | ✓ |  | 24s |
| Q13 | no_answer | LM317 现在的库存和交期怎么样？ | ✓ |  | 35s |

## Q1 MAX20029B系列包含哪些产品型号？
- 意图: model_list  用时: 69s
```
根据结构化型号库，**MAX20029B 系列包含以下 7 个产品型号（PPN）**：

| 序号 | 产品型号（PPN） | 来源 |
|---|---|---|
| 1 | MAX20029BATIA | [型号库] |
| 2 | MAX20029BATIB | [型号库] |
| 3 | MAX20029BATIC | [型号库] |
| 4 | MAX20029BATID | [型号库] |
| 5 | MAX20029BATIE | [型号库] |
| 6 | MAX20029BATIF | [型号库] |
| 7 | MAX20029BATIH | [型号库] |

规格书《Ordering Information》中，MAX20029B 对应的订购信息写法为：

| PART | TEMP RANGE | PIN-PACKAGE | 来源 |
|---|---|---|---|
| MAX20029BATI_/V+ | -40°C to +125°C | 28 TQFN-EP* | [max20029-max20029d 第17页] |

说明：规格书第17页只列出 **MAX20029BATI_/V+** 这种带下划线的形式；检索结果中未给出上述 7 个具体 PPN 后缀 A、B、C、D、E、F、H 与规格书订购型号之间的逐项对应关系。
```

## Q2 TL432 家族有哪些精度与温度等级组合的型号？
- 意图: model_list  用时: 57s
```
依据【型号库】的 TL432 家族 PPN 列表，并结合规格书中精度/温度代码定义，TL432 家族中可识别的“精度等级 × 温度等级”组合型号共有 9 个：

| 精度等级（初始容差 @25°C） | 温度等级（工作 free-air 温度） | 组合型号 |
|---|---|---|
| B：0.5% [tl431.pdf 第1页][tl431.pdf 第21页] | C：0°C to 70°C [tl431.pdf 第3页] | TL432BC [型号库] |
| B：0.5% [tl431.pdf 第1页][tl431.pdf 第21页] | I：-40°C to 85°C [tl431.pdf 第3页] | TL432BI [型号库] |
| B：0.5% [tl431.pdf 第1页][tl431.pdf 第21页] | Q：-40°C to 125°C [tl431.pdf 第3页] | TL432BQ [型号库] |
| A：1% [tl431.pdf 第1页][tl431.pdf 第21页] | C：0°C to 70°C [tl431.pdf 第3页] | TL432AC [型号库] |
| A：1% [tl431.pdf 第1页][tl431.pdf 第21页] | I：-40°C to 85°C [tl431.pdf 第3页] | TL432AI [型号库] |
| A：1% [tl431.pdf 第1页][tl431.pdf 第21页] | Q：-40°C to 125°C [tl431.pdf 第3页] | TL432AQ [型号库] |
| Blank/标准：2% [tl431.pdf 第1页][tl431.pdf 第21页] | C：0°C to 70°C [tl431.pdf 第3页] | TL432C [型号库] |
| Blank/标准：2% [tl431.pdf 第1页][tl431.pdf 第21页] | I：-40°C to 85°C [tl431.pdf 第3页] | TL432I [型号库] |
| Blank/标准：2% [tl431.pdf 第1页][tl431.pdf 第21页] | Q：-40°C to 125°C [tl431.pdf 第3页] | TL432Q [型号库] |

说明：  
- 精度代码：B = 0.5%，A = 1%，Blank/标准 = 2%，文档标注为 25°C 下的参考电压容差/初始容差；原文未以 typ/max/min 标注该容差，因此不补充该属性。[tl431.pdf 第1页][tl431.pdf 第21页]  
- 温度代码：C = 0°C to 70°C，I = -40°C to 85°C，Q = -40°C to 125°C。[tl431.pdf 第3页][tl4
```

## Q3 TL432BIDBZR 属于哪个产品家族和PPN？封装是什么？
- 意图: model_detail  用时: 31s
```
- **产品家族（family）**：TL432 [型号库]
- **PPN**：TL432BI [型号库]
- **封装**：SOT-23 (DBZ)，3 引脚 [型号库]；规格书原文中 TL432BIDBZR 也列为 SOT-23 (DBZ)、Pins 3 [tl431.pdf 第46页]

补充：其包装信息为 3000 | LARGE T&R [型号库]，文档中也显示 Package qty 3000、Carrier LARGE T&R [tl431.pdf 第46页]。
```

## Q4 LM317DCYG3 对应的 PPN 是什么？DCY 是什么封装？
- 意图: model_detail  用时: 27s
```
- **LM317DCYG3 对应的 PPN**：**LM317**  
  来源：[型号库]

- **DCY 是什么封装**：**DCY 是 SOT-223 封装代码，引脚数为 4**。  
  来源：[型号库]；文档中也列为 `Package: SOT-223 (DCY)`、`Pins: 4`：[lm317 第30页]。  
  文档第1页进一步标注为 `DCY (SOT-223, 4)`，封装尺寸为 **6.5mm × 7mm**：[lm317 第1页]。

补充：LM317DCYG3 的包装信息为 **80 | TUBE**：[型号库]；文档第30页也显示 `Package qty: 80`、`Carrier: TUBE`：[lm317 第30页]。
```

## Q5 MAX20029ATIA/V+ 型号的后缀 /V+ 代表什么含义？
- 意图: rule_explain  用时: 49s
```
MAX20029ATIA/V+ 的后缀 **“/V+”** 不是单一代码，而是由 **“/V”** 和 **“+”** 两部分组成：

| 后缀片段 | 含义 | 来源 |
|---|---|---|
| **/V** | 表示汽车级器件（automotive-qualified），符合 **AEC-Q100** | [max20029-max20029d 第16页] |
| **+** | 表示封装为 **无铅（Pb-free）/RoHS 合规** | [max20029-max20029d 第16页] |

因此，**“/V+”整体表示：该型号为汽车级、符合 AEC-Q100，且采用无铅/RoHS 合规封装。**  
结构化命名规则中也将 **“/V+”** 整体归类为 **Environmental/ordering suffix（automotive, lead-free）**：[型号库: max20029-max20029d.pdf 第17页]。

以上信息未发现冲突。
```

## Q6 LM317 的命名规则 LM317yyyz 中 yyy 和 z 分别代表什么？
- 意图: rule_explain  用时: 54s
```
根据 LM317 的命名规则 `LM317yyyz`：

| 片段 | 含义 | 示例/说明 | 来源 |
|---|---|---|---|
| `yyy` | 封装代码（Package designator） | `DCY`=SOT-223，`KCS`=TO-220，`KTT`=TO-263 | [型号库]；[lm317.pdf 第28页] |
| `z` | 封装数量/包装代码（Package quantity designator） | `R`=大卷带，空=管装 | [型号库]；[lm317.pdf 第28页] |

规格书原文也明确写明：`yyy is the package designator. z is the package quantity designator.` [lm317.pdf 第28页]

因此，`LM317yyyz` 中的 `yyy` 表示封装代码，`z` 表示封装数量/包装代码。
```

## Q7 MAX20029 的输入电压工作范围是多少？
- 意图: param_query  用时: 39s
```
MAX20029 的输入（供电）工作范围为 **3.0V 至 5.5V**。

- 参数：Supply Voltage Range，符号 **VPV_**
- 条件：**Fully operational**
- 最小值：**3.0V**
- 最大值：**5.5V**
- 典型值：规格书检索片段中未给出 typ  
来源：[max20029-max20029d 第3页]

补充：结构化检索结果只说明 MAX20029 是四路降压 DC-DC 转换器、输出 1V 至 4.0V、最多四路 1.5A，未直接给出输入电压范围 [型号库]。
```

## Q8 LM358B 的供电电压范围和每通道静态电流是多少？
- 意图: param_query  用时: 33s
```
LM358B 的参数如下：

| 参数 | 数值 | 属性/条件 | 来源 |
|---|---:|---|---|
| 供电电压范围 | 3 V 到 36 V | 推荐工作条件；VS = ([V+] – [V–])；最小 3 V，最大 36 V | [lm358 第5页]；Family Comparison 也列为 3 to 36 V [lm358 第1页]；结构化属性 `supply_voltage: 3 to 36 V` [型号库] |
| 每通道供电电流/静态电流 | 0.3 mA | 典型值 typ，per channel；检索结果未给出最大值、最小值或测试条件 | [lm358 第1页]；结构化属性 `supply_current_typ_per_ch: 0.3 mA` [型号库] |

补充说明：绝对最大供电电压额定值另有规定为 ±20 V 或 40 V [lm358 第4页]，但这不是推荐工作电压范围。
```

## Q9 TL431 B 等级在 25°C 时的基准电压容差是多少？
- 意图: param_query  用时: 25s
```
TL431 **B 等级**在 **25°C** 时的基准电压容差为：

| 参数 | 数值 | 测试条件 | 等级 | 来源 |
|---|---:|---|---|---|
| Reference voltage tolerance at 25°C | **0.5%** | 25°C | B grade | [tl431 第1页] |

说明：检索到的规格书原文将该容差列为 **0.5% (B grade)**；原文未标注其为 typ、max 或 min，因此不额外推断属性。
```

## Q10 MAX20029 和 LM317 的封装有什么差异？
- 意图: cross_compare  用时: 50s
```
核心结论：MAX20029 在检索到的订购信息中为 **28 TQFN-EP*** 封装；LM317 不是单一封装，而是可选 **SOT-223(DCY)、TO-263(KTT)、TO-220(KCS,KCT)** 多种封装 [型号库]。因此两者封装体系差异明显。

| 对比项 | MAX20029 | LM317 |
|---|---|---|
| 封装类型 | **28 TQFN-EP*** [max20029-max20029d 第17页] | 封装选项：**SOT-223(DCY)、TO-263(KTT)、TO-220(KCS,KCT)** [型号库] |
| 引脚数 | **28** [max20029-max20029d 第17页] | SOT-223：4；TO-263：3；TO-220：原文“3 (3)” [lm317 第1页] |
| 封装尺寸 | 本次检索结果中未找到 MAX20029 的封装外形尺寸 | SOT-223：**6.5mm × 7mm**；TO-263：**10.16mm × 15.24mm**；TO-220：**10.16mm × 4.55mm** [lm317 第1页] |
| 封装代码/机械编号 | Package Code：**T2855+5/T2855+5C**；Outline Number：**21-0140**；Land Pattern Number：**90-0027** [max20029-max20029d 第3页] | 本次检索结果中未给出与 MAX20029 对应的 TQFN 类机械编号 |
| 热阻 | 四层板条件：Junction to Ambient **θJA = 35°C/W**；Junction to Case **θJC = 3°C/W** [max20029-max20029d 第3页] | 本次检索结果中未找到 LM317 的热阻参数 |
| 订购/温度信息 | 订购信息中温度范围为 **-40°C to +125°C** [max20029-max20029d 第17页] | 推荐工作温度：**0 to 125 °C** [型号库] |

差异要点：
- MAX20029 是 **28 引脚 TQFN-EP*** 封装，文档中列出的订购型号均为该封装 [max20029-max20029d 第17页]。
- LM317 是 **多封装可选**：SOT-223、TO-263、TO-220，且不同封装引脚数和尺寸不同 [型号库][lm317 第1页]。
- MAX20029 提供了四层板热阻数据 [max20029-max20029d 第3页]；LM317 在本次检索结果中未找到热阻数据，因此无法直接比较热性能。
- MAX20029 的封装外形尺寸在本次检索结果中未找到；LM317 则
```

## Q11 LM358B 和 LM2904 的供电电压范围有什么差异？
- 意图: cross_compare  用时: 41s
```
按基础型号 **LM2904**（非 LM2904B/BA）比较：

| 型号 | 供电电压范围 | 属性 | 来源 |
|---|---|---:|---|
| LM358B | 3 V 至 36 V | 最小 3 V，最大 36 V | [型号库]；[lm358 第1页]；[lm358 第5页]（over operating ambient temperature range 条件下） |
| LM2904 | 3 V 至 26 V | 最小 3 V，最大 26 V | [型号库]；[lm358 第1页]；[lm358 第5页]（over operating ambient temperature range 条件下） |

**主要差异：**

1. **下限相同**：LM358B 和 LM2904 的供电电压最小值均为 **3 V**。  
   来源：[型号库]；[lm358 第1页]；[lm358 第5页]

2. **上限不同**：  
   - LM358B 最大供电电压为 **36 V**；  
   - LM2904 最大供电电压为 **26 V**。  
   因此 LM358B 的上限比 LM2904 高 **10 V**。  
   来源：[型号库]；[lm358 第1页]；[lm358 第5页]

3. **结论**：LM358B 的供电电压范围更宽，高压侧更高；LM2904 的高压侧较低。  
   来源：[型号库]；[lm358 第1页]；[lm358 第5页]

**注意区分：**

- **LM2904B / LM2904BA** 的供电电压范围是 **3 V 至 36 V**，与基础型号 **LM2904** 不同。  
  来源：[lm358 第1页]；[lm358 第5页]

- 绝对最大额定值方面：  
  - LM358B / LM358BA / LM2904B / LM2904BA：供电电压 **±20 V 或 40 V**；  
  - LM2904：供电电压 **±13 V 或 26 V**。  
  这是绝对最大额定值，不是推荐工作范围。  
  来源：[lm358 第4页]

结构化型号库与规格书文档在 LM358B、LM2904 的推荐供电电压范围上一致，未发现冲突。
```

## Q12 TL431 的价格是多少？
- 意图: no_answer  用时: 24s
```
知识库中未找到 TL431 的价格信息，因此无法给出具体价格或价格区间。

依据如下：

- 结构化型号库中仅检索到型号 `TL431`，其 `attributes` 为空，未包含价格字段：[型号库]
- 规格书中的订购信息表包含的是可订购料号、状态、封装、引脚数、包装数量、载体、RoHS、铅工艺/球材料、MSL、工作温度和丝印等信息，但**没有价格列**：[tl431.pdf 第36页]、[tl431.pdf 第42页]、[tl431.pdf 第35页]、[tl431.pdf 第37页]、[tl431.pdf 第38页]
- 文档检索结果中还包含应用/测试电路、目录、引脚配置等内容，也未出现价格信息：[tl431.pdf 第16页]、[tl431.pdf 第2页]

缺少的信息包括：  
- TL431 或其具体可订购料号的价格/报价  
- 币种  
- 采购数量对应的阶梯价格  
- 分销渠道、地区、有效期等价格条件  

因此，按当前知识库内容，不能回答“TL431 的价格是多少”。建议查询 TI 官网、授权分销商或采购渠道获取实时报价。
```

## Q13 LM317 现在的库存和交期怎么样？
- 意图: no_answer  用时: 35s
```
结论：知识库中未找到 LM317 当前库存和交期的相关信息，因此无法判断“库存和交期怎么样”。结构化数据仅含型号/参数，文档包装信息表也未提供实时库存、交期或发货日期 [型号库] [lm317.pdf 第30页]。

可查到的相关信息如下，但这些都不等同于库存或交期：

- 结构化型号库中，LM317 属性包含：封装选项 SOT-223(DCY)/TO-263(KTT)/TO-220(KCS,KCT)、输出电流 1.5A、输入电压范围 4.25 to 40 V、PSRR(120Hz) 64 dB、负载调整率精度 1.5%、推荐工作温度 0 to 125 °C、芯片版本 Legacy Chip [型号库]。  
  其中没有库存数量、可售库存、交期/lead time 字段 [型号库]。

- 文档第30页包装信息表列出的是生命周期状态、物料类型、包装数量、载带方式等，例如：
  - LM317DCY：Status Active，Material type Production，SOT-223(DCY)，4 pins，Package qty 80，Carrier TUBE，Op temp 0 to 125 °C [lm317.pdf 第30页]。
  - LM317DCYR：Status Active，Material type Production，SOT-223(DCY)，4 pins，Package qty 2500，Carrier LARGE T&R，Op temp 0 to 125 °C [lm317.pdf 第30页]。
  - LM317KCS：Status NRND，Material type Production，TO-220(KCS)，3 pins，Package qty 50，Carrier TUBE，Op temp 0 to 125 °C [lm317.pdf 第30页]。
  - LM317KTTR：Status Active，Material type Production，DDPAK/TO-263(KTT)，3 pins，Package qty 500，Carrier LARGE T&R，Op temp 0 to 125 °C [lm317.pdf 第30页]。

- 上述 Status 是产品生命周期状态，不是库存数量；Material type Production 表示生产料，不是可售库存；Package qty 是包装数量，不是库存或交期 [lm317.pdf 第30页]。

缺少的信息包括：实时库存数量、可售库存、库存地点、分销商库存、交期/lead time、预计发货日期、订单排期、MOQ/MPQ 等。因此，若需判断“现在的库存和交期”，需要查询实时库存/交期系统或供应商，知识库中未找到相关信息 [型号库] [lm31
```
