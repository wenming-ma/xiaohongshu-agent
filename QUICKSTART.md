# 快速开始指南

## 🚀 5分钟快速上手

### 步骤 1: 安装依赖

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium
```

### 步骤 2: 配置 API 密钥

创建 `.env` 文件：

```bash
cp .env.example .env
```

**✅ 已预配置自定义 Anthropic API 端点！**

`.env` 文件内容（已配置）：

```env
# 自定义 Anthropic API 端点（统一管理所有模型）
ANTHROPIC_BASE_URL=http://115.175.23.49:3000/api
ANTHROPIC_AUTH_TOKEN=cr_b11e7fecd0961b3503a7a7019159d75513aea6c199f9352780c171dfa1b1d54d

# OpenRouter 图片生成（使用 DALL-E 3）
OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_IMAGE_MODEL=openai/dall-e-3
```

**📘 详细说明**: 查看 [CONFIG_GUIDE.md](CONFIG_GUIDE.md)

### 步骤 3: 验证环境

```bash
python config.py
```

应该看到：
```
✅ Environment check passed
🔗 Using Anthropic API endpoint: http://115.175.23.49:3000/api

📊 Model Configuration:
  init_project          → None
  research_xhs          → claude-sonnet-4-5-20251022     ($3.0/1M tokens)
  research_web          → claude-sonnet-4-5-20251022     ($3.0/1M tokens)
  synthesize            → claude-sonnet-4-5-20251022     ($3.0/1M tokens)
  generate_images       → claude-sonnet-4-5-20251022     ($3.0/1M tokens)
  publish               → None
```

**注**: 显示的成本为官方价格参考，实际成本取决于自定义端点计费

### 步骤 4: 小红书登录（一次性）

在运行完整工作流之前，需要先登录小红书：

```bash
python -m langgraph.tools.browser
```

这将：
1. 打开浏览器到小红书登录页面
2. 等待你扫码登录
3. 保存登录 session 到 `.xhs_session.json`

**只需要做一次！** Session 会被保存，后续自动使用。

---

## 📝 运行第一个工作流

### 基础用法

```bash
python main.py --topic "西安公司避坑指南" --audience "求职者"
```

### 完整参数

```bash
python main.py \
  --topic "可持续时尚品牌推荐" \
  --audience "年轻女性" \
  --images 3
```

---

## 🎯 工作流程说明

运行时你会看到：

```
============================================================
🎯 主题: 西安公司避坑指南
👥 目标受众: 求职者
📸 图片数量: 3
📁 项目目录: posts/20251228-143022-xian-company-pitfalls
============================================================

⏳ 启动工作流...

✓ 节点完成: init_project
  📝 [2025-12-28T14:30:22] Project initialized: 20251228-143022-xian-company-pitfalls

✓ 节点完成: research_xhs
  📝 [2025-12-28T14:30:45] XHS research completed: 12 data points collected

✓ 节点完成: research_web
  📝 [2025-12-28T14:30:48] Web research completed: 15 data points, 60% verified

✓ 节点完成: synthesize
  📝 [2025-12-28T14:31:10] Content synthesized: 5 entities, 3 verified

🎨 开始生成 3 张图片...
🎨 使用 DALL-E 3 生成图片...
   描述: Create a trendy, eye-catching social media post...
   ✅ 图片已保存: posts/.../images/cover.png

✓ 节点完成: generate_images
  📝 ✅ 成功生成 3 张图片

📤 准备发布到小红书...
   标题: 西安公司避坑指南 ⚠️ 这些坑千万别踩
   正文长度: 523 字
   图片数量: 3
   话题标签: ['西安求职', '避坑指南', '职场经验']

✓ 节点完成: publish
  📝 [2025-12-28T14:31:45] ✅ 发布成功: https://xiaohongshu.com/explore/...

============================================================
✅ 工作流完成！
============================================================
```

---

## 📂 输出文件

每个项目生成独立的目录：

```
posts/20251228-143022-xian-company-pitfalls/
├── project.json                  # 项目元数据
├── xiaohongshu-research.json     # 小红书研究数据
├── web-research.json             # 多平台研究数据
├── research-summary.json         # 综合总结
├── content.json                  # 最终内容 ⭐ 重要
├── images/
│   ├── cover.png                # DALL-E 生成的封面
│   ├── image-1.png              # 图片 1
│   └── image-2.png              # 图片 2
└── publish-result.json          # 发布结果
```

---

## 🎨 仅生成图片（不发布）

如果你只想测试图片生成：

```bash
python -m langgraph.tools.image_generation
```

这会生成 3 张测试图片到 `test_images/` 目录。

---

## 🔧 常见问题

### Q: 发布失败，提示 "No session found"

**A:** 需要先登录小红书：

```bash
python -m langgraph.tools.browser
```

### Q: 图片生成失败

**A:** 检查：
1. `OPENROUTER_API_KEY` 是否正确设置
2. OpenRouter 账户是否有足够余额
3. 网络连接是否正常
4. 使用的模型是否支持图片生成（默认：openai/dall-e-3）

### Q: 如何修改使用的模型？

**A:** 当前所有节点已统一使用 Claude 模型（通过自定义端点）。

如需修改，编辑 `config.py` 中的 `NODE_MODELS` 字典：

```python
NODE_MODELS = {
    "research_xhs": "claude",    # 统一使用 Claude
    "research_web": "claude",
    "synthesize": "claude",
}
```

**详细配置**: 查看 [CONFIG_GUIDE.md](CONFIG_GUIDE.md)

### Q: 成本大概多少？

**A:** 成本取决于自定义 API 端点的计费方式。

官方价格参考（单次运行，1篇帖子）：
- 研究（Claude × 2）: ~$0.60
- 内容创作（Claude）: ~$0.30
- 图片生成（OpenRouter DALL-E 3，3张）: ~$0.12
- **总计参考**: ~$1.02 / 篇

**实际成本**: 请咨询你的 API 端点提供方

---

## 📚 进阶用法

### Python API 调用

```python
import asyncio
from main import run_xiaohongshu_workflow

async def my_script():
    result = await run_xiaohongshu_workflow(
        topic="健康早餐食谱",
        target_audience="上班族",
        num_images=3
    )

    print(f"项目目录: {result['project_dir']}")
    print(f"标题: {result['content']['title']}")
    print(f"发布URL: {result['publish_result']['post_url']}")

asyncio.run(my_script())
```

### 批量生成

```python
topics = [
    "西安公司避坑指南",
    "可持续时尚品牌推荐",
    "健康早餐食谱大全"
]

for topic in topics:
    await run_xiaohongshu_workflow(topic=topic)
```

---

## 🔍 调试技巧

### 1. 查看详细日志

每个 JSON 文件都包含详细信息：

```bash
# 查看研究结果
cat posts/YOUR_PROJECT/xiaohongshu-research.json | jq .

# 查看内容
cat posts/YOUR_PROJECT/content.json | jq .
```

### 2. 浏览器可见模式

发布时浏览器默认可见，方便调试。查看 `langgraph/nodes/publish.py` 第 59 行。

### 3. 截图调试

发布失败时会自动截图保存为 `publish_error.png`

---

## ✅ 下一步

- [ ] 查看 [README.md](README.md) 了解完整架构
- [ ] 阅读 [ARCHITECTURE.md](ARCHITECTURE.md) 理解设计细节
- [ ] 探索 [examples/](examples/) 查看更多示例
- [ ] 使用 LangGraph Studio 可视化调试（待配置）

---

**祝你玩得开心！** 🎉

有问题？查看 [README.md](README.md) 或提交 Issue。
