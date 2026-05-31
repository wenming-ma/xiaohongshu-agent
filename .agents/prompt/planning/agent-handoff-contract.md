# Agent Handoff Contract

## Use When

Use when defining how one specialist Agent's output should be consumed by the
next Agent.

## Constraints

- Use ResultEnvelope fields explicitly.
- Reference artifacts by artifact ref, not raw path strings.
- State what downstream Agents may trust and what they must re-check.
- Do not include message history as cross-Agent state.

## Prompt Template

Create a handoff contract from `{upstream_agent}` to `{downstream_agent}`.

Include:
- Required envelope fields.
- Payload fields used downstream.
- Artifact refs to inspect.
- Validation checks before use.
- Recovery behavior if envelope status is not success.
