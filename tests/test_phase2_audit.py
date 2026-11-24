import csv
import os
import shutil
from pathlib import Path

import pytest

from ffta.apply_phase2_audit import build_validation_database
from ffta.comparison import ComparisonFilters, compare_local_names
from ffta.query import snapshot

AUDITS = Path(__file__).resolve().parents[1] / "research" / "phase2"


@pytest.fixture
def recovered_database():
    path = os.environ.get("FFTA_PHASE2_TEST_DB")
    if not path:
        pytest.skip("実データの検証には FFTA_PHASE2_TEST_DB を設定してください。")
    return Path(path)


def test_existing_database_and_non_baseline_are_rejected(tmp_path):
    candidate = tmp_path / "new.sqlite3"
    candidate.write_bytes(b"existing")
    old = tmp_path / "unrecognized.sqlite3"
    old.write_bytes(b"wrong input")
    with pytest.raises(FileExistsError):
        build_validation_database(old, AUDITS, candidate)
    assert candidate.read_bytes() == b"existing"
    next_candidate = tmp_path / "fresh.sqlite3"
    with pytest.raises(ValueError, match="SHA-256"):
        build_validation_database(old, AUDITS, next_candidate)
    assert not next_candidate.exists()


def test_phase2_copy_retains_classification_and_use_uncertainty(tmp_path, recovered_database):
    candidate = tmp_path / "ffta.sqlite3"
    original = recovered_database.read_bytes()
    summary = build_validation_database(recovered_database, AUDITS, candidate)
    assert recovered_database.read_bytes() == original
    assert summary["local_name_attestations"] == {"confirmed": 79}
    assert summary["name_agreement"] == {"confirmed": 12, "indeterminate": 2}
    assert summary["local_names_with_stage_evidence"] == 24
    base, refined = snapshot(recovered_database), snapshot(candidate)
    for table in ("folk_units", "unit_species", "uses"):
        assert refined.tables[table].equals(base.tables[table])
    ambiguous = refined.tables["species"].query("species_id in ('SP005', 'SP012')")
    assert ambiguous["name_status"].tolist() == ["unverified", "unverified"]
    assert ambiguous["scientific_name"].notna().all()
    assert set(refined.tables["name_species"]["certainty"]) == {"uncertain"}
    assert len(refined.tables["sources"]) == 8
    strict = compare_local_names(refined, ComparisonFilters(("北海道", "福島県"), ("CTX_HRO", "CTX_FUK"), True))
    assert strict["regional_comparison"].empty


def test_tampered_scope_cannot_publish_a_validation_database(tmp_path, recovered_database):
    audit_dir = tmp_path / "audits"
    shutil.copytree(AUDITS, audit_dir)
    file = audit_dir / "folk_unit_audit.csv"
    with file.open(encoding="utf-8-sig", newline="") as stream:
        entries = list(csv.DictReader(stream))
    entries[0]["context_id"] = "CTX_HOK_FOOD"
    with file.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, list(entries[0]))
        writer.writeheader()
        writer.writerows(entries)
    candidate = tmp_path / "ffta.sqlite3"
    with pytest.raises(ValueError, match="仮置き状態・文脈"):
        build_validation_database(recovered_database, audit_dir, candidate)
    assert not candidate.exists()
