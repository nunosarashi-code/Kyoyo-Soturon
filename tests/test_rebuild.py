import hashlib

import pytest

from ffta.rebuild import rebuild_database
from ffta.storage import InputError, read_table, transaction

from conftest import csv_body


def test_builds_one_snapshot_with_provenance_and_provisional_states(comparison_csvs, tmp_path):
    output = tmp_path / "recovery-data" / "ffta.sqlite3"
    report = rebuild_database(comparison_csvs, output)
    assert report["rows"]["local_names"] == 6
    assert report["rows"]["uses"] == 2
    assert report["rows"]["use_purposes"] == 2
    assert report["input_sha256"]["local_names.csv"] == hashlib.sha256(
        (comparison_csvs / "local_names.csv").read_bytes()
    ).hexdigest()
    with transaction(output) as db:
        assert read_table(db, "folk_units")[0]["unit_status"] == "provisional"
        assert read_table(db, "uses")[0]["purposes"] == "food|other"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_existing_database_is_unchanged_on_retry(comparison_csvs, tmp_path):
    output = tmp_path / "ffta.sqlite3"
    rebuild_database(comparison_csvs, output)
    original = output.read_bytes()
    with pytest.raises(FileExistsError, match="新しい保存先"):
        rebuild_database(comparison_csvs, output)
    assert output.read_bytes() == original


def test_rejects_mixed_csv_sets(comparison_csvs, tmp_path):
    (comparison_csvs / "local_names_initial.csv").write_bytes(csv_body("local_names"))
    output = tmp_path / "ffta.sqlite3"
    with pytest.raises(ValueError, match="local_names_initial.csv"):
        rebuild_database(comparison_csvs, output)
    assert not output.exists()


@pytest.mark.parametrize("problem", ["missing_source", "duplicated_id"])
def test_invalid_snapshot_creates_no_database(comparison_csvs, tmp_path, problem):
    claim = {
        "use_id": "TEST_BAD", "context_id": "TEST_H1", "species_id": "TEST_F1",
        "use_status": "used", "purposes": "food",
    }
    rows = [{**claim, "source_id": "MISSING"}] if problem == "missing_source" else [claim, claim]
    (comparison_csvs / "uses.csv").write_bytes(csv_body("uses", *rows))
    output = tmp_path / "ffta.sqlite3"
    with pytest.raises(InputError) as error:
        rebuild_database(comparison_csvs, output)
    assert any(issue.location == "uses.csv" for issue in error.value.issues)
    assert not output.exists()
    assert not list(tmp_path.glob(".ffta-rebuild-*"))
