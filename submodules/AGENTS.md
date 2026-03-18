# Submodules Usage

`submodules/` 下的仓库可以作为实现参考来源。

## Reference Rules

- 可以阅读这里的源码、文档、测试和示例，用来参考架构设计、API 用法、提示词组织方式和实现细节。
- 优先只打开当前任务直接相关的文件，不要无差别遍历整个子模块。
- 如果问题涉及某个已存在子模块库的具体行为，优先直接查看对应子模块源码，而不是先去网上查。
  例如：需要确认 `pydantic_ai.Tool` 如何生成工具 description/docstring 时，优先查看 `submodules/pydantic-ai` 里的实现。
- 参考时要结合主项目当前架构做适配，不要机械复制代码。

## Boundary Rules

- `submodules/` 顶层目录视为受管理的 git submodule。
- `submodules/reference/` 仅用于参考，不要从这里直接导入运行时代码，除非当前任务明确要求迁移代码到主项目。
- 不要让主项目在运行时依赖 `submodules/` 里的 Python 包路径；如果需要复用实现，应复制并迁移到主项目合适的位置。
- 从子模块借鉴实现时，保持主项目既有目录结构、命名和依赖边界。

## Preferred Workflow

- 先在主项目里确认扩展点和目标文件。
- 再到相关子模块中查找可复用的思路、接口或实现模式。
- 落地时优先写成符合主项目约定的本地实现，而不是建立跨目录耦合。
