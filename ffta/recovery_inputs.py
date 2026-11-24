"""2026-11-23復旧バンドルの構造を検証し、Phase 1形式に変換する。"""
import csv
import hashlib
import io
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from .model import TABLES

INITIAL_ARCHIVE = "FFTA_realdata_pilot_2026-11-06.zip"
FULL_ARCHIVE = "FFTA_evidence_update_2026-11-08.zip"
DELTA_ARCHIVE = "FFTA_Codex_validation_2026-11-08.zip"
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
LEGACY_COLUMNS = {
    "sources": "source_id author year title publisher doi_url pages quotation extracted_on verification notes",
    "species": "species_id japanese_name scientific_name genus family taxonomic_order taxonomy_source checked_on verification source_id",
    "regions": "region_id prefecture locality latitude longitude characteristics survey_period source_id",
    "contexts": "context_id region_id period user_group survey_method scope recording_density source_id notes",
    "folk_units": "unit_id context_id label parent_unit_id hierarchy growth_stage criteria certainty source_id notes",
    "local_names": "name_id unit_id spelling reading source_id notes",
    "mappings": "mapping_id unit_id species_id certainty source_id notes",
    "uses": "use_id context_id species_id unit_id status purpose body_part method frequency cultural_importance source_id notes",
}
AUDIT_COLUMNS = (
    "region standard_name local_name locality source_url source_page original_note record_type verification "
    "analysis_eligible issues this_round_source_check folk_unit_validated usage_validated_for_same_context "
    "research_status audit_note"
)
COMPARE_COLUMNS = "standard_name hokkaido_name_count fukushima_name_count comparable_for_granularity reason"
NAME_CONTEXTS = ("CTX_HRO", "CTX_FUK")
AUDIT_REGIONS = {"CTX_HRO": "北海道・道北", "CTX_FUK": "福島県"}


@dataclass
class RecoveryInputs:
    normalized: dict[str, list[dict[str, str]]]
    inventory: dict
    audit_files: dict[str, bytes]
    reference_comparison: list[dict[str, str]]
    checks: dict


