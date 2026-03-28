import re


DEFAULT_TONE_TAG = "neutral"
_MAX_TONE_WORDS = 3
_MAX_TONE_TEXT_LEN = 24
_LEADING_TONE_RE = re.compile(r"^\[([^\]]+)\]\s*")


def normalize_tone_tag(raw_tag: str, default: str = DEFAULT_TONE_TAG) -> str:
    tag = raw_tag.strip()
    if not tag:
        return default
    if tag.startswith("[") and tag.endswith("]"):
        tag = tag[1:-1].strip()

    tag = tag.lower().replace("_", " ").replace("-", " ")
    tag = re.sub(r"\s+", " ", tag).strip()
    if not tag or len(tag) > _MAX_TONE_TEXT_LEN:
        return default

    words = tag.split(" ")
    if len(words) > _MAX_TONE_WORDS:
        return default
    if any(not re.fullmatch(r"[a-z]+", word) for word in words):
        return default
    return tag


def split_tone_tag(text: str) -> tuple[str, str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return "", ""

    match = _LEADING_TONE_RE.match(cleaned)
    if not match:
        return "", cleaned

    tone_tag = normalize_tone_tag(match.group(1))
    content = cleaned[match.end():].strip()
    return tone_tag, content


def strip_tone_tag(text: str) -> str:
    _, content = split_tone_tag(text)
    return content


def build_tts_text(text: str, tone_tag: str) -> str:
    content = re.sub(r"\s+", " ", text).strip()
    if not content:
        return ""

    normalized_tag = normalize_tone_tag(tone_tag)
    return f"[{normalized_tag}] {content}"


def prepare_provider_tts_text(
    text: str,
    provider: str,
    tone_tag: str = "",
    default_tag: str = DEFAULT_TONE_TAG,
) -> str:
    normalized_text = re.sub(r"\s+", " ", text).strip()
    if not normalized_text:
        return ""

    extracted_tag, content = split_tone_tag(normalized_text)
    if content:
        normalized_text = content

    normalized_tag = normalize_tone_tag(tone_tag or extracted_tag or default_tag)
    provider_name = provider.strip().lower()
    if provider_name == "google":
        return normalized_text
    return f"[{normalized_tag}] {normalized_text}"
