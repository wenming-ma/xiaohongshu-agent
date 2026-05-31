# Color Palette Match

## Use When

Use when generated images must match a user-provided color palette or reference
board.

## Constraints

- Prioritize palette consistency over adding trendy colors.
- Keep color names concrete.
- Avoid muddy low-contrast output.
- Preserve key product or outfit colors exactly when specified.

## Prompt Template

Generate `{image_subject}` with this palette: `{palette}`.

Rules:
- Dominant color: `{dominant_color}`.
- Secondary color: `{secondary_color}`.
- Accent color: `{accent_color}`.
- Background relationship: `{background_color_relation}`.
- Do not introduce off-palette props.
