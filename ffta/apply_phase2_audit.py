"""2026-11-25の資料照合を、復旧DBの新しいコピーへ反映する。"""
import argparse
import csv
import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from .model import TABLES
from .recovery_inputs import indexed
from .storage import InputError, parse_record, read_table, transaction, validate_records, write_record

BASE_SHA256 = "6691469c99e9b50b178d4b4c4353d691e2e88b5ae6787860a3c13753bab2a2cb"
JAF_SOURCE = {
    "source_id": "SRC_JAF43",
    "author": "本村浩之",
    "year": "2026",
    "title": "日本産魚類全種目録 Online ver.43",
    "publication": "鹿児島大学総合研究博物館",
    "doi_url": "https://www.museum.kagoshima-u.ac.jp/staff/motomura/20261025_JAFList.xlsx",
    "page": "2026-10-25版。該当行はscientific_name_audit.csv",
    "extracted_on": "2026-11-25",
    "verification_status": "verified",
}
AUDIT_REQUIRED = {
    "source_audit": {
        "record_type", "record_id", "source_id", "context_id", "standard_name", "check_status", "checked_on",
        "source_url", "page", "locator", "life_stage_size", "stage_source_url", "stage_page", "stage_locator",
    },
    "scientific_name_audit": {
        "species_id", "standard_name", "check_status", "previous_database_name", "previous_database_source_id",
        "jaf_name", "jaf_url", "jaf_locator", "jaf_family", "jaf_order", "worms_status",
        "worms_accepted_name", "worms_url", "historical_specimen_status", "checked_on",
    },
    "folk_unit_audit": {
        "legacy_unit_id", "context_id", "source_id", "local_name_ids", "stage_name_ids",
        "folk_unit_judgment", "retained_unit_status",
    },
    "use_evidence": {"record_id", "registration"},
}


