---
name: feishu-review-delivery
description: Use when final content should be packaged for Feishu review as the formal delivery endpoint, especially when the workflow needs a concise summary, structured body text, and attached media artifacts.
---

# Feishu Review Delivery

## Overview
Use this skill when the final destination is Feishu. The job is not "publish now"; the job is "package clearly so a human can review quickly and decide what to do next."

## When to Use
- User says results should go to Feishu
- The workflow should stop before platform publishing
- We need a reviewable delivery package with text plus media

## Workflow
1. Put the user-facing title, body, hashtags, and route summary into short structured blocks.
2. Attach the actual media artifacts instead of only mentioning local paths.
3. Keep the first message scannable; detailed files and images can follow as attachments.

## Delivery Rules
- Lead with route, topic, and audience context.
- Preserve the real generated media as artifacts.
- Prefer one summary message plus attachments over a long wall of text.
- If the content has multiple images, keep their labels meaningful and stable.

## Common Mistakes
- Sending only raw file paths without context.
- Copying the entire research dump into the first message.
- Mixing "ready to publish" language into a review-only handoff.
