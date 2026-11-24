"""復旧用ZIPから、検証済みの別DB、CSV、監査、比較図を生成する。"""
import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile

from .comparison import EVIDENCE_POLICY, ComparisonFilters, compare_local_names
from .exports import csv_bytes as export_csv
from .exports import result_archive
from .model import TABLES
from .query import classification, snapshot
from .rebuild import rebuild_database
from .recovery_inputs import NAME_CONTEXTS, RecoveryInputs, csv_bytes, describe, indexed, load_recovery_inputs
from .storage import DatabaseError, InputError, parse_record, read_table, transaction
from .visuals import comparison_figure, correspondence_figure

PREFECTURES = ("北海道", "福島県")


def _write_json(path: Path, content: dict) -> None:
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _verify_db(path: Path, source_tables: dict[str, list[dict]]) -> dict:
    with transaction(path) as db:
        meta = db.execute("SELECT dataset_kind, demo_loaded FROM app_metadata").fetchone()
        if tuple(meta) != ("research", 0):
            raise ValueError("研究用DBのメタデータが正しくありません。")
        integrity = [row[0] for row in db.execute("PRAGMA integrity_check")]
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != ["ok"] or foreign_keys:
            raise ValueError("SQLiteの整合性または外部キーの検証に失敗しました。")
        for table, rows in source_tables.items():
            expected = {}
            for line, row in enumerate(rows, 2):
                parsed = parse_record(table, row, f"{table}.csv", line).values
                if table == "uses":
                    parsed["purposes"] = "|".join(parsed["purposes"])
                expected[parsed[TABLES[table].key]] = parsed
            actual = indexed(read_table(db, table), f"SQLite {table}", TABLES[table].key)
            if actual != expected or len(actual) != len(rows):
                raise ValueError(f"SQLite {table} と入力CSVのIDまたは列値が一致しません。")
    return {
        "dataset_kind": "research", "demo_loaded": 0, "integrity_check": integrity[0],
        "foreign_key_violations": len(foreign_keys), "tables_equal_to_normalized_csv": len(source_tables),
    }


def _verify_and_export_comparison(path: Path, inputs: RecoveryInputs, directory: Path) -> dict:
    data = snapshot(path)
    scopes = ComparisonFilters(PREFECTURES, NAME_CONTEXTS)
    compared = compare_local_names(data, scopes)
    summary = compared["regional_comparison"]
    actual = {
        row.standard_name: (row.record_count_left, row.record_count_right)
        for row in summary.itertuples(index=False)
    }
    reference = indexed(inputs.reference_comparison, "旧比較表", "standard_name")
    expected = {
        name: (int(row["hokkaido_name_count"]), int(row["fukushima_name_count"]))
        for name, row in reference.items()
    }
    differences = sorted(name for name in actual.keys() | expected.keys() if actual.get(name) != expected.get(name))
    if differences or len(actual) != len(summary):
        raise ValueError(f"添付の比較表と地方名記録数が一致しません（{differences}）。")
    if {row["comparable_for_granularity"] for row in reference.values()} != {"いいえ"}:
        raise ValueError("旧比較表の条件が名称記録数の探索的比較と一致しません。")
    verified = compare_local_names(data, ComparisonFilters(PREFECTURES, NAME_CONTEXTS, True))
    if not verified["regional_comparison"].empty:
        raise ValueError("確認済みの対応がない資料で確認済み比較の結果が出ました。")
    taxa = data.tables["species"]
    counts_by_prefecture = {
        PREFECTURES[0]: int(summary["record_count_left"].sum()),
        PREFECTURES[1]: int(summary["record_count_right"].sum()),
    }
    name_records = data.tables["local_names"].merge(
        data.tables["contexts"][["context_id", "region_id"]], on="context_id"
    ).merge(data.tables["regions"][["region_id", "prefecture"]], on="region_id")
    if dict(Counter(name_records["prefecture"])) != counts_by_prefecture or set(name_records["context_id"]) != set(NAME_CONTEXTS):
        raise ValueError("地方名の収録地域・文脈または件数が比較表と一致しません。")
    links = classification(data, NAME_CONTEXTS)["unit_species"]
    if set(links["certainty"]) != {"uncertain"}:
        raise ValueError("仮置き単位の種対応に根拠確認済みの区分が混入しています。")
    sankey_counts = {}
    for context_id in NAME_CONTEXTS:
        diagram = correspondence_figure(links, context_id=context_id, context_label=context_id, kind=data.kind)
        if diagram is None:
            raise ValueError(f"{context_id} のSankey図を作成できません。")
        sankey_counts[context_id] = len(diagram.data[0].link.value)

    directory.mkdir()
    conditions = {
        "prefectures": list(PREFECTURES), "context_ids": list(NAME_CONTEXTS), "confirmed_only": False,
        "counting_policy": EVIDENCE_POLICY, "role": "exploratory_documentary_counts",
    }
    (directory / "regional_comparison.csv").write_bytes(export_csv(summary, data.kind))
    (directory / "regional_comparison_evidence.zip").write_bytes(
        result_archive(compared, dataset_kind=data.kind, view="regional_comparison", conditions=conditions)
    )
    figure = comparison_figure(summary, ("北海道（道北資料）", "福島県（福島県列）"))
    figure.update_layout(
        title=(
            f"共通する{len(summary)}標準和名の地方名記録数"
            "<br><sup>調査範囲・時期・採録法の異なる2資料の記載件数</sup>"
        ),
        margin={"t": 90, "l": 25, "r": 25, "b": 65},
        font={"family": "Noto Sans JP, Hiragino Sans, Meiryo, sans-serif"},
    )
    (directory / "regional_comparison.html").write_text(
        figure.to_html(full_html=True, include_plotlyjs=True, config={"displaylogo": False}), encoding="utf-8",
    )
    return {
        "conditions": conditions,
        "common_standard_names": len(summary),
        "local_name_records_by_prefecture": counts_by_prefecture,
        "difference_count": len(differences),
        "verified_only_common_standard_names": len(verified["regional_comparison"]),
        "sankey_links": sankey_counts,
        "source_status": dict(Counter(data.tables["sources"]["verification_status"])),
        "species_name_status": dict(Counter(taxa["name_status"])),
        "scientific_names_missing": int(taxa["scientific_name"].isna().sum()),
        "unit_status": dict(Counter(data.tables["folk_units"]["unit_status"])),
        "name_form_type": dict(Counter(data.tables["local_names"]["form_type"])),
        "unit_mapping_certainty": dict(Counter(data.tables["unit_species"]["certainty"])),
        "name_mapping_certainty": dict(Counter(data.tables["name_species"]["certainty"])),
        "use_references": data.tables["uses"][
            ["use_id", "context_id", "species_id", "source_id", "use_status", "purposes"]
        ].to_dict(orient="records"),
    }


