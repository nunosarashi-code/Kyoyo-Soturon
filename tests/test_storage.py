import sqlite3

import pytest

from ffta.csv_import import import_csv
from ffta.datasets import DEMO_CSV
from ffta.storage import DatabaseError, InputError, delete_record, initialize, read_table, save_record, transaction
from conftest import csv_body


def all_rows(path, table):
    with transaction(path) as db:
        return read_table(db, table)


def region(region_id="R1"):
    return {"region_id": region_id, "prefecture": "試験県", "locality": "試験集落"}


def sources():
    return {"source_id": "S1", "title": "検証用出典", "author": "テスト", "verification_status": "verified"}


def test_initialization_is_idempotent_and_blank(research):
    initialize(research)
    assert all_rows(research, "species") == []
    with transaction(research) as db:
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(DatabaseError, match="区分"):
        initialize(research, "demo")


def test_initialization_preserves_unrelated_database(tmp_path):
    path = tmp_path / "external.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE preserved (value TEXT)")
        db.execute("INSERT INTO preserved VALUES ('test')")
    with pytest.raises(DatabaseError, match="初期化"):
        initialize(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM preserved").fetchone() == ("test",)


def test_preview_and_atomic_import_accept_forward_references(research):
    units = [
        {"unit_id": "U1", "parent_unit_id": "U2", "context_id": "C1", "unit_status": "provisional"},
        {"unit_id": "U2", "context_id": "C1", "unit_status": "provisional"},
    ]
    files = {
        "folk_units.csv": csv_body("folk_units", *units),
        "contexts.csv": csv_body("contexts", {"context_id": "C1", "region_id": "R1", "context_label": "聞き取り"}),
        "regions.csv": csv_body("regions", region()),
    }
    preview = import_csv(research, files)
    assert preview.total == 4 and not preview.issues
    assert not all_rows(research, "regions")
    assert not import_csv(research, files, preview=False).issues
    assert [row["parent_unit_id"] for row in all_rows(research, "folk_units")] == ["U2", None]
    assert import_csv(research, files, preview=False).issues
    assert len(all_rows(research, "folk_units")) == 2


def test_invalid_values_and_foreign_keys_include_location(research):
    files = {
        "regions.csv": csv_body("regions", {**region(), "latitude": "91"}, region("R2"), region("R2")),
        "species.csv": csv_body("species", {
            "species_id": "F1", "standard_name": "テスト", "source_id": "NO_SOURCE",
            "name_status": "unverified", "checked_on": "2024-02-29",
        }),
        "sources.csv": csv_body("sources", {"source_id": "", "year": "2024.5", "extracted_on": "2023-02-29"}),
    }
    report = import_csv(research, files, preview=False)
    fields = {(issue.location, issue.line, issue.field) for issue in report.issues}
    assert ("regions.csv", 2, "latitude") in fields
    assert ("regions.csv", 4, "region_id") in fields
    assert ("species.csv", 2, "source_id") in fields
    assert ("sources.csv", 2, "extracted_on") in fields
    assert ("sources.csv", 2, "year") in fields
    assert ("sources.csv", 2, "source_id") in fields
    assert ("sources.csv", 2, "verification_status") in fields
    assert all_rows(research, "regions") == []


@pytest.mark.parametrize("data,expected", [
    (b"\xff", "UTF-8"),
    (b"region_id,region_id\n", "重複"),
    (b"region_id,wrong\n", "必要な列"),
    (b'region_id,prefecture,locality,latitude,longitude,characteristics,survey_period,source_id\nR1,"bad\n', "CSV形式"),
    (b"region_id,prefecture,locality,latitude,longitude,characteristics,survey_period,source_id\nR1,P,L\n", "列数"),
])
def test_invalid_csv_format(research, data, expected):
    assert any(expected in err.message for err in import_csv(research, {"regions.csv": data}).issues)


def test_duplicate_attestation_rolls_back_written_rows(research):
    files = {
        "sources.csv": csv_body("sources", sources()),
        "species.csv": csv_body("species", {"species_id": "F1", "standard_name": "試験魚", "name_status": "unverified"}),
        "regions.csv": csv_body("regions", region()),
        "contexts.csv": csv_body("contexts", {"context_id": "C1", "region_id": "R1", "context_label": "テスト"}),
        "folk_units.csv": csv_body("folk_units", {"unit_id": "U1", "context_id": "C1", "unit_status": "provisional"}),
        "unit_species.csv": csv_body(
            "unit_species", *[{"mapping_id": key, "unit_id": "U1", "species_id": "F1",
                             "certainty": "confirmed", "source_id": "S1"} for key in ("M1", "M2")]
        ),
    }
    report = import_csv(research, files, preview=False)
    assert any(issue.location == "unit_species.csv" and issue.line == 3 for issue in report.issues)
    assert all_rows(research, "species") == []
    assert all_rows(research, "sources") == []


def test_context_and_hierarchy_constraints(research):
    save_record(research, "regions", region())
    for key in ("C1", "C2"):
        save_record(research, "contexts", {"context_id": key, "region_id": "R1", "context_label": key})
    save_record(research, "folk_units", {"unit_id": "U1", "context_id": "C1", "unit_status": "provisional"})
    with pytest.raises(InputError, match="同じ調査文脈"):
        save_record(research, "local_names", {
            "local_name_id": "N1", "spelling": "試験名", "unit_id": "U1", "context_id": "C2", "form_type": "synonym",
        })
    report = import_csv(research, {"folk_units.csv": csv_body("folk_units", *[
        {"unit_id": key, "context_id": "C1", "unit_status": "provisional", "parent_unit_id": parent}
        for key, parent in (("U2", "U3"), ("U3", "U2"))
    ])}, preview=False)
    assert any("循環" in issue.message for issue in report.issues)
    assert len(all_rows(research, "folk_units")) == 1


def test_verified_needs_checkable_source_and_cannot_be_orphaned(research):
    raw = {"species_id": "F1", "standard_name": "試験魚", "scientific_name": "Fictopiscis test", "name_status": "verified"}
    with pytest.raises(InputError, match="確認済みの出典"):
        save_record(research, "species", raw)
    with pytest.raises(InputError, match="表題"):
        save_record(research, "sources", {"source_id": "S1", "verification_status": "verified"})
    source = {**sources(), "page": "2", "excerpt": "試験記載\n2行目の引用。"}
    assert not import_csv(research, {"sources.csv": csv_body("sources", source)}, preview=False).issues
    assert all_rows(research, "sources")[0]["excerpt"] == source["excerpt"]
    save_record(research, "species", {**raw, "source_id": "S1"})
    original = all_rows(research, "sources")[0]
    with pytest.raises(InputError, match="矛盾する参照"):
        save_record(research, "sources", {**source, "verification_status": "unknown"}, original=original)
    with pytest.raises(InputError, match="使用中"):
        delete_record(research, "sources", original)
    assert all_rows(research, "sources")[0]["verification_status"] == "verified"


def test_usage_validation_and_replacement(research):
    save_record(research, "regions", region())
    save_record(research, "contexts", {"context_id": "C1", "region_id": "R1", "context_label": "テスト"})
    save_record(research, "sources", sources())
    save_record(research, "species", {"species_id": "F1", "standard_name": "試験魚", "name_status": "unverified"})
    raw = {"use_id": "U1", "context_id": "C1", "species_id": "F1", "use_status": "used"}
    with pytest.raises(InputError, match="1つ以上"):
        save_record(research, "uses", raw)
    with pytest.raises(InputError, match="出典ID"):
        save_record(research, "uses", {**raw, "use_status": "not_used"})
    with pytest.raises(InputError, match="重複"):
        save_record(research, "uses", {**raw, "purposes": "food|food"})
    save_record(research, "uses", {**raw, "purposes": "tool|food", "source_id": "S1"})
    existing = all_rows(research, "uses")[0]
    assert existing["purposes"] == "food|tool"
    save_record(research, "uses", {**raw, "purposes": "ritual"}, original=existing)
    current = all_rows(research, "uses")[0]
    assert current["purposes"] == "ritual"
    delete_record(research, "uses", current)
    with transaction(research) as db:
        assert db.execute("SELECT COUNT(*) FROM use_purposes").fetchone()[0] == 0


def test_crud_detects_stale_edits_and_referenced_deletes(research):
    save_record(research, "regions", region())
    original = all_rows(research, "regions")[0]
    save_record(research, "regions", {**region(), "locality": "更新済み集落"}, original=original)
    with pytest.raises(InputError, match="別の操作"):
        delete_record(research, "regions", original)
    current = all_rows(research, "regions")[0]
    assert current["locality"] == "更新済み集落"
    save_record(research, "contexts", {"context_id": "C1", "region_id": "R1", "context_label": "テスト"})
    with pytest.raises(InputError, match="使用中"):
        delete_record(research, "regions", current)
    delete_record(research, "contexts", all_rows(research, "contexts")[0])
    delete_record(research, "regions", current)
    assert not all_rows(research, "regions")


def test_demo_data_stays_separate(research, demo):
    assert len(all_rows(demo, "species")) == 4
    contents = {file.name: file.read_bytes() for file in DEMO_CSV.glob("*.csv")}
    report = import_csv(research, contents, preview=False)
    assert any("架空デモ専用" in item.message for item in report.issues)
    assert all_rows(research, "regions") == []
    with pytest.raises(InputError, match="閲覧専用"):
        save_record(demo, "regions", region())
    assert not import_csv(demo, contents, preview=False, seed_demo=True).issues
    assert len(all_rows(demo, "species")) == 4


def test_shipped_templates_match_csv_contract():
    import csv

    from ffta.datasets import TEMPLATES
    from ffta.model import TABLES

    assert {file.stem for file in TEMPLATES.glob("*.csv")} == TABLES.keys()
    for key, spec in TABLES.items():
        with (TEMPLATES / f"{key}.csv").open(encoding="utf-8-sig", newline="") as reader:
            assert list(csv.reader(reader)) == [spec.columns]
