# DeepSeek + 通义千问VL 配置指南

## 一、模型服务购买指南

### 1. DeepSeek（LLM）

#### A. 检查您已有的模型

您提到有 `deepseek-v4-flash` 和 `v4-pro`，说明已经注册了。

**登录查看：**
```bash
https://platform.deepseek.com/
```

**查看余额：**
- 控制台 → 账户管理
- 查看 API 余额和使用情况

**模型详情：**
- `v4-flash`: 免费版，有速率限制
- `v4-pro`: 付费版，需充值

#### B. 充值 v4-pro（如需使用）

```bash
# 充值路径
控制台 → 充值中心 → 选择充值金额

# 推荐充值
- 测试：10元
- 个人使用：50元
- 频繁使用：100元

# 价格参考
- v4-pro: 0.5元/百万tokens
- 预估：1元可处理200万tokens（约1500页文档）
```

#### C. 获取 API Key

```bash
1. 控制台 → API Keys
2. 创建新的 API Key
3. 复制保存（只显示一次）

格式：sk-xxxxxxxxxxxxxxxx
```

---

### 2. 通义千问VL（VLM）

#### A. 注册阿里云

```bash
# 访问阿里云百炼
https://dashscope.aliyuncs.com/

# 注册/登录
- 使用支付宝/淘宝账号快速登录
- 或手机号注册
```

#### B. 开通服务

```bash
# 开通"灵积"或"百炼"平台
1. 控制台 → 产品服务 → 搜索"灵积"
2. 点击开通（免费）
3. 同意服务协议

# 免费额度
- 新用户：100万tokens
- 足够处理约100张图片
```

#### C. 获取 API Key

```bash
1. 控制台 → API-KEY管理
2. 创建新的 API Key
3. 复制保存

格式：sk-xxxxxxxxxxxxxxxx
```

#### D. 充值（可选）

```bash
# 如果超出免费额度
控制台 → 充值中心

# 推荐充值
- 测试：10元
- 个人使用：50元

# 价格
- qwen-vl-max: 0.008元/张图
- 预估：1元可处理125张图片
```

---

## 二、配置文件修改

### 步骤1：修改 .env 文件

```bash
# D:\AIpractise\shopkeer_brain\knowledge\.env
```

```python
# ==================== LLM 配置（DeepSeek）====================
OPENAI_API_BASE=https://api.deepseek.com/v1
OPENAI_API_KEY=sk-your-deepseek-key  # 替换为您的 DeepSeek Key
LLM_DEFAULT_MODEL=deepseek-v4-flash  # 或 deepseek-v4-pro
ITEM_MODEL=deepseek-v4-flash         # 商品名识别
VL_MODEL=qwen-vl-plus                # 视觉模型（暂时用这个）

# ==================== VLM 配置（通义千问）====================
# 新增以下配置
DASHSCOPE_API_KEY=sk-your-qwen-key   # 替换为您的通义千问 Key
DASHSCOPE_VL_MODEL=qwen-vl-max       # 或 qwen-vl-plus（更便宜）

# ==================== 其他配置保持不变 ====================
BGE_M3_PATH=D:\ai_models\bge_models\BAAI\bge-m3
# ... 其他配置 ...
```

---

### 步骤2：修改 config.py 添加 VLM 配置

编辑 `D:\AIpractise\shopkeer_brain\knowledge\processor\import_process\config.py`:

在 `QueryConfig` 类中添加：

```python
# ==================== VLM 配置（新增）====================
dashscope_api_key: str = field(
    default_factory=lambda: os.getenv("DASHSCOPE_API_KEY", "")
)
dashscope_vl_model: str = field(
    default_factory=lambda: os.getenv("DASHSCOPE_VL_MODEL", "qwen-vl-max")
)
```

---

### 步骤3：修改 md_img.py 使用独立的 VLM 客户端

编辑 `D:\AIpractise\shopkeer_brain\knowledge\processor\import_process\nodes\md_img.py`:

找到 `get_summary_singleImg` 方法（第301行附近），修改为：

