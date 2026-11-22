import csv
import io

import pytest

from ffta.datasets import get_database
from ffta.model import TABLES
from ffta.storage import initialize


@pytest.fixture
def research(tmp_path):
    return initialize(tmp_path / "research.sqlite3")


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.setenv("FFTA_DATA_DIR", str(tmp_path))
    return get_database("demo")


def csv_body(table, *rows):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, TABLES[table].columns)
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8-sig")


@pytest.fixture
def comparison_csvs(tmp_path):
    """実名を含まない合成の比較用レコード。"""
    folder = tmp_path / "normalized"
    folder.mkdir()
    rows = {
        "sources": [{
            "source_id": "TEST_S", "title": "検証専用の架空資料", "author": "試験班",
            "verification_status": "verified",
        }],
        "species": [
            {"species_id": f"TEST_F{i}", "standard_name": f"架空魚{i}",
             "scientific_name": f"Fictopiscis {'prima' if i == 1 else 'secunda'}",
             "source_id": "TEST_S", "name_status": "verified"}
            for i in (1, 2)
        ],
        "regions": [
            {"region_id": "TEST_H", "prefecture": "北海道", "locality": "架空北部調査地"},
            {"region_id": "TEST_F", "prefecture": "福島県", "locality": "架空南部調査地"},
        ],
        "contexts": [
            {"context_id": key, "region_id": area, "context_label": key, "survey_method": "試験",
             "source_id": "TEST_S"}
            for key, area in (("TEST_H1", "TEST_H"), ("TEST_H2", "TEST_H"), ("TEST_F1", "TEST_F"))
        ],
        "folk_units": [{
            "unit_id": "TEST_U", "context_id": "TEST_H1", "unit_status": "provisional", "source_id": "TEST_S",
        }],
        "local_names": [
            {"local_name_id": key, "spelling": spelling, "context_id": context, "unit_id": unit,
             "form_type": "label" if unit else "unresolved", "source_id": "TEST_S"}
            for key, spelling, context, unit in (
                ("TEST_N1", "架空語A", "TEST_H1", "TEST_U"),
                ("TEST_N2", "架空語A", "TEST_H2", None),
                ("TEST_N3", "架空語B", "TEST_F1", None),
                ("TEST_N4", "架空語C", "TEST_F1", None),
                ("TEST_N5", "架空語D", "TEST_H1", "TEST_U"),
                ("TEST_N6", "架空語E", "TEST_F1", None),
            )
        ],
        "unit_species": [{
            "mapping_id": "TEST_M", "unit_id": "TEST_U", "species_id": "TEST_F2",
            "certainty": "confirmed", "source_id": "TEST_S",
        }],
        "name_species": [
            {"name_mapping_id": f"TEST_A{i}", "local_name_id": f"TEST_N{i}", "species_id": fish,
             "certainty": "confirmed", "source_id": "TEST_S"}
            for i, fish in ((1, "TEST_F1"), (2, "TEST_F1"), (3, "TEST_F1"), (6, "TEST_F2"))
        ],
        "uses": [
            {"use_id": "TEST_USE1", "context_id": "TEST_H1", "species_id": "TEST_F1",
             "use_status": "used", "purposes": "food|other", "source_id": "TEST_S"},
            {"use_id": "TEST_USE2", "context_id": "TEST_H1", "unit_id": "TEST_U", "use_status": "unknown"},
        ],
    }
    for name, values in rows.items():
        (folder / f"{name}.csv").write_bytes(csv_body(name, *values))
    return folder
