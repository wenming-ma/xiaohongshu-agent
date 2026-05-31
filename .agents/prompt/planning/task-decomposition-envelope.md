# Task Decomposition Envelope

## Use When

Use when the orchestrator needs to translate a flexible user request into
inputs for Atomic Agents.

## Constraints

- Keep Agent boundaries coarse and clear.
- Pass data through ResultEnvelope references, not ad hoc prompt strings.
- Do not split an Agent's internal review loop into separate public tasks.
- Identify parallelizable image generation tasks.

## Prompt Template

Decompose `{request}` into Atomic Agent calls.

Return:
- Research input.
- Grouping input envelope dependencies.
- Content input envelope dependencies.
- Image tasks and parallelization plan.
- Review/Delivery inputs.
