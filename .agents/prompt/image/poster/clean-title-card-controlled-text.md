# Clean Title Card Controlled Text

## Use When
Use when the image must include a small amount of exact user-approved title
text, such as a cover title or section card.

## Constraints
- Use only `{provided_text}`; do not invent additional text.
- Keep text large, simple, and easy for the image model to render.
- Prefer short Chinese or English phrases and leave final text QA to the review
  Agent.

## Prompt Template
Generate a clean 3:4 title-card image for `{topic}` with one visual subject and
one exact text phrase: `{provided_text}`. Use strong hierarchy, generous spacing,
plain background, and minimal typography so the text remains readable.
