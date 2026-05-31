# Prompt Library

This directory is the repository-versioned prompt template library explored by
specialist Agents. `ImagePromptTemplateAgent` uses this library for image
prompt guidance, and other specialist Agents can use the copy, article, video,
and delivery categories. Keep reusable prompt fragments here instead of
creating rotating local prompt roots.

Template selection is Agent-driven: the Agent reads the current user request,
current group, route plan, artifacts, and style constraints, then decides which
prompt references to inspect. Do not add deterministic trigger tables or hidden
selection rules here.

Skill Protocol documents stay in `.agents/skills/`; this directory only stores
runtime-loadable prompt references.

## Categories

- `image/`: visual prompt templates for generated images and covers.
- `copy/`: Xiaohongshu title/body/product-review copy templates.
- `article/`: long-form outline and source-backed article templates.
- `video/`: short video hook, storyboard, narration, and cover templates.
- `delivery/`: Feishu review package, risk check, and handoff templates.

Every template should include `## Use When`, `## Constraints`, and
`## Prompt Template` so Agents can inspect files quickly and compose them
without brittle filename rules.
