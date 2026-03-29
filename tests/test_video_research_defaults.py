import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_AGENT_PATH = PROJECT_ROOT / "src" / "agents" / "video_post" / "research" / "agent.py"


def test_video_research_initial_quality_target_defaults_to_ten() -> None:
    tree = ast.parse(RESEARCH_AGENT_PATH.read_text(encoding="utf-8"))
    constants = {}

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        try:
            constants[node.targets[0].id] = ast.literal_eval(node.value)
        except (SyntaxError, ValueError):
            continue

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "VideoListQualityFilter":
            continue

        keyword_values = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                continue
            if isinstance(keyword.value, ast.Name):
                keyword_values[keyword.arg] = constants[keyword.value.id]
            else:
                keyword_values[keyword.arg] = ast.literal_eval(keyword.value)
        assert keyword_values["min_quality_videos"] == 10
        return

    raise AssertionError("VideoListQualityFilter configuration not found in research agent")
