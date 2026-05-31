# Event Poster Visual Hierarchy

## Use When
Use for event, itinerary, collection, seasonal, or campaign visuals that need
poster-like hierarchy without relying on dense generated copy.

## Constraints
- Keep the subject and theme visible even if text rendering fails.
- Use visual sections, scale, and spacing instead of tiny fake captions.
- Use only exact text supplied by upstream content.

## Prompt Template
Generate a poster-like 3:4 image for `{event_or_theme}` with a clear hero
visual, strong top-to-bottom hierarchy, restrained color palette, and optional
exact title `{provided_text}`. The design should work as a visual poster even
without readable small text.
