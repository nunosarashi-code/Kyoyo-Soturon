"""SQLite の初期化、入力検証、登録・更新・削除。"""
import math
import re
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from .model import DATASETS, DEMO_PREFIX, PURPOSES, SCHEMA_VERSION, TABLES, Field

SCHEMA = Path(__file__).with_name("schema.sql")
VERIFIED_ASSERTIONS = {
    "species": ("name_status", "verified"),
    "folk_units": ("unit_status", "documented"),
    "unit_species": ("certainty", "confirmed"),
    "name_species": ("certainty", "confirmed"),
}


@dataclass(frozen=True)
class Issue:
    location: str
    line: int | None
    field: str
    message: str


class InputError(ValueError):
    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__(" / ".join(issue.message for issue in issues))


class DatabaseError(RuntimeError):
    pass


@dataclass
class Record:
    table: str
    values: dict
    location: str
    line: int | None = None

    def issue(self, message: str, field: str = "") -> Issue:
        return Issue(self.location, self.line, field, message)


def _connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def initialize(path: Path, kind: str = "research") -> Path:
    if kind not in DATASETS:
        raise ValueError("不明なデータ区分です。")
    if sqlite3.sqlite_version_info < (3, 37):
        raise DatabaseError("SQLite 3.37 以上を搭載した Python が必要です。")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect(path)) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            existing = db.execute("SELECT name FROM sqlite_schema WHERE type IN ('table', 'view')").fetchone()
            if existing:
                raise DatabaseError("このファイルはFFTAのデータベースとして初期化できません。")
            # kind は上の固定値検証を通過している。
            db.executescript(
                "BEGIN IMMEDIATE;\n" + SCHEMA.read_text(encoding="utf-8")
                + f"\nINSERT OR IGNORE INTO app_metadata (singleton, dataset_kind) VALUES (1, '{kind}');"
                + f"\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;"
            )
        elif version != SCHEMA_VERSION:
            raise DatabaseError(f"スキーマのバージョン {version} には対応していません。")
        meta = db.execute("SELECT dataset_kind FROM app_metadata WHERE singleton = 1").fetchone()
        if not meta or meta["dataset_kind"] != kind:
            raise DatabaseError("指定されたSQLiteファイルの研究・架空デモ区分が一致しません。")
    return path


