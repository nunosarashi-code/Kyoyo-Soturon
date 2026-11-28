import hashlib
import io
import json
import zipfile

from ffta.exports import result_archive
from ffta.query import SearchFilters, classification, search, snapshot
from ffta.visuals import EDGE_COLORS, correspondence_figure


def test_empty_catalog_search_has_all_result_tables(research):
    found = search(snapshot(research), SearchFilters(standard_name="検索語", purposes=("craft",)))
    assert all(frame.empty for frame in found.values())


def test_alias_search_keeps_one_unit_and_cites_sources(demo):
    data = snapshot(demo)
    found = search(data, SearchFilters(local_name="ｼｵﾐｵ", scientific_name="FICTOPISCIS EXEMPLARIS"))
    assert list(found["local_names"]["local_name_id"]) == ["DEMO_NA1_ALT"]
    assert list(found["local_names"]["form_type"]) == ["synonym"]
    assert list(found["local_names"]["related_species_ids"]) == ["DEMO_F1"]
    assert list(found["unit_species"]["unit_id"]) == ["DEMO_UA1"]
    assert {"DEMO_SRC_A", "DEMO_SRC_TAX"}.issubset(found["sources"]["source_id"])


def test_name_can_be_associated_with_multiple_species(demo):
    data = snapshot(demo)
    aggregate = search(data, SearchFilters(local_name="なぎまと"))
    assert set(aggregate["species"]["species_id"]) == {"DEMO_F2", "DEMO_F3"}
    assert set(aggregate["unit_species"]["unit_id"]) == {"DEMO_UA2"}
    unresolved = search(data, SearchFilters(local_name="かりとう"))
    assert set(unresolved["species"]["species_id"]) == {"DEMO_F3", "DEMO_F4"}
    assert len(unresolved["name_species"]) == 2
    assert unresolved["unit_species"].empty and unresolved["folk_units"].empty


def test_search_combines_filters_and_preserves_usage_target(demo):
    data = snapshot(demo)
    found = search(data, SearchFilters(
        standard_name="ミオソラ", region_ids=("DEMO_RB",), purposes=("craft",),
        taxon="fictopiscidae",
    ))
    assert list(found["unit_species"]["unit_id"]) == ["DEMO_UB2"]
    assert list(found["uses"]["use_id"]) == ["DEMO_USE_4"]
    assert found["uses"].iloc[0]["species_id"] is None
    assert found["uses"].iloc[0]["unit_id"] == "DEMO_UB2"
    inapplicable = search(data, SearchFilters(local_name="こつき", purposes=("craft",)))
    assert inapplicable["uses"].empty and inapplicable["species"].empty


def test_explicit_non_use_and_unknown_are_excluded_from_purpose_search(demo):
    data = snapshot(demo)
    a = search(data, SearchFilters(region_ids=("DEMO_RA",)))
    b = search(data, SearchFilters(region_ids=("DEMO_RB",)))
    assert "not_used" in set(a["uses"]["use_status"])
    assert "unknown" in set(b["uses"]["use_status"])
    craft = search(data, SearchFilters(region_ids=("DEMO_RA",), purposes=("craft",)))
    assert craft["uses"].empty and craft["species"].empty


def test_contextual_visualization_collapses_aliases_and_citations(demo):
    data = snapshot(demo)
    mapping = classification(data, ("DEMO_CA", "DEMO_CB"))
    assert len(mapping["unit_species"]) == 8
    left = correspondence_figure(mapping["unit_species"], context_id="DEMO_CA", context_label="架空A", kind=data.kind)
    right = correspondence_figure(mapping["unit_species"], context_id="DEMO_CB", context_label="架空B", kind=data.kind)
    assert len(left.data[0].link.value) == 3
    assert len(right.data[0].link.value) == 4
    assert all(value == 1 for value in right.data[0].link.value)
    assert set(right.data[0].link.color) == set(EDGE_COLORS.values())
    assert sum(source == 0 for source in right.data[0].link.source) == 2
    assert "架空デモ" in right.layout.title.text
    tooltip = " ".join(right.data[0].link.customdata)
    assert "DEMO_M5A" in tooltip and "DEMO_M5B" in tooltip
    assert "DEMO_NM1" not in tooltip


def test_exports_include_data_scope_and_source_trace(demo):
    data = snapshot(demo)
    tables = classification(data, ("DEMO_CA",))
    content = result_archive(
        tables, dataset_kind="demo", view="classification", conditions={"context_ids": ["DEMO_CA"]},
    )
    with zipfile.ZipFile(io.BytesIO(content)) as files:
        manifest = json.loads(files.read("manifest.json"))
        assert manifest["dataset_kind"] == "demo"
        assert manifest["conditions"] == {"context_ids": ["DEMO_CA"]}
        csv = files.read("unit_species.csv")
        assert csv.decode("utf-8-sig").startswith("dataset_kind,mapping_id")
        assert "DEMO_SRC_A" in csv.decode("utf-8-sig")
        assert manifest["files"]["unit_species.csv"]["sha256"] == hashlib.sha256(csv).hexdigest()
        assert "sources.csv" in files.namelist()


def test_same_spelling_keeps_contexts_and_direct_evidence_distinct(research):
    from ffta.storage import save_record

    save_record(research, "regions", {"region_id": "R", "prefecture": "試験県", "locality": "試験集落"})
    for key, name in (("F1", "試験種A"), ("F2", "試験種B")):
        save_record(research, "species", {"species_id": key, "standard_name": name, "name_status": "unverified"})
    for context_id, group, unit_id, name_id, species_id in (
        ("C1", "漁業者", "U1", "N1", "F1"),
        ("C2", "加工者", "U2", "N2", "F2"),
    ):
        save_record(research, "contexts", {
            "context_id": context_id, "region_id": "R", "context_label": group, "user_group": group,
        })
        save_record(research, "folk_units", {
            "unit_id": unit_id, "context_id": context_id, "unit_status": "provisional",
        })
        save_record(research, "local_names", {
            "local_name_id": name_id, "spelling": "試験名", "context_id": context_id,
            "unit_id": unit_id, "form_type": "label",
        })
        save_record(research, "unit_species", {
            "mapping_id": f"M_{unit_id}", "unit_id": unit_id, "species_id": species_id, "certainty": "uncertain",
        })
    save_record(research, "name_species", {
        "name_mapping_id": "NM1", "local_name_id": "N1", "species_id": "F2", "certainty": "probable",
    })
    data = snapshot(research)
    found = search(data, SearchFilters(local_name="試験名"))
    assert set(found["local_names"]["context_id"]) == {"C1", "C2"}
    assert set(found["species"]["species_id"]) == {"F2"}
    assert list(found["unit_species"]["unit_id"]) == ["U2"]
    assert found["unit_species"].iloc[0]["source_verification_status"] == "unknown"
    assert list(found["name_species"]["name_mapping_id"]) == ["NM1"]
    assert set(classification(data, ("C1",))["unit_species"]["species_id"]) == {"F1"}