def _publish(stage: Path, destination: Path) -> None:
    destination.mkdir(mode=0o700)
    moved = []
    try:
        # 検証済みDBは最後に公開する。
        for item in sorted(stage.iterdir(), key=lambda path: path.name == "research"):
            target = destination / item.name
            item.rename(target)
            moved.append((item, target))
    except OSError:
        for item, target in reversed(moved):
            target.rename(item)
        destination.rmdir()
        raise


def recover_bundle(bundle: Path, destination: Path) -> dict:
    """元ZIPと既存DBに手を加えず、別ディレクトリへ復旧結果を出力する。"""
    bundle, destination = Path(bundle), Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"新しい出力ディレクトリを指定してください（{destination}）。")
    inputs = load_recovery_inputs(bundle)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".ffta-restore-", dir=destination.parent) as scratch:
        stage = Path(scratch)
        normalized_dir = stage / "normalized"
        normalized_dir.mkdir()
        for table, rows in inputs.normalized.items():
            (normalized_dir / f"{table}.csv").write_bytes(csv_bytes(rows, TABLES[table].columns))
        audit_dir = stage / "audit"
        audit_dir.mkdir()
        for name, payload in inputs.audit_files.items():
            (audit_dir / name).write_bytes(payload)
        _write_json(audit_dir / "input_inventory.json", inputs.inventory)
        database = stage / "research" / "ffta.sqlite3"
        build = rebuild_database(normalized_dir, database)
        db_checks = _verify_db(database, inputs.normalized)
        comparison_checks = _verify_and_export_comparison(database, inputs, stage / "comparison")
        report = {
            "bundle": {key: inputs.inventory[key] for key in ("name", "size_bytes", "sha256")},
            **inputs.checks,
            "database": {
                **build, "database": "research/ffta.sqlite3", **describe(database.read_bytes()), **db_checks,
            },
            "comparison_and_status": comparison_checks,
        }
        _write_json(audit_dir / "verification.json", report)
        _publish(stage, destination)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="FFTA_recovery_bundle_2026-11-23.zip")
    parser.add_argument("--output-dir", required=True, type=Path, help="新しい出力ディレクトリ")
    args = parser.parse_args(argv)
    try:
        report = recover_bundle(args.bundle, args.output_dir)
    except InputError as error:
        for issue in error.issues:
            print(f"{issue.location} {issue.line or ''} {issue.field} {issue.message}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, DatabaseError, BadZipFile, csv.Error, sqlite3.Error) as error:
        print(f"復旧できませんでした。{error}", file=sys.stderr)
        return 1
    print(json.dumps({
        "output_directory": str(args.output_dir),
        "rows": report["database"]["rows"],
        "common_standard_names": report["comparison_and_status"]["common_standard_names"],
        "comparison_differences": report["comparison_and_status"]["difference_count"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