def describe(payload: bytes) -> dict:
    return {"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def read_archive(blob: bytes, name: str) -> tuple[dict[str, bytes], dict]:
    """CRCを検査し、ZIPエントリをファイルシステムに展開せずに取得する。"""
    if len(blob) > MAX_ARCHIVE_BYTES:
        raise ValueError(f"{name} が想定する入力サイズを超えています。")
    with ZipFile(io.BytesIO(blob)) as archive:
        entries = [info for info in archive.infolist() if not info.is_dir()]
        if sum(entry.file_size for entry in entries) > MAX_ARCHIVE_BYTES:
            raise ValueError(f"{name} の解凍サイズが上限を超えています。")
        if len(set(entry.filename for entry in entries)) != len(entries):
            raise ValueError(f"{name} に同名のZIPエントリがあります。")
        files = {entry.filename: archive.read(entry) for entry in entries}
    summary = {
        "name": name,
        **describe(blob),
        "files": {filename: describe(content) for filename, content in files.items()},
    }
    return files, summary


def read_csv(payload: bytes, columns: str, label: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig"), newline=""), strict=True)
    expected = columns.split()
    header = reader.fieldnames or []
    if len(header) != len(expected) or set(header) != set(expected):
        raise ValueError(f"{label} の見出しが2026-11-08版の仕様と一致しません。")
    rows = []
    for row in reader:
        if None in row or None in row.values():
            raise ValueError(f"{label} の{reader.line_num}行目は列数が見出しと一致しません。")
        rows.append(row)
    return rows


def indexed(rows: list[dict], label: str, *columns: str) -> dict:
    result = {}
    for row in rows:
        values = tuple(row[column] for column in columns)
        key = values[0] if len(columns) == 1 else values
        if not all(values) or key in result:
            raise ValueError(f"{label} に空欄または重複するキーがあります（{key}）。")
        result[key] = row
    return result


def _legacy_tables(archive: dict[str, bytes]) -> dict[str, list[dict]]:
    return {
        table: read_csv(archive[f"{table}.csv"], columns, f"{table}.csv")
        for table, columns in LEGACY_COLUMNS.items()
    }


def _reconcile(
    initial: dict[str, list[dict]], full: dict[str, list[dict]], delta: dict[str, bytes]
) -> dict:
    delta_tables = {"sources", "regions", "contexts", "uses"}
    checks = {}
    for table, columns in LEGACY_COLUMNS.items():
        key = columns.split()[0]
        before = indexed(initial[table], f"初期版 {table}", key)
        current = indexed(full[table], f"全体版 {table}", key)
        name = f"{table}_NEW_ONLY.csv"
        added = indexed(read_csv(delta[name], columns, name), name, key) if table in delta_tables else {}
        if before.keys() & added.keys() or current.keys() != (before.keys() | added.keys()):
            raise ValueError(f"{table} の初期版・全体版・差分のID集合が整合しません。")
        if any(current[row_id] != row for row_id, row in added.items()):
            raise ValueError(f"{table} の差分の内容が全体版に一致しません。")
        checks[table] = {
            "initial_rows": len(before), "full_rows": len(current), "delta_rows": len(added),
            "updated_existing_rows": sum(current[row_id] != row for row_id, row in before.items()),
        }
    return checks


def _renamed(row: dict[str, str], renames: dict[str, str], *, omit: tuple[str, ...] = ()) -> dict[str, str]:
    return {renames.get(key, key): value for key, value in row.items() if key not in omit}


def _translate(value: str, codes: dict[str, str], label: str) -> str:
    if value not in codes:
        raise ValueError(f"{label} に対応表にない値があります（{value}）。")
    return codes[value]


def _convert_names(full: dict[str, list[dict]], audit: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    sources = indexed(full["sources"], "出典", "source_id")
    contexts = indexed(full["contexts"], "調査文脈", "context_id")
    units = indexed(full["folk_units"], "仮置き単位", "unit_id")
    mappings = indexed(full["mappings"], "仮置き単位の対応", "unit_id")
    species = indexed(full["species"], "魚種", "species_id")
    audit_by_key = indexed(audit, "行単位監査", "source_url", "standard_name", "local_name")

    names, direct, metadata = [], [], []
    for old in full["local_names"]:
        name_id, unit_id, source_id = old["name_id"], old["unit_id"], old["source_id"]
        unit, mapping = units[unit_id], mappings[unit_id]
        context_id, species_id = unit["context_id"], mapping["species_id"]
        if source_id != unit["source_id"] or source_id != mapping["source_id"] or source_id != contexts[context_id]["source_id"]:
            raise ValueError(f"{name_id} の旧単位・対応・文脈の出典IDが一致しません。")
        audit_key = (sources[source_id]["doi_url"], species[species_id]["japanese_name"], old["spelling"])
        try:
            evidence = audit_by_key.pop(audit_key)
        except KeyError as error:
            raise ValueError(f"{name_id} と1対1で対応する行単位監査がありません。") from error
        if (
            evidence["region"] != AUDIT_REGIONS.get(context_id)
            or evidence["record_type"] != "名称-標準和名対応"
            or evidence["verification"] != "原資料表示照合済／分類単位未確認"
            or evidence["folk_unit_validated"] != "いいえ"
            or evidence["analysis_eligible"] != "いいえ"
            or evidence["usage_validated_for_same_context"] != "いいえ"
        ):
            raise ValueError(f"{name_id} の監査内容が探索用の名称対応の条件と一致しません。")
        mapping_id = f"PAIR_{name_id}"
        names.append({
            "local_name_id": name_id, "spelling": old["spelling"], "reading": old["reading"],
            "context_id": context_id, "unit_id": "", "form_type": "unresolved", "life_stage_size": "",
            "notes": old["notes"], "source_id": source_id,
        })
        notes = "\n".join([
            f"原資料箇所 {evidence['source_page']}",
            f"2026-11-08監査 {evidence['this_round_source_check']}",
            evidence["audit_note"],
            f"旧仮置き単位ID {unit_id}",
        ])
        direct.append({
            "name_mapping_id": mapping_id, "local_name_id": name_id, "species_id": species_id,
            "certainty": "uncertain", "source_id": source_id, "notes": notes,
        })
        metadata.append({
            "local_name_id": name_id, "legacy_unit_id": unit_id, "legacy_mapping_id": mapping["mapping_id"],
            "name_mapping_id": mapping_id, "species_id": species_id, "context_id": context_id, "source_id": source_id,
            **evidence,
        })
    if audit_by_key:
        raise ValueError("地方名IDに結び付かなかった監査行があります。")
    return names, direct, metadata


def _convert(full: dict[str, list[dict]], audit: list[dict]) -> tuple[dict[str, list[dict]], list[dict], list[dict]]:
    normalized = {table: [] for table in TABLES}
    retained = []
    definitions = {
        "sources": (
            {"publisher": "publication", "pages": "page", "quotation": "excerpt", "verification": "verification_status"},
            ("notes",),
        ),
        "species": ({"japanese_name": "standard_name", "verification": "name_status"}, ("taxonomy_source",)),
        "contexts": ({"scope": "coverage"}, ("recording_density",)),
        "folk_units": (
            {"label": "unit_label", "hierarchy": "hierarchy_level", "growth_stage": "life_stage_size"},
            ("notes", "certainty"),
        ),
        "uses": (
            {"status": "use_status", "purpose": "purposes", "body_part": "part", "cultural_importance": "importance_notes"},
            (),
        ),
    }
    source_by_id = indexed(full["sources"], "出典", "source_id")
    for table, (renames, omitted) in definitions.items():
        for old in full[table]:
            row = _renamed(old, renames, omit=omitted)
            legacy_key = LEGACY_COLUMNS[table].split()[0]
            retained.extend(
                {"table_name": table, "record_id": old[legacy_key], "legacy_column": column, "value": old[column]}
                for column in omitted
            )
            if table == "sources":
                row["verification_status"] = _translate(old["verification"], {"未確認": "unverified"}, table)
            elif table == "species":
                row["name_status"] = _translate(old["verification"], {"未確認": "unverified"}, table)
            elif table == "contexts":
                row["context_label"] = source_by_id[old["source_id"]]["title"]
                row["notes"] = "\n".join(filter(None, (old["notes"], f"記録密度 {old['recording_density']}" if old["recording_density"] else "")))
            elif table == "folk_units":
                row["unit_status"] = _translate(old["certainty"], {"不明": "provisional"}, table)
            elif table == "uses":
                row["use_status"] = _translate(old["status"], {"利用あり": "used"}, table)
                row["purposes"] = _translate(old["purpose"], {"食用": "food"}, table)
            normalized[table].append(row)
    normalized["regions"] = full["regions"]
    for old in full["mappings"]:
        normalized["unit_species"].append({
            **old, "certainty": _translate(old["certainty"], {"暫定": "uncertain"}, "対応"),
        })
        retained.append({
            "table_name": "mappings", "record_id": old["mapping_id"], "legacy_column": "certainty",
            "value": old["certainty"],
        })
    normalized["local_names"], normalized["name_species"], crosswalk = _convert_names(full, audit)
    for table, rows in normalized.items():
        if any(set(row) != set(TABLES[table].columns) for row in rows):
            raise ValueError(f"{table} の変換結果がPhase 1のCSV契約に一致しません。")
    return normalized, crosswalk, retained


def load_recovery_inputs(path: Path) -> RecoveryInputs:
    path = Path(path)
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("復旧バンドルのサイズが上限を超えています。")
    outer, inventory = read_archive(path.read_bytes(), path.name)
    archives = {}
    inventory["nested_archives"] = {}
    for name in (INITIAL_ARCHIVE, FULL_ARCHIVE, DELTA_ARCHIVE):
        archives[name], inventory["nested_archives"][name] = read_archive(outer[name], name)
    full_archive = archives[FULL_ARCHIVE]
    full = _legacy_tables(full_archive)
    reconciled = _reconcile(_legacy_tables(archives[INITIAL_ARCHIVE]), full, archives[DELTA_ARCHIVE])
    audit = read_csv(full_archive["name_pair_audit.csv"], AUDIT_COLUMNS, "name_pair_audit.csv")
    normalized, crosswalk, retained = _convert(full, audit)

    summary = json.loads(full_archive["SUMMARY.json"].decode("utf-8-sig"))
    reviewed = "元資料掲載を確認（文字列レベル）"
    audit_status = Counter(row["this_round_source_check"] for row in audit)
    audit_reviewed = Counter(row["region"] for row in audit if row["this_round_source_check"] == reviewed)
    if set(audit_status) - {reviewed, "今回未照合"}:
        raise ValueError("行単位監査に想定外の照合状態があります。")
    group_evidence = read_csv(
        full_archive["group_level_evidence_STAGING.csv"],
        "candidate_id region taxon_label local_designation evidence_type purpose method_or_feature source_id source_location species_link_allowed reason",
        "group_level_evidence_STAGING.csv",
    )
    unresolved = read_csv(
        full_archive["staging_unresolved_group_names.csv"],
        "region local_name source_text reason source_url",
        "staging_unresolved_group_names.csv",
    )
    source_ids = {row["source_id"] for row in full["sources"]}
    source_urls = {row["doi_url"] for row in full["sources"]}
    indexed(group_evidence, "群レベルの保留資料", "candidate_id")
    if any(row["source_id"] not in source_ids for row in group_evidence) or any(
        row["source_url"] not in source_urls for row in unresolved
    ):
        raise ValueError("保留資料に全体版の出典へ結び付かない行があります。")
    expected_summary = {
        "original_name_pairs": len(normalized["local_names"]),
        "name_pairs_Hokkaido_reviewed": audit_reviewed["北海道・道北"],
        "name_pairs_Fukushima_sampled": audit_reviewed["福島県"],
        "new_species_specific_uses": len(normalized["uses"]),
        "group_level_staging": len(group_evidence),
        "source_count": len(normalized["sources"]),
    }
    if summary != expected_summary or (len(audit), len(normalized["uses"])) != (79, 2):
        raise ValueError("全体版のサマリー、監査または指定の件数が一致しません。")
    audit_files = {
        "README_RECOVERY.md": outer["README_RECOVERY.md"],
        **{name: full_archive[name] for name in (
            "RESEARCH_AUDIT.md", "SUMMARY.json", "name_pair_audit.csv", "group_level_evidence_STAGING.csv",
            "staging_unresolved_group_names.csv", "cross_region_overlap.csv",
        )},
        "legacy_name_crosswalk.csv": csv_bytes(crosswalk, list(crosswalk[0])),
        "legacy_fields.csv": csv_bytes(retained, ["table_name", "record_id", "legacy_column", "value"]),
    }
    return RecoveryInputs(
        normalized, inventory, audit_files,
        read_csv(full_archive["cross_region_overlap.csv"], COMPARE_COLUMNS, "cross_region_overlap.csv"),
        {
            "imported_archive": FULL_ARCHIVE, "archive_reconciliation": reconciled,
            "blank_fields_in_legacy_full_snapshot": {
                table: dict(Counter(field for row in rows for field, value in row.items() if value == ""))
                for table, rows in full.items()
            },
            "row_audit_status": dict(audit_status), "row_audit_reviewed_by_region": dict(audit_reviewed),
            "staging_rows_retained_outside_database": {"group_level_evidence": len(group_evidence), "unresolved_group_names": len(unresolved)},
        },
    )


def csv_bytes(rows: list[dict], columns: list[str]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")
