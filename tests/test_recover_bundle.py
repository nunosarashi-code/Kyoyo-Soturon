import csv
import io
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from streamlit.testing.v1 import AppTest

from ffta.comparison import ComparisonFilters, compare_local_names
from ffta.query import SearchFilters, search, snapshot
from ffta.recover_bundle import recover_bundle
from ffta.recovery_inputs import AUDIT_COLUMNS, FULL_ARCHIVE, csv_bytes, read_archive, read_csv
from ffta.storage import transaction

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(scope="module")
def research_bundle():
    path = os.environ.get("FFTA_RECOVERY_TEST_BUNDLE")
    if not path:
        pytest.skip("実データの検証には FFTA_RECOVERY_TEST_BUNDLE を設定してください。")
    return Path(path)


@pytest.fixture(scope="module")
def recovered(tmp_path_factory, research_bundle):
    directory = tmp_path_factory.mktemp("restoration") / "recovered"
    return directory, recover_bundle(research_bundle, directory)


def test_zip_with_duplicate_member_is_rejected():
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("test.txt", "first")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("test.txt", "second")
    with pytest.raises(ValueError, match="同名"):
        read_archive(buffer.getvalue(), "test.zip")


def test_recovery_retains_existing_directory(tmp_path):
    directory = tmp_path / "already-present"
    directory.mkdir()
    marker = directory / "marker"
    marker.write_bytes(b"existing")
    with pytest.raises(FileExistsError, match="新しい出力ディレクトリ"):
        recover_bundle(tmp_path / "missing.zip", directory)
    assert marker.read_bytes() == b"existing"


def test_imported_legacy_rows_and_review_states(recovered):
    directory, report = recovered
    assert report["database"]["rows"] == {
        "sources": 7, "species": 14, "regions": 4, "contexts": 4, "folk_units": 28, "local_names": 79,
        "unit_species": 28, "name_species": 79, "uses": 2, "use_purposes": 2,
    }
    assert report["database"]["foreign_key_violations"] == 0
    with transaction(directory / "research" / "ffta.sqlite3") as db:
        assert db.execute("SELECT dataset_kind FROM app_metadata").fetchone()[0] == "research"
        assert db.execute("SELECT COUNT(*) FROM sources WHERE verification_status = 'unverified'").fetchone()[0] == 7
        assert db.execute("SELECT COUNT(*) FROM folk_units WHERE unit_status = 'provisional'").fetchone()[0] == 28
        assert db.execute("SELECT COUNT(*) FROM local_names WHERE unit_id IS NULL AND form_type = 'unresolved'").fetchone()[0] == 79
    assert report["row_audit_status"] == {"元資料掲載を確認（文字列レベル）": 45, "今回未照合": 34}
    assert not (directory / "research" / "ffta_demo.sqlite3").exists()
    assert len(list((directory / "normalized").glob("*.csv"))) == 9


def test_reference_comparison_and_uses_keep_contexts_separate(recovered):
    directory, report = recovered
    data = snapshot(directory / "research" / "ffta.sqlite3")
    expected = report["comparison_and_status"]
    assert expected["common_standard_names"] == 14
    assert expected["local_name_records_by_prefecture"] == {"北海道": 18, "福島県": 61}
    assert expected["difference_count"] == 0
    assert expected["sankey_links"] == {"CTX_HRO": 14, "CTX_FUK": 14}
    checked = compare_local_names(data, ComparisonFilters(("北海道", "福島県"), ("CTX_HRO", "CTX_FUK"), True))
    assert checked["regional_comparison"].empty
    fukushima = search(data, SearchFilters(region_ids=("REG_FUK",), purposes=("food",)))
    assert fukushima["uses"].empty
    food = search(data, SearchFilters(purposes=("food",)))
    assert set(zip(food["uses"]["use_id"], food["uses"]["context_id"])) == {
        ("USE_E001", "CTX_HOK_FOOD"), ("USE_E002", "CTX_TOCH_FOOD"),
    }
    with (directory / "comparison" / "regional_comparison.csv").open(encoding="utf-8-sig", newline="") as csv_file:
        assert len(list(csv.DictReader(csv_file))) == 14


def test_recovered_app_defaults_to_name_contexts_and_switches_demo(recovered, tmp_path, monkeypatch):
    directory, _ = recovered
    deployed = tmp_path / "ffta.sqlite3"
    deployed.write_bytes((directory / "research" / "ffta.sqlite3").read_bytes())
    original = deployed.read_bytes()
    monkeypatch.setenv("FFTA_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception and not app.error
    app.radio(key="page").set_value("地域間比較").run()
    assert not app.exception and not app.error
    assert len(app.get("plotly_chart")) == 1
    assert app.multiselect(key="compare_contexts_research_0_北海道").value == ["CTX_HRO"]
    assert app.multiselect(key="compare_contexts_research_1_福島県").value == ["CTX_FUK"]
    app.radio(key="dataset").set_value("demo").run()
    assert not app.exception and not app.error
    assert (tmp_path / "ffta_demo.sqlite3").exists()
    assert deployed.read_bytes() == original


def _replace_member(blob, name, change):
    buffer = io.BytesIO()
    with ZipFile(io.BytesIO(blob)) as source, ZipFile(buffer, "w", compression=ZIP_DEFLATED) as output:
        for filename in source.namelist():
            content = source.read(filename)
            output.writestr(filename, change(content) if filename == name else content)
    return buffer.getvalue()


def test_missing_row_audit_stops_publication(research_bundle, tmp_path):
    def remove_audit_row(payload):
        rows = read_csv(payload, AUDIT_COLUMNS, "name_pair_audit.csv")
        return csv_bytes(rows[1:], AUDIT_COLUMNS.split())

    def change_full_archive(payload):
        return _replace_member(payload, "name_pair_audit.csv", remove_audit_row)

    tampered = tmp_path / "incomplete.zip"
    tampered.write_bytes(_replace_member(research_bundle.read_bytes(), FULL_ARCHIVE, change_full_archive))
    destination = tmp_path / "recovered"
    with pytest.raises(ValueError, match="対応する行単位監査がありません"):
        recover_bundle(tampered, destination)
    assert not destination.exists()