```python
def get_summary_singleImg(self, md_path, img_file_path, img_context):
    # 原则：把图片 + 上下文信息，提交vlm，生成摘要
    head_title, pre_context, post_context = img_context
    data = []
    if head_title:
        data.append(head_title)
    if pre_context:
        data.append(pre_context)
    if post_context:
        data.append(post_context)
    context = "\n".join(data)

    image_data_str = ""
    # 读取图片内容，二进制内容，使用base64把图片转换字符串
    with open(img_file_path, "rb") as f:
        image_data_str = base64.b64encode(f.read()).decode("utf-8")

    # 开始调用vlm视觉模型
    config = get_config()

    # === 修改开始：使用通义千问VL ===
    try:
        # 尝试使用通义千问VL
        vl_client = OpenAI(
            api_key=config.dashscope_api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )

        document_name = md_path.stem
        messages = [
            {"role": "user",
             "content": [
                 {
                     "type": "text",
                     "text": f"""任务：为Markdown文档中的图片生成一个简短的中文标题。
                                 背景信息：
                                     1. 所属文档标题："{document_name}"
                                     2. 图片上下文：{context}
                                     请结合图片视觉内容和上述上下文信息，用中文简要总结这张图片的内容，
                                     生成一个精准的中文标题（不要包含"图片"二字）。""",
                 },
                 {
                     "type": "image_url",
                     "image_url": {
                         "url": f"data:image/jpeg;base64,{image_data_str}"
                     }
                 }
             ]
            }
        ]

        response = vl_client.chat.completions.create(
            model=config.dashscope_vl_model,
            messages=messages,
        )

        summary = response.choices[0].message.content.strip()
        return summary

    except Exception as e:
        self.logger.warning(f"通义千问VL调用失败: {e}，回退到默认模型")

        # 回退方案：使用原配置（智谱）
        client = OpenAI(
            api_key=config.openai_api_key,
            base_url=config.openai_api_base
        )

        document_name = md_path.stem
        messages = [
            {"role": "user",
             "content": [
                 {
                     "type": "text",
                     "text": f"""任务：为Markdown文档中的图片生成一个简短的中文标题。
                                 背景信息：
                                     1. 所属文档标题："{document_name}"
                                     2. 图片上下文：{context}
                                     请结合图片视觉内容和上述上下文信息，用中文简要总结这张图片的内容，
                                     生成一个精准的中文标题（不要包含"图片"二字）。""",
                 },
                 {
                     "type": "image_url",
                     "image_url": {
                         "url": f"data:image/jpeg;base64,{image_data_str}"
                     }
                 }
             ]
            }
        ]

        response = client.chat.completions.create(
            model=config.vl_model,
            messages=messages,
        )

        summary = response.choices[0].message.content.strip()
        return summary
    # === 修改结束 ===
```

---

### 步骤4：添加性能监控（可选）

在 `get_summary_singleImg` 方法中添加计时：

```python
from knowledge.utils.performance_util import PerformanceTimer

def get_summary_singleImg(self, md_path, img_file_path, img_context):
    with PerformanceTimer("VLM图片摘要生成"):
        # ... 原有代码 ...
```

---

## 三、测试验证

### 1. 测试 LLM（DeepSeek）

```python
# 创建测试脚本 test_deepseek.py
from knowledge.utils.llm_client_util import get_llm_client

client = get_llm_client()
response = client.invoke("测试：用一句话介绍人工智能")
print(response.content)
```

运行：
```bash
python test_deepseek.py
```

预期：2-5秒内返回结果

---

### 2. 测试 VLM（通义千问）

```python
# 创建测试脚本 test_qwen_vl.py
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

response = client.chat.completions.create(
    model="qwen-vl-max",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "这张图片是什么？"},
            {
                "type": "image_url",
                "image_url": {
                    "url": "https://dashscope.oss-cn-beijing.aliyuncs.com/images/dog.png"
                }
            }
        ]
    }]
)

print(response.choices[0].message.content)
```

运行：
```bash
python test_qwen_vl.py
```

预期：3-8秒内返回图片描述

---

## 四、常见问题

### Q1: DeepSeek v4-flash 速率限制是多少？

A: 免费版限制：
- 每分钟：60次请求
- 每天：100万tokens
- 超出后需等待或切换到 v4-pro

### Q2: 通义千问免费额度用完怎么办？

A: 充值建议：
- 10元 → 处理1250张图片
- 50元 → 处理6250张图片
- 按需充值，避免浪费

### Q3: 如何选择 qwen-vl-max 还是 qwen-vl-plus？

A:
- **vl-max**：质量更高，速度稍快，价格0.008元/张
- **vl-plus**：性价比高，速度稍慢，价格0.005元/张

推荐：先用 `vl-plus`，质量不够再升级到 `vl-max`

---

## 五、预期效果

### 性能提升

| 环节 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| **导入（10张图）** | | | |
| LLM商品名识别 | 20-60秒 | 2-5秒 | 10倍 |
| VLM图片处理×10 | 300-600秒 | 20-50秒 | 10-12倍 |
| BGE-M3向量化 | 30-90秒 | 30-90秒 | 不变 |
| **总计** | **10分钟+** | **2-3分钟** | **70-80%** |
| | | | |
| **查询** | | | |
| LLM商品名提取 | 15-40秒 | 2-5秒 | 8倍 |
| LLM答案生成 | 30-90秒 | 5-15秒 | 6倍 |
| **总计** | **5分钟+** | **30-60秒** | **90%** |

### 成本估算

**月使用场景（个人）：**
- 导入文档：50个（含500张图片）
- 查询次数：300次
- **总成本**：约 **15-25元/月**

**详细清单：**
- DeepSeek LLM：300次 × 1000tokens × 0.5元/百万 = 1.5元
- 通义千问VL：500张 × 0.008元 = 4元
- 其他杂费：约5-10元
- **总计**：约 **10-15元/月**

---

## 六、快速开始清单

- [ ] 1. 获取 DeepSeek API Key
- [ ] 2. 注册阿里云百炼，获取通义千问 API Key
- [ ] 3. 修改 .env 配置文件
- [ ] 4. 修改 config.py 添加 VLM 配置
- [ ] 5. 修改 md_img.py 使用通义千问VL
- [ ] 6. 重启服务测试
- [ ] 7. 导入一个文档测试速度
- [ ] 8. 查看日志性能报告

---

**开始配置后，如果遇到任何问题，随时告诉我！**
