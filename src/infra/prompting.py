"""
Prompt template helpers.

Uses simple placeholder replacement to avoid brace escaping in JSON snippets.
"""
from typing import Any


def render_template(template: str, **variables: Any) -> str:
    """
    Replace {key} placeholders with provided values.

    This intentionally does not use str.format to keep literal braces intact.
    """
    if not variables:
        return template
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{key}}}", str(value))
    return rendered
