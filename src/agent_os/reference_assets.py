from __future__ import annotations

import json
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ReferenceAsset(BaseModel):
    path: str
    label: str = ""
    description: str = ""
    use_as: str = "style_reference"

    model_config = {"extra": "forbid"}


class ReferenceAssetBatch(BaseModel):
    batch_id: str
    instruction: str = ""
    images: list[ReferenceAsset] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class ReferenceAssetStore:
    """SQLite-backed store for user-described reference image batches."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.assets_root = self.root / "assets"
        self.assets_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "resources.db"
        self._init_db()

    def create_batch(
        self,
        *,
        instruction: str,
        images: list[ReferenceAsset | dict[str, Any] | str],
        batch_id: str | None = None,
    ) -> ReferenceAssetBatch:
        resolved_batch_id = batch_id or f"refbatch_{uuid4().hex[:12]}"
        batch_dir = self.assets_root / resolved_batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)

        stored_images = [
            self._copy_asset(asset, batch_dir=batch_dir, index=index)
            for index, asset in enumerate(images, start=1)
        ]
        batch = ReferenceAssetBatch(
            batch_id=resolved_batch_id,
            instruction=instruction.strip(),
            images=stored_images,
        )
        payload = json.dumps(batch.model_dump(mode="json"), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reference_asset_batches(batch_id, instruction, payload)
                VALUES (?, ?, ?)
                """,
                (batch.batch_id, batch.instruction, payload),
            )
        return batch

    def get_batch(self, batch_id: str) -> ReferenceAssetBatch:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM reference_asset_batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Reference asset batch not found: {batch_id}")
        return ReferenceAssetBatch.model_validate_json(str(row[0]))

    def list_batches(self) -> list[ReferenceAssetBatch]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM reference_asset_batches ORDER BY rowid"
            ).fetchall()
        return [ReferenceAssetBatch.model_validate_json(str(row[0])) for row in rows]

    def _copy_asset(self, value: ReferenceAsset | dict[str, Any] | str, *, batch_dir: Path, index: int) -> ReferenceAsset:
        asset = self._coerce_asset(value)
        source = Path(asset.path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Reference image does not exist: {asset.path}")

        label = asset.label.strip() or f"reference_{index}"
        suffix = source.suffix or ".jpg"
        filename = f"{index:02d}_{_safe_filename(label)}{suffix}"
        destination = batch_dir / filename
        shutil.copy2(source, destination)

        return ReferenceAsset(
            path=str(destination.resolve()),
            label=label,
            description=asset.description.strip(),
            use_as=asset.use_as.strip() or "style_reference",
        )

    @staticmethod
    def _coerce_asset(value: ReferenceAsset | dict[str, Any] | str) -> ReferenceAsset:
        if isinstance(value, ReferenceAsset):
            return value
        if isinstance(value, str):
            source = Path(value)
            return ReferenceAsset(path=value, label=source.stem)
        return ReferenceAsset.model_validate(value)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reference_asset_batches (
                    batch_id TEXT PRIMARY KEY,
                    instruction TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", value).strip("._")
    return cleaned or "reference"
