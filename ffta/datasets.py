"""研究用SQLiteと同梱の架空デモを別ファイルで扱う。"""
import os
from pathlib import Path

from .csv_import import import_csv
from .storage import DatabaseError, initialize, transaction

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "csv" / "templates"
DEMO_CSV = ROOT / "csv" / "demo"


def get_database(kind: str) -> Path:
    directory = Path(os.environ.get("FFTA_DATA_DIR", ROOT / "data")).expanduser()
    if kind == "research":
        return initialize(directory / "ffta.sqlite3")
    if kind != "demo":
        raise ValueError("不明なデータ区分です。")
    path = initialize(directory / "ffta_demo.sqlite3", "demo")
    with transaction(path) as db:
        loaded = db.execute("SELECT demo_loaded FROM app_metadata").fetchone()[0]
    if not loaded:
        report = import_csv(
            path, {file.name: file.read_bytes() for file in sorted(DEMO_CSV.glob("*.csv"))},
            preview=False, seed_demo=True,
        )
        if report.issues:
            raise DatabaseError("同梱の架空デモを取り込めませんでした。")
    return path