@contextmanager
def transaction(path: Path, *, write: bool = False):
    # 検索の複数クエリは同じスナップショットを参照する。
    with closing(_connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield db


def read_table(db: sqlite3.Connection, table: str) -> list[dict]:
    spec = TABLES[table]
    columns = [name for name in spec.columns if name != "purposes"]
    parts = ", ".join(columns)
    rows = [dict(row) for row in db.execute(f"SELECT {parts} FROM {table} ORDER BY {spec.key}")]
    if table == "uses":
        purposes: dict[str, set[str]] = {}
        for link in db.execute("SELECT use_id, purpose FROM use_purposes"):
            purposes.setdefault(link["use_id"], set()).add(link["purpose"])
        for row in rows:
            row["purposes"] = "|".join(p for p in PURPOSES if p in purposes.get(row["use_id"], ()))
    return rows


def _read_record(db: sqlite3.Connection, table: str, key: str) -> dict | None:
    spec = TABLES[table]
    columns = ", ".join(name for name in spec.columns if name != "purposes")
    row = db.execute(f"SELECT {columns} FROM {table} WHERE {spec.key} = ?", (key,)).fetchone()
    if row is None:
        return None
    result = dict(row)
    if table == "uses":
        purposes = {p[0] for p in db.execute("SELECT purpose FROM use_purposes WHERE use_id = ?", (key,))}
        result["purposes"] = "|".join(p for p in PURPOSES if p in purposes)
    return result


def _parse(field: Field, raw: str | None):
    if raw is None or not raw.strip():
        if field.required:
            raise ValueError("必須項目です。")
        return () if field.kind == "purposes" else None
    if "\x00" in raw:
        raise ValueError("NUL文字を含む値は使用できません。")
    if field.kind == "purposes":
        values = raw.split("|")
        if unknown := set(values) - PURPOSES.keys():
            raise ValueError(f"未定義の利用目的があります（{', '.join(repr(p) for p in sorted(unknown))}）。")
        if len(values) != len(set(values)):
            raise ValueError("同じ利用目的が重複しています。")
        return tuple(p for p in PURPOSES if p in values)
    if field.choices and raw not in field.choices:
        raise ValueError(f"次のコードを使用してください（{' / '.join(field.choices)}）。")
    if field.kind == "id" and (raw != raw.strip() or not raw.isprintable()):
        raise ValueError("IDの前後の空白や制御文字を取り除いてください。")
    if field.kind == "year":
        if not re.fullmatch(r"[0-9]{1,4}", raw) or int(raw) < 1:
            raise ValueError("発表年は1〜9999の整数を入力してください。")
        return int(raw)
    if field.kind == "date":
        try:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
                raise ValueError
            date.fromisoformat(raw)
        except ValueError:
            raise ValueError("実在する日付を YYYY-MM-DD で入力してください。") from None
    if field.kind in ("latitude", "longitude"):
        limit = 90 if field.kind == "latitude" else 180
        try:
            if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", raw):
                raise ValueError
            value = float(raw)
            if not math.isfinite(value) or not -limit <= value <= limit:
                raise ValueError
        except ValueError:
            raise ValueError(f"-{limit}〜{limit} の十進度で入力してください。") from None
        return value
    if field.kind == "locator":
        try:
            url = urlsplit(raw)
            valid_url = url.scheme in ("http", "https") and url.hostname and not any(c.isspace() for c in raw)
        except ValueError:
            valid_url = False
        if not valid_url and not re.fullmatch(r"(?:doi:)?10\.[0-9]{4,9}/\S+", raw, re.IGNORECASE):
            raise ValueError("DOIまたは http/https のURLを入力してください。")
    return raw


def parse_record(table: str, raw: dict, location: str, line: int | None = None) -> Record:
    record = Record(table, {}, location, line)
    errors = []
    for field in TABLES[table].fields:
        try:
            record.values[field.name] = _parse(field, raw.get(field.name))
        except ValueError as exc:
            errors.append(record.issue(str(exc), field.name))
    if errors:
        raise InputError(errors)
    return record


def check_record_rules(record: Record, kind: str) -> list[Issue]:
    table, row = record.table, record.values
    id_column = TABLES[table].key
    reserved = row[id_column].upper().startswith(DEMO_PREFIX)
    issues = []
    if reserved != (kind == "demo"):
        issues.append(record.issue("DEMO_ で始まるIDは架空デモ専用です。", id_column))
    if table == "sources" and row["verification_status"] == "verified":
        if not row["title"] or not any(row[key] for key in ("author", "publication", "doi_url")):
            issues.append(record.issue("出典を確認済みにするには、表題と著者・掲載誌・DOI/URLのいずれかが必要です。"))
    if table == "species":
        if not (row["standard_name"] or row["scientific_name"]):
            issues.append(record.issue("標準和名または学名を入力してください。"))
        elif row["name_status"] == "verified" and not (row["standard_name"] and row["scientific_name"]):
            issues.append(record.issue("和名・学名の対応を確認済みにするには、両方の名前が必要です。"))
    if table == "local_names" and (row["form_type"] == "unresolved") != (row["unit_id"] is None):
        issues.append(record.issue("所属未確認の地方名は単位IDを空欄にし、呼称・別名には単位IDを指定してください。", "unit_id"))
    if table == "uses":
        if (row["species_id"] is None) == (row["unit_id"] is None):
            issues.append(record.issue("利用の対象は魚種IDまたは民俗分類単位IDの一方を指定してください。"))
        if row["use_status"] == "used" and not row["purposes"]:
            issues.append(record.issue("利用ありの場合は、利用目的を1つ以上入力してください。", "purposes"))
        if row["use_status"] == "not_used" and not row["source_id"]:
            issues.append(record.issue("利用なしの明記をたどれる出典IDが必要です。", "source_id"))
    return issues


def validate_records(db: sqlite3.Connection, records: list[Record], *, editing: bool = False) -> list[Issue]:
    kind = db.execute("SELECT dataset_kind FROM app_metadata").fetchone()[0]
    details = {
        "sources": ", verification_status",
        "folk_units": ", parent_unit_id, context_id",
    }
    known = {}
    for table, spec in TABLES.items():
        rows = db.execute(f"SELECT {spec.key}{details.get(table, '')} FROM {table}")
        known[table] = {row[spec.key]: dict(row) for row in rows}

    issues = []
    for record in records:
        table, row = record.table, record.values
        key = TABLES[table].key
        if row[key] in known[table] and not editing:
            issues.append(record.issue(f"ID「{row[key]}」が重複しています。", key))
        known[table][row[key]] = row

    for record in records:
        table, row = record.table, record.values
        issues.extend(check_record_rules(record, kind))
        for field in TABLES[table].fields:
            if field.reference and row[field.name] is not None and row[field.name] not in known[field.reference]:
                issues.append(record.issue(
                    f"{TABLES[field.reference].label}にID「{row[field.name]}」がありません。", field.name
                ))
        if table in VERIFIED_ASSERTIONS:
            field, expected = VERIFIED_ASSERTIONS[table]
            source = known["sources"].get(row["source_id"], {})
            if row[field] == expected and source.get("verification_status") != "verified":
                issues.append(record.issue("確認済みの出典IDが必要です。", "source_id"))
        if table in ("folk_units", "local_names", "uses"):
            field = "parent_unit_id" if table == "folk_units" else "unit_id"
            unit = known["folk_units"].get(row[field])
            if unit and unit["context_id"] != row["context_id"]:
                issues.append(record.issue("参照先の分類単位と同じ調査文脈を指定してください。", field))
        if table == "folk_units":
            seen = {row["unit_id"]}
            ancestor = row["parent_unit_id"]
            while ancestor in known["folk_units"]:
                if ancestor in seen:
                    issues.append(record.issue("分類階層が循環しています。", "parent_unit_id"))
                    break
                seen.add(ancestor)
                ancestor = known["folk_units"][ancestor]["parent_unit_id"]
    return issues


def write_record(db: sqlite3.Connection, record: Record, *, editing: bool = False) -> None:
    table, row = record.table, record.values
    spec = TABLES[table]
    key = row[spec.key]
    columns = [name for name in spec.columns if name != "purposes"]
    if editing:
        mutable = columns[1:]
        assignments = ", ".join(f"{name} = ?" for name in mutable)
        db.execute(
            f"UPDATE {table} SET {assignments} WHERE {spec.key} = ?",
            [row[name] for name in mutable] + [key],
        )
    else:
        db.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            [row[name] for name in columns],
        )
    if table == "uses":
        if editing:
            db.execute("DELETE FROM use_purposes WHERE use_id = ?", (key,))
        db.executemany(
            "INSERT INTO use_purposes (use_id, purpose) VALUES (?, ?)",
            [(key, purpose) for purpose in row["purposes"]],
        )


