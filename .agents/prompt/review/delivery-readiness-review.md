# Delivery Readiness Review

## Use When

Use before sending the final DeliveryPackage to Feishu.

## Constraints

- Verify route, title, copy, media artifacts, and risk notes align.
- Catch broken artifacts, missing captions, mismatched image counts, and stale
  research notes.
- Do not require perfection; distinguish blocking issues from polish notes.
- Never suggest direct platform publishing.

## Prompt Template

Review `{delivery_package}` for Feishu delivery readiness.

Return:
- Blocking issues.
- Non-blocking improvements.
- Artifact checks.
- User-facing summary quality.
- Final decision: send, revise, or fail.
