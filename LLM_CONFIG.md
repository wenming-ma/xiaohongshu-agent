# LLM 配置指南

## 当前配置架构

### 📍 配置位置层级

```
1. 环境变量 (.env 文件)
   ├── ANTHROPIC_API_KEY      # pydantic-ai 自动识别
   ├── ANTHROPIC_BASE_URL     # pydantic-ai 自动识别（可选）
   └── 其他环境变量

2. Agent 构造函数参数
   ├── src/agents/research.py: ResearchAgent.__init__(model="...")
   └── src/agents/content.py: ContentAgent.__init__(model="...")

3. main.py 调用时
   ├── research_agent = ResearchAgent()  # 使用默认值
   └── content_agent = ContentAgent()    # 使用默认值
```

---

## 详细配置说明

### 1️⃣ API Key 配置

#### **方式 A：使用标准 Anthropic API**

编辑 `.env` 文件：

```env
# Anthropic 官方 API
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
```

**pydantic-ai 自动处理**：
- 读取 `ANTHROPIC_API_KEY` 环境变量
- 自动连接到 `https://api.anthropic.com`
- 无需额外配置

#### **方式 B：使用自定义端点（你的配置）**

编辑 `.env` 文件：

```env
# 自定义端点（统一代理）
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx  # 仍然需要
ANTHROPIC_BASE_URL=http://115.175.23.49:3000/api
```

**⚠️ 当前问题**：
- `.env.example` 使用了 `ANTHROPIC_AUTH_TOKEN`
- 但 pydantic-ai 只识别 `ANTHROPIC_API_KEY`
- 需要统一使用 `ANTHROPIC_API_KEY`

---

### 2️⃣ 模型名称配置

#### **当前设置**

```python
# src/agents/research.py (第14行)
def __init__(self, model: str = "claude-3-5-sonnet-20241022"):
    self.agent = Agent(model=model, ...)

# src/agents/content.py (第13行)
def __init__(self, model: str = "claude-3-5-sonnet-20241022"):
    self.agent = Agent(model=model, ...)
```

#### **支持的模型名称**

pydantic-ai 支持以下 Anthropic 模型：

```python
# Claude 3.5 系列（推荐）
"claude-3-5-sonnet-20241022"      # 最新 Sonnet（当前使用）
"claude-3-5-haiku-20241022"       # 更快更便宜

# Claude 3 系列
"claude-3-opus-20240229"          # 最强大
"claude-3-sonnet-20240229"        # 平衡
"claude-3-haiku-20240307"         # 最快
```

---

### 3️⃣ 修改 LLM 的方法

#### **方法 1：修改默认值（代码中）**

编辑 `src/agents/research.py`:

```python
def __init__(self, model: str = "claude-3-5-haiku-20241022"):  # 改这里
    ...
```

编辑 `src/agents/content.py`:

```python
def __init__(self, model: str = "claude-3-opus-20240229"):  # 改这里
    ...
```

#### **方法 2：运行时传参（推荐）**

修改 `src/main.py`:

```python
async def run_workflow(topic: str, audience: str) -> None:
    # 为不同 Agent 指定不同模型
    research_agent = ResearchAgent(model="claude-3-5-sonnet-20241022")
    content_agent = ContentAgent(model="claude-3-opus-20240229")
```

#### **方法 3：从环境变量读取（最灵活）**

修改 `src/agents/research.py`:

```python
def __init__(self, model: str | None = None):
    if model is None:
        # 从环境变量读取，否则使用默认值
        model = os.getenv("RESEARCH_MODEL", "claude-3-5-sonnet-20241022")
    ...
```

然后在 `.env` 中配置：

```env
RESEARCH_MODEL=claude-3-5-haiku-20241022
CONTENT_MODEL=claude-3-opus-20240229
```

---

### 4️⃣ pydantic-ai 如何处理 Anthropic 认证

#### **自动识别流程**

```python
# pydantic-ai 内部（简化版）
class Agent:
    def __init__(self, model: str, ...):
        # 1. 解析模型字符串
        if model.startswith("claude-"):
            # 这是 Anthropic 模型

            # 2. 自动读取环境变量
            api_key = os.getenv("ANTHROPIC_API_KEY")
            base_url = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

            # 3. 创建 Anthropic 客户端
            self.client = anthropic.Anthropic(
                api_key=api_key,
                base_url=base_url
            )
```

