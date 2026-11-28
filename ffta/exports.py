"""抽出条件とデータのスナップショットを同梱する。"""
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone

import pandas as pd

from .model import SCHEMA_VERSION, VERSION


def archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
    return buffer.getvalue()


def csv_bytes(frame: pd.DataFrame, dataset_kind: str) -> bytes:
    labeled = frame.copy()
    labeled.insert(0, "dataset_kind", dataset_kind)
    return labeled.to_csv(index=False).encode("utf-8-sig")


def result_archive(
    tables: dict[str, pd.DataFrame], *, dataset_kind: str, view: str, conditions: dict
) -> bytes:
    files, summaries = {}, {}
    for table, frame in tables.items():
        file = f"{table}.csv"
        content = csv_bytes(frame, dataset_kind)
        files[file] = content
        summaries[file] = {"rows": len(frame), "sha256": hashlib.sha256(content).hexdigest()}
    manifest = {
        "tool": "Fish Folk Taxonomy Analyzer",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "dataset_kind": dataset_kind,
        "exported_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "view": view,
        "conditions": conditions,
        "files": summaries,
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    return archive(files)
