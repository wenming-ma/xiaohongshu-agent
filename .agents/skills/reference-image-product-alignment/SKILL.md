---
name: reference-image-product-alignment
description: Use when the user provides reference images for products, clothing, accessories, or visual style and generated images must preserve the referenced appearance.
---

# Reference Image Product Alignment

## Overview
Use this skill when the user attaches or mentions reference images and expects generated pictures to keep the same product appearance, clothing details, colors, shape, or texture.

## Workflow
1. If the user uploads a batch of reference images, ask for the missing usage instructions before generation.
2. Store the batch with `create_reference_asset_batch`; keep the returned `batch_id` and pass it through `reference_asset_batch_ids`.
3. Identify which stored reference image belongs to which item or style cue using the stored text description and usage instruction, not by re-reading the image.
4. Only apply strict visual alignment to positive/recommended items or explicitly requested objects.
5. Pass the relevant reference-image intent into the image prompt for the current group.
6. Keep the generated scene flexible, but preserve the referenced item's color, silhouette, texture, and design details.

## Style Rules
- Mention the item name and state that its appearance should match the labeled reference image.
- Do not invent a different color, pattern, material, or cut for referenced items.
- For outfit posts, reference items should appear as wearable objects in the look, not as floating screenshots.
- If a group is about avoidance or negative examples, do not force positive reference products into that image.
- Planner decisions should use the asset batch text: label, description, use_as, and instruction.
- The image generation node should receive only the selected local image paths plus the current task constraints.

## Common Mistakes
- Treating a reference image as a generic inspiration board rather than a concrete product constraint.
- Reusing a reference product in every group even when it does not fit the group.
- Copying UI screenshots, watermarks, or upload artifacts into the generated image.
- Making downstream specialist Agents read images again after the user already described how to use them.
