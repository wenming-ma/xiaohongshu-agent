# Clarification Choice Card

## Use When

Use when the main Agent lacks one decision and should ask the user through a
low-friction Feishu choice or form.

## Constraints

- Ask at most one decision at a time.
- Include a "you decide" option when the system can reasonably proceed.
- Avoid fixed input formats.
- Choices must map to workflow constraints, not implementation jargon.

## Prompt Template

Create a Feishu clarification card for `{request}`.

Return:
- Question.
- 3 to 5 button or checkbox options.
- Recommended default.
- How each option changes the workflow.
- Fallback if the user does not respond.
