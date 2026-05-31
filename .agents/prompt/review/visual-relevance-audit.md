# Visual Relevance Audit

## Use When

Use after image generation to detect images that are unrelated, generic, or
contaminated by operational artifacts.

## Constraints

- Compare against the exact group content and user style constraints.
- Reject login screens, app UI, research limitation cards, fake dashboards, and
  generic phone illustrations unless explicitly requested.
- Do not reward pretty images that miss the task.
- Return actionable regeneration guidance.

## Prompt Template

Audit image `{image_artifact}` against `{group_content}` and `{style_context}`.

Return:
- Pass/fail.
- Relevance score from 1 to 5.
- Missing required elements.
- Unwanted artifacts.
- Regeneration instruction if failed.
