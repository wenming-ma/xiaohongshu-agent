from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.orchestration.schemas import ResultEnvelope

from .schemas import AgentOSEvent, TaskRunSpec


class AgentOSStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    def append_event(self, event: AgentOSEvent) -> None:
        self._append_jsonl(self.events_path, event.model_dump(mode="json"))

    def read_events(self) -> list[AgentOSEvent]:
        if not self.events_path.exists():
            return []
        return [
            AgentOSEvent.model_validate_json(line)
            for line in self.events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def save_task_spec(self, spec: TaskRunSpec) -> None:
        task_dir = self.root / "tasks" / spec.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "task.json").write_text(
            json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def read_task_spec(self, task_id: str) -> TaskRunSpec:
        path = self.root / "tasks" / task_id / "task.json"
        return TaskRunSpec.model_validate_json(path.read_text(encoding="utf-8"))

    def save_envelope(
        self,
        task_id: str,
        label: str,
        envelope: ResultEnvelope[Any],
    ) -> None:
        steps_dir = self.root / "tasks" / task_id / "steps"
        steps_dir.mkdir(parents=True, exist_ok=True)
        path = steps_dir / f"{label}.json"
        path.write_text(
            json.dumps(envelope.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def read_envelope(self, task_id: str, label: str) -> ResultEnvelope[Any]:
        path = self.root / "tasks" / task_id / "steps" / f"{label}.json"
        return ResultEnvelope[Any].model_validate_json(path.read_text(encoding="utf-8"))

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
