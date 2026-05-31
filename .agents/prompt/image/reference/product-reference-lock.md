# Product Reference Lock

## Use When

Use when a product reference image must be preserved closely in generated
images.

## Constraints

- Keep product silhouette, main color, material, cap/lid shape, and label area.
- Do not invent brand claims or readable label text.
- Allow scene, lighting, and prop changes only if product identity remains.
- Flag conflicts with style constraints before generation.

## Prompt Template

Generate `{image_subject}` while locking product reference details.

Must preserve:
- Shape: `{reference_shape}`.
- Color/material: `{reference_material}`.
- Label area: non-readable, visually aligned.
- Scale: `{scale_context}`.
- Scene style: `{style_context}`.