#### **环境变量优先级**

pydantic-ai 按以下顺序查找：

1. `ANTHROPIC_API_KEY` - 必需
2. `ANTHROPIC_BASE_URL` - 可选（默认官方 API）
3. 其他 Anthropic SDK 支持的变量

---

### 5️⃣ 代码中的配置路径

#### **完整调用链**

```
main.py
  ↓
main.py:47 - research_agent = ResearchAgent()
  ↓
research.py:14 - def __init__(self, model: str = "claude-3-5-sonnet-20241022")
  ↓
research.py:22 - api_key = os.getenv("ANTHROPIC_API_KEY")
  ↓
research.py:40 - self.agent = Agent(model=model, ...)
  ↓
pydantic_ai 自动使用环境变量创建 Anthropic 客户端
  ↓
调用 Claude API
```

#### **关键文件位置**

| 文件 | 行号 | 内容 |
|------|------|------|
| `src/agents/research.py` | 14 | `model="claude-3-5-sonnet-20241022"` |
| `src/agents/research.py` | 22 | `os.getenv("ANTHROPIC_API_KEY")` |
| `src/agents/content.py` | 13 | `model="claude-3-5-sonnet-20241022"` |
| `src/agents/content.py` | 21 | `os.getenv("ANTHROPIC_API_KEY")` |
| `src/main.py` | 47 | `ResearchAgent()` |
| `src/main.py` | 67 | `ContentAgent()` |
| `.env.example` | 6 | `ANTHROPIC_AUTH_TOKEN` (⚠️ 错误) |

---

### 6️⃣ 需要修复的问题

#### **问题：.env.example 中的变量名不一致**

**当前（错误）**：
```env
ANTHROPIC_AUTH_TOKEN=cr_xxxxx
```

**应该改为**：
```env
ANTHROPIC_API_KEY=cr_xxxxx
```

#### **原因**：
- pydantic-ai 使用 Anthropic 官方 SDK
- 官方 SDK 只识别 `ANTHROPIC_API_KEY`
- `ANTHROPIC_AUTH_TOKEN` 是旧版 LangChain 的配置

---

### 7️⃣ 配置示例

#### **标准配置（官方 API）**

```env
# .env
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
```

#### **自定义端点配置**

```env
# .env
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
ANTHROPIC_BASE_URL=http://115.175.23.49:3000/api
```

#### **多模型配置（可选）**

```env
# .env
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
RESEARCH_MODEL=claude-3-5-sonnet-20241022
CONTENT_MODEL=claude-3-opus-20240229
```

---

### 8️⃣ 常见问题

#### **Q: 如何切换到更便宜的模型？**

修改 `src/agents/research.py` 第 14 行：
```python
def __init__(self, model: str = "claude-3-5-haiku-20241022"):  # Haiku 更便宜
```

#### **Q: 如何为不同 Agent 使用不同模型？**

修改 `src/main.py` 第 47 和 67 行：
```python
research_agent = ResearchAgent(model="claude-3-5-haiku-20241022")  # 快速研究
content_agent = ContentAgent(model="claude-3-opus-20240229")       # 高质量创作
```

#### **Q: API Key 存储在哪里？**

1. 开发环境：`.env` 文件（不要提交到 Git）
2. 生产环境：系统环境变量或密钥管理服务

#### **Q: 如何验证配置是否正确？**

```bash
# 检查环境变量
python -c "import os; print(os.getenv('ANTHROPIC_API_KEY'))"

# 运行程序
python -m src.main --topic "测试" --audience "用户"
```

---

## 总结

### ✅ 当前配置
- **模型**: `claude-3-5-sonnet-20241022`（硬编码在代码中）
- **API Key**: 从 `ANTHROPIC_API_KEY` 环境变量读取
- **端点**: 从 `ANTHROPIC_BASE_URL` 读取（可选）

### ⚠️ 需要修复
- 更新 `.env.example` 将 `ANTHROPIC_AUTH_TOKEN` 改为 `ANTHROPIC_API_KEY`

### 🔧 推荐配置
```env
# .env
ANTHROPIC_API_KEY=your-api-key-here
```

### 📝 修改模型
编辑 `src/agents/research.py` 第 14 行和 `src/agents/content.py` 第 13 行。
