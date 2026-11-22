"""指定したPhase 1形式のCSV一式から、別のSQLiteを作成する。"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from .csv_import import import_csv
from .model import SCHEMA_VERSION, TABLES
from .storage import DatabaseError, InputError, initialize, transaction


def _ensure_new_target(destination: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = destination.with_name(destination.name + suffix)
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"既存のファイルを保護するため、新しい保存先を指定してください（{path}）。")


def rebuild_database(csv_dir: Path, destination: Path) -> dict:
    """1フォルダーの全体CSVを検証し、存在しないパスにDBを保存する。"""
    csv_dir, destination = Path(csv_dir), Path(destination)
    _ensure_new_target(destination)
    expected = {f"{table}.csv" for table in TABLES}
    actual = {path.name for path in csv_dir.iterdir() if path.suffix.lower() == ".csv"}
    missing, extra = sorted(expected - actual), sorted(actual - expected)
    if missing or extra:
        raise ValueError(f"Phase 1形式のCSV一式を指定してください。不足 {missing}、想定外 {extra}。")
    files = {name: (csv_dir / name).read_bytes() for name in sorted(expected)}

    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".ffta-rebuild-", dir=destination.parent) as staged:
        db_path = initialize(Path(staged) / "candidate.sqlite3")
        result = import_csv(db_path, files, preview=False)
        if result.issues:
            raise InputError(result.issues)
        with transaction(db_path) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise DatabaseError("作成したDBがSQLiteの整合性検査に失敗しました。")
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise DatabaseError("作成したDBに不整合な参照があります。")
            rows = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}
            rows["use_purposes"] = db.execute("SELECT COUNT(*) FROM use_purposes").fetchone()[0]
        # 同じファイルシステム上で、新規作成として公開する。既存パスは置換しない。
        _ensure_new_target(destination)
        os.link(db_path, destination)

    return {
        "database": str(destination),
        "schema_version": SCHEMA_VERSION,
        "rows": rows,
        "input_sha256": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_directory", type=Path, help="正規化済みの全体CSV9種類があるフォルダー")
    parser.add_argument("--database", type=Path, required=True, help="新規のSQLiteファイルのパス")
    args = parser.parse_args(argv)
    try:
        report = rebuild_database(args.csv_directory, args.database)
    except InputError as error:
        for issue in error.issues:
            line = f" {issue.line}行" if issue.line is not None else ""
            column = f" [{issue.field}]" if issue.field else ""
            print(f"{issue.location}{line}{column}　{issue.message}", file=sys.stderr)
        return 1
    except (OSError, ValueError, DatabaseError, sqlite3.Error) as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
