# Preserve Subject Relevance

## Use When
Use as a broad relevance guard for all generated images, especially after
research-heavy or multi-step workflows.

## Constraints
- The image must visually answer the current group, not a meta-commentary about
  the workflow.
- Keep the subject, scene, audience, and style constraints aligned.
- If an idea cannot be tied to the group payload, do not generate it.

## Prompt Template
Relevance guard for `{group_subject}`: the image must clearly show
`{required_visual_elements}` and avoid unrelated scenery, placeholders, template
examples, workflow artifacts, or generic AI art. The viewer should understand
the group topic without reading internal notes.
