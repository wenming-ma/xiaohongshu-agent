# OpenRouter 图片生成配置指南

## 🎨 OpenRouter 简介

OpenRouter 是一个 **AI 模型路由服务**，提供统一的 API 接口访问多种 AI 模型，包括：
- OpenAI DALL-E 3
- Stability AI Stable Diffusion
- Midjourney (即将支持)
- 其他图片生成模型

**优势：**
- ✅ 统一接口：一个 API 访问多个模型
- ✅ 成本优化：根据价格选择不同模型
- ✅ 高可用性：自动切换到可用模型
- ✅ 透明计费：详细的使用统计

---

## 🔧 配置步骤

### 1. 获取 OpenRouter API Key

访问 [OpenRouter.ai](https://openrouter.ai/) 注册并获取 API Key。

### 2. 配置环境变量

编辑 `.env` 文件：

```env
# OpenRouter 配置
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxx
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_IMAGE_MODEL=openai/dall-e-3

# 可选：网站信息（用于 OpenRouter 排名）
OPENROUTER_SITE_URL=https://your-site.com
OPENROUTER_SITE_NAME=Your Site Name
```

**配置说明：**

| 配置项 | 必需 | 说明 |
|--------|------|------|
| `OPENROUTER_API_KEY` | ✅ 是 | OpenRouter API 密钥 |
| `OPENROUTER_BASE_URL` | ❌ 否 | API 端点（默认：https://openrouter.ai/api/v1） |
| `OPENROUTER_IMAGE_MODEL` | ❌ 否 | 使用的模型（默认：openai/dall-e-3） |
| `OPENROUTER_SITE_URL` | ❌ 否 | 你的网站 URL（用于 OpenRouter 排名） |
| `OPENROUTER_SITE_NAME` | ❌ 否 | 你的网站名称（用于 OpenRouter 排名） |

### 3. 支持的图片生成模型

你可以通过修改 `OPENROUTER_IMAGE_MODEL` 切换不同的图片生成模型：

```env
# DALL-E 3（推荐，质量最高）
OPENROUTER_IMAGE_MODEL=openai/dall-e-3

# DALL-E 2（成本更低）
OPENROUTER_IMAGE_MODEL=openai/dall-e-2

# Stable Diffusion XL（开源模型）
OPENROUTER_IMAGE_MODEL=stability-ai/stable-diffusion-xl

# 其他模型（查看 OpenRouter 文档）
```

---

## 💰 成本说明

### OpenRouter 计费方式

OpenRouter 采用**按使用量计费**：
- 根据实际使用的模型和 tokens 收费
- 每个模型有不同的价格
- 详细账单可在 OpenRouter 控制台查看

### DALL-E 3 价格（通过 OpenRouter）

| 尺寸 | 质量 | 价格/张 |
|------|------|---------|
| 1024×1024 | Standard | ~$0.040 |
| 1024×1024 | HD | ~$0.080 |
| 1024×1792 | Standard | ~$0.080 |
| 1792×1024 | Standard | ~$0.080 |

**注**: 实际价格可能随 OpenRouter 调整而变化，请查看 [OpenRouter Pricing](https://openrouter.ai/models)

### 单次运行成本估算

生成 3 张图片（1024×1024，Standard 质量）：
- 3 × $0.04 = **$0.12**

---

## 🚀 使用示例

### 基本用法

系统会自动使用 OpenRouter 生成图片，无需手动调用。

```bash
python main.py --topic "西安公司避坑指南" --audience "求职者"
```

### 测试图片生成

单独测试 OpenRouter 图片生成：

```bash
python -m langgraph.tools.image_generation
```

### Python API 调用

```python
from langgraph.tools.image_generation import ImageGenerationService

service = ImageGenerationService(provider="openrouter")

image_paths = await service.generate_xiaohongshu_images(
    image_descriptions=[
        "A vibrant social media post with the text '避坑指南'...",
        "An infographic-style image showing a list...",
        "A conclusion card with cute design..."
    ],
    output_dir="posts/my-project/images",
    filenames=["cover.png", "image-1.png", "image-2.png"]
)
```

---

## 🔍 高级配置

### 切换到其他图片生成模型

编辑 `langgraph/nodes/generate_images.py`:

```python
# 使用 Stable Diffusion 而不是 DALL-E 3
service = ImageGenerationService(provider="openrouter")
# 然后在 .env 中设置：
# OPENROUTER_IMAGE_MODEL=stability-ai/stable-diffusion-xl
```

### 自定义提示词增强

修改 `langgraph/tools/image_generation.py` 中的 `generate_xiaohongshu_images` 方法：

```python
enhanced_prompt = (
    f"Create a trendy, eye-catching social media post image. "
    f"{desc} "
    f"Style: Xiaohongshu aesthetic, vibrant colors, clean typography."
)
```

---

## 🛠️ 故障排查

### 问题 1: API Key 无效

**症状**: `401 Unauthorized`

**解决方案**:
1. 检查 `OPENROUTER_API_KEY` 是否正确
2. 确认 API Key 是否激活
3. 访问 [OpenRouter Dashboard](https://openrouter.ai/keys) 验证

### 问题 2: 模型不支持图片生成

**症状**: `Model does not support image generation`

**解决方案**:
1. 确认 `OPENROUTER_IMAGE_MODEL` 设置正确
2. 使用支持的模型：
   - `openai/dall-e-3` ✅
   - `openai/dall-e-2` ✅
   - `stability-ai/stable-diffusion-xl` ✅

### 问题 3: 余额不足

**症状**: `Insufficient credits`

**解决方案**:
1. 访问 [OpenRouter Dashboard](https://openrouter.ai/credits)
2. 充值账户
3. 查看使用统计

### 问题 4: 生成速度慢

**可能原因**:
- OpenRouter 服务器负载高
- 使用的模型生成速度慢

**解决方案**:
1. 切换到更快的模型（如 DALL-E 2）
2. 减少并发生成数量
3. 联系 OpenRouter 支持

---

## 📊 监控和统计

### 查看使用统计

访问 [OpenRouter Dashboard](https://openrouter.ai/activity) 查看：
- 每日请求数
- 成本统计
- 模型使用分布
- 错误率

### 设置预算提醒

在 OpenRouter 控制台设置预算上限，避免意外超支。

---

## 🔐 安全建议

1. **不要泄露 API Key**:
   - 不要提交 `.env` 文件到 git
   - 使用环境变量管理密钥

2. **限制 API Key 权限**:
   - 在 OpenRouter 控制台设置 IP 白名单
   - 限制每日使用额度

3. **定期轮换密钥**:
   - 建议每 3 个月更换一次 API Key
   - 发现泄露立即撤销并生成新密钥

---

## 📚 相关资源

- [OpenRouter 官方文档](https://openrouter.ai/docs)
- [OpenRouter 模型列表](https://openrouter.ai/models)
- [OpenRouter 定价](https://openrouter.ai/models)
- [OpenAI DALL-E 3 文档](https://platform.openai.com/docs/guides/images)

---

## 🆚 OpenRouter vs 直接调用 OpenAI

| 特性 | OpenRouter | 直接调用 OpenAI |
|------|-----------|----------------|
| **API Key** | 一个 Key 访问多个模型 | 每个服务需要单独 Key |
| **价格** | 略高（OpenRouter 收取小额服务费） | 官方价格 |
| **可用性** | 高（多提供商自动切换） | 取决于单一提供商 |
| **灵活性** | 支持多种模型切换 | 仅限 OpenAI 模型 |
| **计费** | 统一账单 | 分散在不同服务 |

**推荐场景**:
- ✅ 使用 OpenRouter：需要多模型支持、追求高可用性
- ✅ 直接调用 OpenAI：仅使用 DALL-E 3、追求最低成本

---

**配置完成后**，系统会自动通过 OpenRouter 生成图片，享受更灵活的模型选择和更高的可用性！
