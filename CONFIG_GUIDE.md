# 配置指南

## 🔧 自定义 API 端点配置

本系统已配置为使用**自定义 Anthropic API 端点**，所有语言模型调用将统一通过该端点进行。

---

## 📝 环境变量说明

### 核心配置（必需）

```env
# 自定义 Anthropic API 端点
ANTHROPIC_BASE_URL=http://115.175.23.49:3000/api

# 认证令牌
ANTHROPIC_AUTH_TOKEN=cr_b11e7fecd0961b3503a7a7019159d75513aea6c199f9352780c171dfa1b1d54d
```

这两个配置项是**必需的**，系统会通过该端点访问所有 Claude 模型。

---

### 图片生成配置（可选）

```env
# OpenAI API Key（仅用于 DALL-E 3 图片生成）
OPENAI_API_KEY=your_openai_api_key_here
```

**说明：**
- 如果你需要使用 **DALL-E 3** 生成图片，请填入 OpenAI API Key
- 如果不需要图片生成功能，可以留空或注释掉该行
- 图片生成是工作流的可选步骤，不影响内容创作和发布

---

## 🎯 模型配置

所有节点现在统一使用 **Claude** 模型（通过自定义端点）：

| 节点 | 模型 | 用途 |
|------|------|------|
| `research_xhs` | Claude | 小红书平台研究 |
| `research_web` | Claude | 多平台研究 |
| `synthesize` | Claude | 内容合成与创作 |
| `generate_images` | Claude* | 图片描述生成 |
| `publish` | - | 浏览器自动化（无需模型） |

*注：`generate_images` 节点会生成图片描述，实际图片生成仍使用 DALL-E 3（如果配置了 OPENAI_API_KEY）

---

## ⚙️ 配置步骤

### 1. 创建配置文件

```bash
# 如果还没有 .env 文件
cp .env.example .env
```

### 2. 验证配置

```bash
python config.py
```

应该看到：
```
✅ Environment check passed
🔗 Using Anthropic API endpoint: http://115.175.23.49:3000/api

📊 Model Configuration:
  init_project          → None
  research_xhs          → claude-sonnet-4-5-20251022      ($3.0/1M tokens)
  research_web          → claude-sonnet-4-5-20251022      ($3.0/1M tokens)
  synthesize            → claude-sonnet-4-5-20251022      ($3.0/1M tokens)
  generate_images       → claude-sonnet-4-5-20251022      ($3.0/1M tokens)
  publish               → None
```

### 3. 测试运行

```bash
python main.py --topic "测试主题" --audience "测试受众"
```

---

## 🔍 高级配置

### 修改模型配置

如果需要修改使用的模型，编辑 `config.py` 中的 `NODE_MODELS` 字典：

```python
NODE_MODELS = {
    "research_xhs": "claude",    # Claude Sonnet 4.5
    "research_web": "claude",
    "synthesize": "claude",
    "generate_images": "claude",
}
```

### 自定义端点参数

在 `config.py` 的 `get_model_for_node()` 函数中，可以调整：

```python
return ChatAnthropic(
    model=model_name,
    api_key=ANTHROPIC_API_KEY,
    base_url=ANTHROPIC_BASE_URL,  # 自定义端点
    temperature=0.7,                # 温度参数
    max_tokens=4096                # 最大token数
)
```

---

## 🚨 常见问题

### Q1: 如果自定义端点不可用怎么办？

**A:** 修改 `.env` 文件，使用官方 Anthropic API：

```env
# 使用官方 API
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_API_KEY=your_official_anthropic_key
```

### Q2: 如何跳过图片生成步骤？

**A:** 不配置 `OPENAI_API_KEY`，系统会自动跳过 DALL-E 3 调用，仅生成图片描述。

### Q3: 成本如何计算？

**A:** 所有模型调用现在都通过自定义端点，具体成本取决于你的端点计费方式。

系统仍会显示官方价格作为参考：
- Claude Sonnet 4.5: $3.0/1M tokens

### Q4: 如何切换回多模型配置？

**A:** 编辑 `config.py`，修改 `NODE_MODELS`：

```python
NODE_MODELS = {
    "research_xhs": "gpt4o",    # 改回 GPT-4o
    "research_web": "gpt4o",
    "synthesize": "claude",
    "generate_images": "gemini",
}
```

同时在 `.env` 中添加对应的 API Keys。

---

## 📊 端点健康检查

建议定期检查自定义端点的可用性：

```bash
# 测试端点连接
curl -X POST http://115.175.23.49:3000/api/messages \
  -H "x-api-key: cr_b11e7fecd0961b3503a7a7019159d75513aea6c199f9352780c171dfa1b1d54d" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{
    "model": "claude-sonnet-4-5-20251022",
    "max_tokens": 100,
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

---

## 📞 技术支持

如果遇到配置问题：
1. 检查 `langgraph.log` 日志文件
2. 运行 `python config.py` 验证环境
3. 查看错误信息中的具体端点响应

---

**最后更新**: 2025-12-28
**配置版本**: 统一自定义端点 v1.0
