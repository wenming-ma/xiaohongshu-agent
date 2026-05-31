# Retexture Reference Object

## Use When
Use for image-editing or reference-guided generation where the object shape
must remain but its material or finish should change.

## Constraints
- Preserve the source object's silhouette, proportions, orientation, and key
  structural details.
- Change only the requested material, surface, color, or finish.
- Avoid inventing extra buttons, logos, screens, text, or decorative parts.

## Prompt Template
Retexture `{reference_subject}` as `{target_material}` while preserving its
exact shape, scale, orientation, and recognizable details. Use realistic
surface behavior, appropriate reflections, shadows, edge highlights, and
material imperfections so the edit looks physically coherent.
