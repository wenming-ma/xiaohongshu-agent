# Pose-Free Object Match

## Use When

Use when the user wants objects, clothes, or products accurately shown without
people, poses, or models.

## Constraints

- No human body, mannequin, model, face, or hand unless explicitly requested.
- Preserve object structure and front-facing visibility.
- Use flatlay, hanger, shelf, tabletop, or floor arrangement.
- Avoid empty catalog stiffness.

## Prompt Template

Create a people-free image for `{object_set}`.

Use:
- Arrangement: `{object_arrangement}`.
- Background: `{background_style}`.
- Object accuracy: `{reference_requirements}`.
- Lighting: `{lighting_style}`.
- Exclude all people, mannequins, app screens, and text cards.