def _new_destination(path: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = path.with_name(path.name + suffix)
        if candidate.exists() or candidate.is_symlink():
            raise FileExistsError(f"既存ファイルがあるため、新しい保存先を指定してください（{candidate}）。")


def _audit_rows(path: Path, required: set[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, strict=True)
        header = reader.fieldnames or []
        if len(set(header)) != len(header) or not required.issubset(header):
            raise ValueError(f"{path.name} の見出しが監査の入力仕様と一致しません。")
        rows = list(reader)
        if any(None in row or None in row.values() for row in rows):
            raise ValueError(f"{path.name} に列の欠落または余分な列があります。")
    return rows


def _write(db, table: str, row: dict, *, editing: bool) -> None:
    raw = {key: None if value is None else str(value) for key, value in row.items()}
    record = parse_record(table, raw, f"Phase 2 {table}")
    if issues := validate_records(db, [record], editing=editing):
        raise InputError(issues)
    write_record(db, record, editing=editing)


def _matches(audited: dict, original: dict, table: str) -> None:
    if audited.keys() != original.keys():
        raise ValueError(f"{table} の監査IDと元DBのID集合が一致しません。")


def _require_evidence(url: str, page: str, locator: str) -> None:
    if not url.startswith("https://") or not page.strip() or not locator.strip():
        raise ValueError("確認済み記録には資料URL・頁または区分・箇所が必要です。")


def _apply_to_copy(path: Path, files: dict[str, list[dict]]) -> dict:
    with transaction(path, write=True) as db:
        meta = db.execute("SELECT dataset_kind, demo_loaded FROM app_metadata").fetchone()
        if tuple(meta) != ("research", 0):
            raise ValueError("研究用DBを指定してください。")
        originals = {
            table: indexed(read_table(db, table), table, spec.key)
            for table, spec in TABLES.items()
        }

        citations = files["source_audit"]
        if any(row["record_type"] not in ("bibliography", "local_name") for row in citations):
            raise ValueError("出典監査に想定外の行区分があります。")
        bibliography = indexed([r for r in citations if r["record_type"] == "bibliography"], "書誌監査", "record_id")
        naming = indexed([r for r in citations if r["record_type"] == "local_name"], "地方名監査", "record_id")
        taxonomy = indexed(files["scientific_name_audit"], "学名監査", "species_id")
        units = indexed(files["folk_unit_audit"], "民俗分類単位監査", "legacy_unit_id")
        uses = indexed(files["use_evidence"], "利用監査", "record_id")
        _matches(bibliography, originals["sources"], "出典")
        _matches(naming, originals["local_names"], "地方名")
        _matches(taxonomy, originals["species"], "魚種")
        _matches(units, originals["folk_units"], "民俗分類単位")
        direct = indexed(list(originals["name_species"].values()), "地方名の直接対応", "local_name_id")
        _matches(naming, direct, "資料内の名称対応")
        unit_links = indexed(list(originals["unit_species"].values()), "仮置き単位の種対応", "unit_id")
        _matches({key: row for key, row in uses.items() if row["registration"] == "retained"}, originals["uses"], "既存利用")
        if any(row["registration"] not in ("retained", "held", "documentary_only") for row in uses.values()):
            raise ValueError("この監査は利用候補の採用を扱いません。")

        unit_name_ids = []
        for key, audit in units.items():
            original = originals["folk_units"][key]
            if (
                (audit["context_id"], audit["source_id"]) != (original["context_id"], original["source_id"])
                or audit["retained_unit_status"] != original["unit_status"]
                or audit["folk_unit_judgment"] != "indeterminate"
            ):
                raise ValueError(f"{key} の仮置き状態・文脈を確認してください。")
            name_ids = audit["local_name_ids"].split(" | ")
            if any(
                name_id not in naming or naming[name_id]["context_id"] != original["context_id"]
                or direct[name_id]["species_id"] != unit_links[key]["species_id"]
                for name_id in name_ids
            ):
                raise ValueError(f"{key} に文脈または標準和名の異なる地方名があります。")
            if {name_id for name_id in name_ids if naming[name_id]["life_stage_size"]} != set(
                filter(None, audit["stage_name_ids"].split(" | "))
            ):
                raise ValueError(f"{key} の大きさ・成長の根拠が地方名監査と一致しません。")
            unit_name_ids.extend(name_ids)
        if Counter(unit_name_ids) != Counter(naming.keys()):
            raise ValueError("旧単位と地方名の監査に欠落または二重登録があります。")

        for key, audit in bibliography.items():
            original = originals["sources"][key]
            if audit["source_id"] != key or audit["source_url"] != original["doi_url"]:
                raise ValueError(f"{key} のURLまたは出典IDが元DBと一致しません。")
            if audit["check_status"] not in ("confirmed", "partial", "unconfirmed"):
                raise ValueError(f"{key} の書誌照合状態が不明です。")
            if audit["check_status"] == "confirmed":
                _require_evidence(audit["source_url"], audit["page"], audit["locator"])
                _write(db, "sources", original | {"verification_status": "verified"}, editing=True)
        _write(db, "sources", JAF_SOURCE, editing=False)

        for key, audit in taxonomy.items():
            original = originals["species"][key]
            if (
                audit["standard_name"] != original["standard_name"]
                or audit["previous_database_name"] != (original["scientific_name"] or "")
                or audit["previous_database_source_id"] != original["source_id"]
                or audit["jaf_url"] != JAF_SOURCE["doi_url"]
                or audit["historical_specimen_status"] != "unconfirmed"
            ):
                raise ValueError(f"{key} の学名監査が元DB・採用目録と一致しません。")
            _require_evidence(audit["jaf_url"], "ver.43", audit["jaf_locator"])
            _require_evidence(audit["worms_url"], "HTML", "受容学名")
            name = audit["jaf_name"].strip()
            agreed = audit["worms_status"] == "accepted" and audit["worms_accepted_name"] == name
            if len(name.split()) not in (2, 3) or audit["check_status"] != ("confirmed" if agreed else "indeterminate"):
                raise ValueError(f"{key} の学名照合状態と根拠が一致しません。")
            _write(db, "species", original | {
                "scientific_name": name, "genus": name.split()[0], "family": audit["jaf_family"],
                "taxonomic_order": audit["jaf_order"], "source_id": JAF_SOURCE["source_id"],
                "checked_on": audit["checked_on"], "name_status": "verified" if agreed else "unverified",
            }, editing=True)

        for key, audit in naming.items():
            original, mapping = originals["local_names"][key], direct[key]
            if (
                (audit["source_id"], audit["context_id"]) != (original["source_id"], original["context_id"])
                or audit["source_url"] != originals["sources"][original["source_id"]]["doi_url"]
                or audit["standard_name"] != originals["species"][mapping["species_id"]]["standard_name"]
            ):
                raise ValueError(f"{key} の監査文脈・標準和名・出典が元DBと一致しません。")
            if audit["check_status"] not in ("confirmed", "unconfirmed", "indeterminate"):
                raise ValueError(f"{key} の原資料照合状態が不明です。")
            if audit["check_status"] != "confirmed":
                if audit["life_stage_size"]:
                    raise ValueError(f"{key} に未照合の大きさ・成長段階が記載されています。")
                continue
            _require_evidence(audit["source_url"], audit["page"], audit["locator"])
            checked = f"{audit['checked_on']} 原資料掲載照合済み（{audit['page']}、{audit['locator']}）。"
            notes = "\n".join(filter(None, (mapping["notes"], checked)))
            _write(db, "name_species", mapping | {"notes": notes}, editing=True)
            if age := audit["life_stage_size"]:
                _require_evidence(audit["stage_source_url"], audit["stage_page"], audit["stage_locator"])
                stage_note = f"サイズ資料 {audit['stage_source_url']}（{audit['stage_page']}、{audit['stage_locator']}）"
                _write(db, "local_names", original | {
                    "life_stage_size": age, "notes": "\n".join(filter(None, (original["notes"], stage_note))),
                }, editing=True)

        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("検証DBのSQLite整合性または外部キーの検査に失敗しました。")
    return {
        "bibliography": dict(Counter(row["check_status"] for row in bibliography.values())),
        "local_name_attestations": dict(Counter(row["check_status"] for row in naming.values())),
        "name_agreement": dict(Counter(row["check_status"] for row in taxonomy.values())),
        "local_names_with_stage_evidence": sum(bool(row["life_stage_size"]) for row in naming.values()),
        "folk_units_retained_provisional": len(units), "new_registered_uses": 0,
    }


def build_validation_database(base: Path, audit_dir: Path, destination: Path) -> dict:
    """監査の対象とした元DBを検証し、新しい研究用DBを発行する。"""
    base, audit_dir, destination = Path(base), Path(audit_dir), Path(destination)
    _new_destination(destination)
    payload = base.read_bytes()
    baseline = hashlib.sha256(payload).hexdigest()
    if baseline != BASE_SHA256 or any(base.with_name(base.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("対象の2026-11-24復旧DBのSHA-256と一致しないか、DBが使用中です。")
    files = {name: _audit_rows(audit_dir / f"{name}.csv", required) for name, required in AUDIT_REQUIRED.items()}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".ffta-phase2-", dir=destination.parent) as folder:
        path = Path(folder) / "candidate.sqlite3"
        path.write_bytes(payload)
        counts = _apply_to_copy(path, files)
        result_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        _new_destination(destination)
        os.link(path, destination)
    return {"database": str(destination), "baseline_sha256": baseline, "database_sha256": result_hash, **counts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recovered_database", type=Path)
    parser.add_argument("--audit-dir", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path, help="新規保存先")
    args = parser.parse_args(argv)
    try:
        report = build_validation_database(args.recovered_database, args.audit_dir, args.database)
    except (OSError, ValueError, KeyError, sqlite3.Error, csv.Error) as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
