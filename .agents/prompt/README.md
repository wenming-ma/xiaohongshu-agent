# Prompt Library

This directory is the repository-versioned prompt template library explored by
specialist Agents. `ImagePromptTemplateAgent` uses this library for image
prompt guidance, and other specialist Agents can use the research, planning,
copy, article, video, review, meta, and delivery categories. Keep reusable
prompt fragments here instead of creating rotating local prompt roots.

Template selection is Agent-driven: the Agent reads the current user request,
current group, route plan, artifacts, and style constraints, then decides which
prompt references to inspect. Do not add deterministic trigger tables or hidden
selection rules here.

Skill Protocol documents stay in `.agents/skills/`; this directory only stores
runtime-loadable prompt references.

## Categories

- `research/`: trend scouting, source triangulation, evidence extraction, and
  audience insight templates.
- `planning/`: route planning, Skill selection, clarification, and task
  decomposition templates for the main Agent.
- `image/`: visual prompt templates for generated images and covers.
- `copy/`: Xiaohongshu title/body/product-review copy templates.
- `article/`: long-form outline and source-backed article templates.
- `video/`: short video hook, storyboard, narration, and cover templates.
- `review/`: relevance, safety, visual QA, and delivery-readiness checks.
- `meta/`: prompt design, prompt testing, variable schema, and template
  maintenance templates.
- `delivery/`: Feishu review package, risk check, and handoff templates.

Every template should include `## Use When`, `## Constraints`, and
`## Prompt Template` so Agents can inspect files quickly and compose them
without brittle filename rules.

## External Research Inputs

The library is informed by high-impact open prompt and prompt-engineering
repositories, including prompts.chat, DAIR.AI Prompt Engineering Guide,
promptslab Awesome Prompt Engineering, PromptSource, Microsoft prompt-engine,
LangGPT-style structured prompt patterns, and hands-on prompt-engineering
tutorial repositories.

Image prompt templates are the primary asset in this library. Their structure is
also informed by public text-to-image prompt resources such as Stable Diffusion
prompt template collections, awesome Stable Diffusion prompt lists, DiffusionDB
research, DALL-E prompt guides, diffusion-model prompt-engineering studies, and
recent high-star GitHub image-prompt collections such as YouMind-OpenLab's Nano
Banana Pro prompt library, jamez-bondos' GPT-4o image examples, and Hunyuan
PromptEnhancer's structured prompt rewriting work. The useful patterns are
subject specificity, composition, camera angle, lighting, material behavior,
reference alignment, editing intent, negative constraints, model-sensitive
limitations, and review loops that reject unrelated UI or diagnostic artifacts.

These external sources are used as research inputs only. Do not copy their
original project templates into this repository. Convert useful ideas into
project-specific, original templates that fit our Feishu-first orchestrator,
ResultEnvelope workflow, Atomic Agents, Skill documents, and Xiaohongshu-style
content routes.
