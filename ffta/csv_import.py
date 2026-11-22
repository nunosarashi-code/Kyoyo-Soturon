"""CSVの一括検証とトランザクションによる取り込み。"""
import csv
import io
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .model import TABLES
from .storage import InputError, Issue, Record, integrity_issue, parse_record, transaction, validate_records, write_record


@dataclass
class ImportReport:
    counts: dict[str, int]
    issues: list[Issue]
    samples: dict[str, list[dict]]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _read_file(name: str, data: bytes) -> tuple[list[Record], list[Issue]]:
    table = name.removesuffix(".csv")
    if table not in TABLES or name != f"{table}.csv":
        return [], [Issue(name, None, "", "ファイル名を配布テンプレートと同じ名前にしてください。")]
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], [Issue(name, None, "", "文字コードをUTF-8にして保存してください。")]

    columns = TABLES[table].columns
    rows = csv.reader(io.StringIO(content, newline=""), strict=True)
    records, issues = [], []
    try:
        header = next(rows, [])
        if len(header) != len(set(header)):
            return [], [Issue(name, 1, "", "列名が重複しています。")]
        missing, extra = set(columns) - set(header), set(header) - set(columns)
        if missing or extra:
            issues = [Issue(name, 1, key, "必要な列がありません。") for key in sorted(missing)]
            issues += [Issue(name, 1, key, "テンプレートにない列です。") for key in sorted(extra)]
            return [], issues
        while True:
            start_line = rows.line_num + 1
            row = next(rows, None)
            if row is None:
                break
            if not row:
                continue
            if len(row) != len(header):
                issues.append(Issue(name, start_line, "", f"列数が一致しません（{len(row)}列 / 必要 {len(header)}列）。"))
                continue
            if not any(value.strip() for value in row):
                continue
            try:
                records.append(parse_record(table, dict(zip(header, row)), name, start_line))
            except InputError as exc:
                issues.extend(exc.issues)
    except csv.Error as exc:
        issues.append(Issue(name, max(rows.line_num, 1), "", f"CSV形式が不正です（{exc}）。"))
    return records, issues


def import_csv(
    path: Path, files: Mapping[str, bytes], *, preview: bool = True, seed_demo: bool = False
) -> ImportReport:
    records, issues = [], []
    counts, samples = {}, {}
    for name, data in files.items():
        parsed, errors = _read_file(name, data)
        counts[name] = len(parsed)
        if parsed:
            samples[name] = [record.values for record in parsed[:5]]
        records.extend(parsed)
        issues.extend(errors)
    report = ImportReport(counts, issues, samples)

    with transaction(path, write=True) as db:
        meta = db.execute("SELECT dataset_kind, demo_loaded FROM app_metadata").fetchone()
        if (meta["dataset_kind"] == "demo") != seed_demo:
            issues.append(Issue("データベース", None, "", "架空デモ用と研究用のデータベースを確認してください。"))
            return report
        if seed_demo and meta["demo_loaded"]:
            return ImportReport({}, [], {})
        if not records and not issues:
            issues.append(Issue("CSV", None, "", "取り込むデータ行がありません。"))
        issues.extend(validate_records(db, records))
        if issues:
            return report

        # 親単位の行が後にあっても参照できるようにする。検証時は書き込みをロールバックする。
        db.execute("PRAGMA defer_foreign_keys = ON")
        order = {table: index for index, table in enumerate(TABLES)}
        for record in sorted(records, key=lambda row: order[row.table]):
            try:
                write_record(db, record)
            except sqlite3.IntegrityError as exc:
                issues.append(integrity_issue(record, exc))
        if not issues and db.execute("PRAGMA foreign_key_check").fetchone():
            issues.append(Issue("CSV", None, "", "参照IDの整合性を確認してください。"))
        if issues or preview:
            db.rollback()
        elif seed_demo:
            db.execute("UPDATE app_metadata SET demo_loaded = 1")
    return report
