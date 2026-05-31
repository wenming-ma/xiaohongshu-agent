# Few-Shot Example Bank

## Use When

Use when an Agent needs examples of input-to-output behavior without embedding
large examples in the system prompt.

## Constraints

- Examples must be short and domain-relevant.
- Cover variety, not repetition.
- Do not reveal hidden reasoning.
- Label examples by purpose so an Agent can select them.

## Prompt Template

Build a few-shot example bank for `{task}`.

Return:
- Example purpose.
- Input sketch.
- Desired output sketch.
- Why the example helps.
- When not to use it.
