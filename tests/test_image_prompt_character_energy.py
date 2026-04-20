from src.agents.image_post.image.prompts import image_system_prompt as image_post_system_prompt
from src.agents.outfit_post.image.prompts import image_system_prompt as outfit_post_system_prompt
from src.agents.styled_image_post.image.prompts import image_system_prompt as styled_image_post_system_prompt


_SYSTEM_PROMPTS = (
    image_post_system_prompt,
    styled_image_post_system_prompt,
    outfit_post_system_prompt,
)

_REMOVED_PHRASES = (
    "subtle under-eye texture",
    "subtle under-eye shadows",
    "unposed moment",
    "slight motion softness at edges",
    "slightly desaturated tones",
    "half-finished iced coffee",
)

_REQUIRED_PHRASES = (
    "bright eyes",
    "lively expression",
    "upright relaxed posture",
    "avoid tired or sleepy expressions",
)


def test_people_prompts_drop_tired_low_energy_descriptions() -> None:
    for prompt_fn in _SYSTEM_PROMPTS:
        prompt = prompt_fn()
        for phrase in _REMOVED_PHRASES:
            assert phrase not in prompt


def test_people_prompts_push_bright_energetic_expression_defaults() -> None:
    for prompt_fn in _SYSTEM_PROMPTS:
        prompt = prompt_fn()
        for phrase in _REQUIRED_PHRASES:
            assert phrase in prompt
