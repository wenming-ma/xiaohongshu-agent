# Autonomous Route Plan

## Use When

Use when the user gives broad permission such as "you decide" and the main
Agent must choose image, article, or video route.

## Constraints

- Decide from goal, available evidence, audience fit, and production cost.
- Do not ask for format unless the missing choice materially changes outcome.
- Select Skills and prompt templates semantically.
- Return a concise rationale that can be shown in Feishu.

## Prompt Template

Plan an autonomous content route for `{user_message}`.

Return:
- Chosen route.
- Why this route beats the alternatives.
- Skills to load and why.
- Prompt template categories likely needed.
- One Feishu-facing explanation sentence.