def integrity_issue(record: Record, exc: sqlite3.IntegrityError) -> Issue:
    detail = str(exc)
    if "verified_scientific_name" in detail:
        message = "確認済みの同じ学名が別の魚種IDに登録されています。"
    elif "UNIQUE constraint failed" in detail:
        message = "ID、または同じ出典に基づく同一の記載が重複しています。"
    elif "FOREIGN KEY constraint failed" in detail:
        message = "この変更と矛盾する参照があります。先に参照するレコードの出典の確認状況や調査文脈を見直してください。"
    elif "hierarchy_cycle" in detail:
        message = "分類階層が循環しています。"
    else:
        message = f"SQLiteのデータ制約に合いません（{detail}）。"
    return record.issue(message)


def _assert_research(db: sqlite3.Connection) -> None:
    if db.execute("SELECT dataset_kind FROM app_metadata").fetchone()[0] != "research":
        raise InputError([Issue("データ管理", None, "", "架空デモは閲覧専用です。")])


def _assert_current(db: sqlite3.Connection, table: str, original: dict) -> None:
    key = original[TABLES[table].key]
    if _read_record(db, table, key) != original:
        raise InputError([Issue(TABLES[table].label, None, "", "別の操作で更新されました。一覧を更新してから操作してください。")])


def save_record(path: Path, table: str, raw: dict, *, original: dict | None = None) -> None:
    record = parse_record(table, raw, TABLES[table].label)
    key = TABLES[table].key
    if original is not None and record.values[key] != original[key]:
        raise InputError([record.issue("編集時はIDを変更できません。", key)])
    with transaction(path, write=True) as db:
        _assert_research(db)
        if original is not None:
            _assert_current(db, table, original)
        issues = validate_records(db, [record], editing=original is not None)
        if issues:
            raise InputError(issues)
        try:
            write_record(db, record, editing=original is not None)
        except sqlite3.IntegrityError as exc:
            raise InputError([integrity_issue(record, exc)]) from exc


def delete_record(path: Path, table: str, original: dict) -> None:
    key = TABLES[table].key
    with transaction(path, write=True) as db:
        _assert_research(db)
        _assert_current(db, table, original)
        try:
            db.execute(f"DELETE FROM {table} WHERE {key} = ?", (original[key],))
        except sqlite3.IntegrityError as exc:
            raise InputError([Issue(TABLES[table].label, None, key, "他の記録で使用中のIDです。参照を先に見直してください。")]) from exc
