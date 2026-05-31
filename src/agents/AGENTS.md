# Agent Organization

The formal product architecture is Feishu-first. Specialist agents live under
`src/agents/<content_type>/<phase>/`, and application orchestration lives in
`src/orchestration/` plus `src/apps/feishu_orchestrator/`.

## Design System

The design system has three first-class citizens:

- Atomic Agents: general specialist capabilities under `src/agents/`, each owning one complete task area and returning structured outputs.
- Skill Protocol: reusable experience, workflow rules, style guidance, prompts, references, and checklists under `.agents/skills/`.
- Prompt Templates: repository-versioned prompt snippets under `.agents/prompt/` for reusable visual and copywriting patterns.

These citizens are composed at runtime. The Planner Agent or a specialist Agent chooses the needed Skills and Prompt Templates from the user's current goal, constraints, artifacts, and conversation context. Do not encode this composition as keyword triggers or fixed product branches.

## Principles

- One specialist agent owns one complete task area: research, grouping, content, image generation, download, cover generation, login, or review/delivery.
- A specialist agent may keep its internal multi-round review loop. Do not split a coherent phase into smaller external agents just to expose intermediate steps.
- The system is Agent-driven: route selection, Skill selection, prompt-template selection, and tool use decisions belong to the planner or specialist Agents. Do not replace those decisions with hidden keyword-trigger tables in helper functions.
- Agents should expose general task capabilities, not one-off product lines. User-specific style, quantity, format, and topic requirements flow in as dynamic context.
- Cross-agent data moves through `ResultEnvelope` in the orchestration layer. Local files are artifacts referenced by envelopes, not a separate protocol.
- Final delivery is a `DeliveryPackage` sent to Feishu. Direct platform publishing is not part of the formal workflow.
- Skill Protocol documents live in `.agents/skills/` and contain experience, style rules, prompts, and checklists only. Runtime schemas stay in Pydantic models.
- Versioned reusable prompt snippets live in `.agents/prompt/`. Do not add rotating local prompt roots.

## Layout

- `image_post/research`, `image_post/content`, `image_post/image`: image route specialist phases.
- `article_post/research`, `article_post/content`, `article_post/image`: article route specialist phases.
- `video_post/research`, `video_post/download`, `video_post/content`, `video_post/cover`: video route specialist phases.
- `shared/login`: the login specialist capability, used for research/access only.
- `shared/utils`: shared business helpers with stable contracts.

## Conventions

- Agent classes inherit `BaseAgent` and implement `forward`, `step`, and `validate` where applicable.
- Phase-local prompts stay beside the agent in `prompts.py`.
- Shared style prompt snippets live in `.agents/prompt/` and are selected by `ImagePromptTemplateAgent` with directory tools using the current request, image group, and `StyleContext`; do not keyword-trigger prompt snippets in `StyleContext` or hard-code style libraries in specialist agents.
- `ProjectSkillRegistry` only discovers available Skill Protocol documents. It must not rank or match them; `PlanningAgent` chooses Skills based on the active user need.
- Content-type helper modules stay under `src/agents/<content_type>/utils/`.
- Infrastructure helpers stay under `src/utils/`, `src/config/`, or `src/core/`.
- Do not add new direct runners or platform-publishing phases.
