from pathlib import Path

from packrecorder.recording_index import RecordingIndex


def test_insert_and_search(tmp_path: Path) -> None:
    db = tmp_path / "i.sqlite"
    idx = RecordingIndex(db)
    idx.connect()
    idx.insert(
        order_id="ORD1",
        packer="M1",
        rel_key="2026-04-08/ORD1_M1_2026-04-08_12-00-00.mp4",
        storage_status="local_only",
        primary_root=str(tmp_path / "p"),
        backup_root=str(tmp_path / "b"),
        resolved_path=str(tmp_path / "b" / "f.mp4"),
        created_at="2026-04-08T12:00:00",
    )
    rows = idx.search(order_substring="ORD")
    idx.close()
    assert len(rows) == 1
    assert rows[0]["order_id"] == "ORD1"
