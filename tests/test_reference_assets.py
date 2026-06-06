from __future__ import annotations

from pathlib import Path

from src.agent_os.reference_assets import ReferenceAsset, ReferenceAssetBatch, ReferenceAssetStore


def test_reference_asset_schema_stays_minimal() -> None:
    assert set(ReferenceAsset.model_fields) == {"path", "label", "description", "use_as"}
    assert set(ReferenceAssetBatch.model_fields) == {"batch_id", "instruction", "images"}


def test_reference_asset_store_creates_reads_and_lists_batches(tmp_path: Path) -> None:
    source = tmp_path / "uploads" / "bag.jpg"
    source.parent.mkdir()
    source.write_bytes(b"bag-bytes")
    store = ReferenceAssetStore(tmp_path / "agent-os")

    batch = store.create_batch(
        instruction="这批图用于雨天通勤图文，实物必须迁移到新场景。",
        images=[
            ReferenceAsset(
                path=str(source),
                label="black_bag",
                description="黑色尼龙通勤包，肩带和拉链必须保留。",
                use_as="object_transfer",
            )
        ],
    )

    copied_path = Path(batch.images[0].path)
    assert batch.batch_id
    assert copied_path.exists()
    assert copied_path.read_bytes() == b"bag-bytes"
    assert copied_path.parent.name == batch.batch_id

    loaded = store.get_batch(batch.batch_id)
    assert loaded == batch
    assert store.list_batches() == [batch]
