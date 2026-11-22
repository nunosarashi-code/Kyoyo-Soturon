import io
import json
import zipfile
from pathlib import Path

from streamlit.testing.v1 import AppTest

from ffta.comparison import EVIDENCE_POLICY, ComparisonFilters, compare_local_names
from ffta.exports import csv_bytes, result_archive
from ffta.query import snapshot
from ffta.rebuild import rebuild_database

DEMO_PREFECTURES = ("架空波棚県", "架空月棚県")
DEMO_CONTEXTS = ("DEMO_CA", "DEMO_CB")
TARGET_PREFECTURES = ("北海道", "福島県")
TARGET_CONTEXTS = ("TEST_H1", "TEST_H2", "TEST_F1")
APP = Path(__file__).resolve().parents[1] / "app.py"


def counts_as_dict(tables):
    summary = tables["regional_comparison"]
    return {
        r.species_id: (r.record_count_left, r.record_count_right)
        for r in summary.itertuples(index=False)
    }


def test_common_species_counts_local_name_ids_and_keeps_each_evidence(demo):
    result = compare_local_names(snapshot(demo), ComparisonFilters(DEMO_PREFECTURES, DEMO_CONTEXTS))
    assert counts_as_dict(result) == {
        "DEMO_F1": (2, 2), "DEMO_F2": (1, 1), "DEMO_F3": (1, 1),
    }
    evidence = result["comparison_evidence"]
    # 別名は別の記録になり、同じ地方名への複数根拠は集計上1件になる。
    mixed = evidence[evidence["local_name_id"].eq("DEMO_NB4")]
    assert set(mixed["evidence_id"]) == {"DEMO_M5A", "DEMO_M5B"}
    assert set(mixed["evidence_status"]) == {"confirmed", "pending"}
    assert "DEMO_SRC_B_PENDING" in result["sources"]["source_id"].tolist()


def test_confirmed_filter_keeps_verified_evidence_for_mixed_record(demo):
    result = compare_local_names(snapshot(demo), ComparisonFilters(DEMO_PREFECTURES, DEMO_CONTEXTS, True))
    assert counts_as_dict(result) == {"DEMO_F1": (2, 2), "DEMO_F2": (1, 1)}
    assert set(result["comparison_evidence"]["evidence_status"]) == {"confirmed"}
    assert "DEMO_M5B" not in result["comparison_evidence"]["evidence_id"].tolist()


def test_scope_and_direct_match_precedence(comparison_csvs, tmp_path):
    database = tmp_path / "ffta.sqlite3"
    rebuild_database(comparison_csvs, database)
    data = snapshot(database)
    result = compare_local_names(data, ComparisonFilters(TARGET_PREFECTURES, TARGET_CONTEXTS))
    assert counts_as_dict(result) == {"TEST_F1": (2, 1), "TEST_F2": (1, 1)}
    evidence = result["comparison_evidence"].set_index("local_name_id")
    assert evidence.loc["TEST_N1", "species_id"] == "TEST_F1"
    assert evidence.loc["TEST_N1", "evidence_route"] == "direct"
    assert evidence.loc["TEST_N5", "unit_status"] == "provisional"
    assert evidence.loc["TEST_N5", "evidence_status"] == "pending"
    fukushima = result["contexts"].set_index("context_id").loc["TEST_F1"]
    assert fukushima["local_name_records"] == 3
    assert fukushima["linked_name_records"] == 2
    narrow = compare_local_names(data, ComparisonFilters(TARGET_PREFECTURES, ("TEST_H1", "TEST_F1"), True))
    assert counts_as_dict(narrow) == {"TEST_F1": (1, 1)}


def test_no_common_species_and_empty_catalog(research, demo):
    assert compare_local_names(
        snapshot(research), ComparisonFilters(TARGET_PREFECTURES, ()),
    )["regional_comparison"].empty
    assert compare_local_names(
        snapshot(demo), ComparisonFilters(DEMO_PREFECTURES, ("DEMO_CA",)),
    )["regional_comparison"].empty


def test_comparison_export_has_scope_and_source_ids(demo):
    filters = ComparisonFilters(DEMO_PREFECTURES, DEMO_CONTEXTS)
    tables = compare_local_names(snapshot(demo), filters)
    csv_data = csv_bytes(tables["regional_comparison"], "demo").decode("utf-8-sig")
    assert csv_data.startswith("dataset_kind,species_id")
    assert "架空波棚県" in csv_data and "架空月棚県" in csv_data
    exported = result_archive(
        tables, dataset_kind="demo", view="regional_comparison",
        conditions={"context_ids": filters.context_ids, "counting_policy": EVIDENCE_POLICY},
    )
    with zipfile.ZipFile(io.BytesIO(exported)) as files:
        manifest = json.loads(files.read("manifest.json"))
        assert manifest["conditions"]["context_ids"] == list(DEMO_CONTEXTS)
        assert "DEMO_SRC_B_PENDING" in files.read("comparison_evidence.csv").decode("utf-8-sig")
        assert "sources.csv" in files.namelist()


def test_selects_hokkaido_and_fukushima_and_displays_chart(comparison_csvs, tmp_path, monkeypatch):
    directory = tmp_path / "app-data"
    rebuild_database(comparison_csvs, directory / "ffta.sqlite3")
    monkeypatch.setenv("FFTA_DATA_DIR", str(directory))
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    app.radio(key="page").set_value("地域間比較").run()
    assert not app.exception and not app.error
    assert app.selectbox(key="compare_left_research").value == "北海道"
    assert app.selectbox(key="compare_right_research_北海道").value == "福島県"
    assert len(app.get("plotly_chart")) == 1
    assert any("北海道の記録数" in table.value.columns for table in app.dataframe)
    app.checkbox(key="compare_verified_research").check().run()
    assert not app.exception and not app.error
    table = next(table.value for table in app.dataframe if "北海道の記録数" in table.value.columns)
    assert table["魚種ID"].tolist() == ["TEST_F1"]
