---
name: dynamic-route-selection
description: Use when the conversation leaves the content route open and the system should decide whether an image post, article post, or video post best serves the current goal before producing a Feishu delivery package.
---

# Dynamic Route Selection

## Overview
Use this skill when the route is not fixed by the conversation. The decision should be pragmatic: pick the route that best matches the material, the review goal, the user's latest constraints, and the likely output quality.

## When to Use
- The user asks the system to explore, subscribe, track hotspots, collect assets, or otherwise proceed without fixing the format.
- The user provides a broad topic but no strong route preference.
- The best route depends on what the research step finds.

## Route Heuristics
- Choose `image_post` when the topic is visual, example-driven, style-led, or benefits from fast scanning.
- Choose `article_post` when the topic needs synthesis, explanation, comparison, or evidence-heavy narration.
- Choose `video_post` when the request or discovered material centers on clips, remixing, motion, or source footage.

## Review Rules
- Explain the chosen route in one sentence when handing off to Feishu.
- If the route is ambiguous, prefer the format that produces the clearest human-review package.
- Ask the user only when missing information would materially change the output quality or risk profile; otherwise proceed.
- Do not choose video just because it feels more ambitious; choose it only when the source material supports it.

## Common Mistakes
- Treating open-ended exploration as random output.
- Freezing "user specified" and "system initiated" into separate workflow categories.
- Defaulting to the same route every time.
- Picking a route that creates complex output with weak review value.
