# Claim Risk Audit

## Use When

Use when copy contains product, health, finance, legal, safety, or strong trend
claims that need a conservative review.

## Constraints

- Separate factual claims, experiential claims, and suggestions.
- Require evidence refs for factual claims.
- Rewrite overconfident claims into safer wording.
- Do not add medical, financial, or legal advice.

## Prompt Template

Audit claims in `{draft}` using `{research_evidence}`.

Return:
- High-risk claims.
- Missing evidence.
- Safer replacement wording.
- Claims that can stay.
- Delivery note if user review is recommended.
