# No Fake Language Text

## Use When
Use when text is not essential or when exact text has not been provided.

## Constraints
- Do not generate pseudo-Chinese, pseudo-English, random letters, fake UI labels,
  or illegible handwritten notes.
- If text is needed, require exact short text from upstream content.
- Prefer visual storytelling over generated copy.

## Prompt Template
Text negative guard for `{subject}`: keep the image text-free unless exact text
is provided. Do not include fake labels, gibberish, random characters, UI copy,
watermarks, menu boards, subtitles, or decorative writing.
