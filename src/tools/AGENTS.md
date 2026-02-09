# Tools 目录

平台工具目录，按 `平台/内容类型` 组织。

## 目录结构

```
tools/
└── xiaohongshu/           # 小红书平台
    └── image_post/        # 图文帖子工具
        ├── tool.py        # XHSImagePostTool 主类
        ├── schemas.py     # 输入输出 schema
        ├── research/      # 研究 Agent
        ├── content/       # 内容创作 Agent
        ├── image/         # 图片生成 Agent
        ├── publish/       # 发布 Agent
        └── login/         # 登录 Agent
```

## 设计原则

**HuggingFace 风格**：保持简单、保持隔离。每个工具完全独立，包含自己所需的全部代码。

## 添加新平台工具

1. 创建目录：`tools/<platform>/<content_type>/`
2. 实现 `tool.py`，继承 `BasePlatformTool`
3. 使用 `@ToolRegistry.register` 注册
4. 按需添加 Agent 子目录
