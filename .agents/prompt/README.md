# Prompt Library

This directory is the repository-versioned prompt snippet library explored by
`ImagePromptTemplateAgent`. Keep reusable visual prompt fragments here instead
of creating rotating local prompt roots.

Template selection is agent-driven: the agent reads the current user request,
image group, and style constraints, then decides which prompt references to
inspect. Do not add deterministic trigger tables or hidden selection rules here.

Claude-style Skills stay in `.agents/skills/`; this directory only stores
runtime-loadable prompt references.
