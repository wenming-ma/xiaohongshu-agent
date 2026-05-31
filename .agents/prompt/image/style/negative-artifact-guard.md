# Negative Artifact Guard

## Use When

Use as an add-on whenever generated images have previously drifted into app
screens, login cards, generic phone UI, or research-note visuals.

## Constraints

- This is a guardrail, not the main creative direction.
- State what to exclude in concrete visual terms.
- Do not suppress required text if the task truly asks for a card design.
- Keep exclusions aligned with the current route.

## Prompt Template

Add these exclusions to the image prompt for `{image_task}`:

- No login screens, app interfaces, phone mockups, system dialogs, warning
  panels, or diagnostic cards.
- No research process text, source notes, usernames, URLs, or tool status.
- No unrelated icons such as refresh arrows, magnifiers, or generic dashboards.
- If text is needed, it must be explicitly requested by `{style_context}`.
