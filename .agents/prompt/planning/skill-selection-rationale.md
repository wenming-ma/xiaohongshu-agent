# Skill Selection Rationale

## Use When

Use when the main Agent needs to select project Skills without keyword rules.

## Constraints

- Only choose from available Skills.
- Explain fit using user intent and workflow needs.
- Do not choose Skills merely because a filename matches.
- Prefer fewer high-fit Skills over many weak ones.

## Prompt Template

Given `{request}` and `{available_skills}`, select Skills.

Return:
- Selected Skill names.
- Fit reason for each.
- Skills considered but not selected.
- How selected Skills should influence downstream prompts.
