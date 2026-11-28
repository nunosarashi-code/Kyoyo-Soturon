"""2地域に共通する魚種の地方名レコード数を集計する。"""
from dataclasses import dataclass

import pandas as pd

from .query import Dataset, with_sources

SUMMARY_COLUMNS = (
    "species_id", "standard_name", "scientific_name", "name_status",
    "prefecture_left", "record_count_left", "prefecture_right", "record_count_right",
)
EVIDENCE_COLUMNS = (
    "prefecture", "region_id", "context_id", "species_id", "standard_name", "scientific_name",
    "local_name_id", "spelling", "reading", "form_type", "unit_id", "unit_status",
    "evidence_route", "evidence_id", "certainty", "evidence_status", "name_status",
    "name_source_id", "name_source_status", "mapping_source_id", "mapping_source_status",
    "unit_source_id", "species_source_id",
)
EVIDENCE_POLICY = "distinct_local_name_ids_per_species_and_prefecture_v1"


@dataclass(frozen=True)
class ComparisonFilters:
    prefectures: tuple[str, str]
    context_ids: tuple[str, ...]
    confirmed_only: bool = False


def _record_evidence(data: Dataset, names: pd.DataFrame) -> pd.DataFrame:
    tables = data.tables
    name_columns = ["local_name_id", "species_id", "unit_id"]
    # 既存の検索経路を利用し、地方名の直接記載を優先する規則を共有する。
    pairs = data.paths.loc[
        data.paths["local_name_id"].isin(names["local_name_id"]) & data.paths["species_id"].notna(),
        name_columns,
    ]
    direct = tables["name_species"].rename(columns={
        "name_mapping_id": "evidence_id", "source_id": "mapping_source_id",
    })
    evidence_cols = ["evidence_id", "certainty", "mapping_source_id"]
    matched = pairs.merge(
        direct[["local_name_id", "species_id", *evidence_cols]],
        on=["local_name_id", "species_id"], how="left",
    )
    explicit = matched[matched["evidence_id"].notna()].assign(evidence_route="direct")
    unit_mappings = tables["unit_species"].rename(columns={
        "mapping_id": "evidence_id", "source_id": "mapping_source_id",
    })
    via_unit = matched.loc[matched["evidence_id"].isna(), name_columns].merge(
        unit_mappings[["unit_id", "species_id", *evidence_cols]],
        on=["unit_id", "species_id"], how="inner",
    ).assign(evidence_route="unit")
    links = pd.concat([explicit, via_unit], ignore_index=True)
    names = names[
        ["local_name_id", "spelling", "reading", "context_id", "prefecture", "region_id", "form_type", "source_id"]
    ].rename(columns={"source_id": "name_source_id"})
    species = tables["species"][
        ["species_id", "standard_name", "scientific_name", "name_status", "source_id"]
    ].rename(columns={"source_id": "species_source_id"})
    units = tables["folk_units"][["unit_id", "unit_status", "source_id"]].rename(columns={"source_id": "unit_source_id"})
    evidence = links.merge(names, on="local_name_id").merge(species, on="species_id").merge(units, on="unit_id", how="left")
    source_status = tables["sources"].set_index("source_id")["verification_status"]
    for key in ("name", "mapping"):
        evidence[f"{key}_source_status"] = evidence[f"{key}_source_id"].map(source_status).fillna("unknown")
    checked = (
        evidence["certainty"].eq("confirmed")
        & evidence["name_status"].eq("verified")
        & evidence["name_source_status"].eq("verified")
        & evidence["mapping_source_status"].eq("verified")
        & (evidence["evidence_route"].eq("direct") | evidence["unit_status"].eq("documented"))
    )
    evidence["evidence_status"] = checked.map({True: "confirmed", False: "pending"})
    return evidence[list(EVIDENCE_COLUMNS)]


def _comparison_summary(evidence: pd.DataFrame, prefectures: tuple[str, str]) -> pd.DataFrame:
    counts = (
        evidence.groupby(["species_id", "prefecture"])["local_name_id"].nunique()
        .rename("name_count").reset_index()
    )
    sides = []
    for prefecture, side in zip(prefectures, ("left", "right"), strict=True):
        subset = counts.loc[counts["prefecture"].eq(prefecture), ["species_id", "prefecture", "name_count"]]
        sides.append(subset.rename(columns={"prefecture": f"prefecture_{side}", "name_count": f"record_count_{side}"}))
    fish = evidence[["species_id", "standard_name", "scientific_name", "name_status"]].drop_duplicates("species_id")
    summary = sides[0].merge(sides[1], on="species_id").merge(fish, on="species_id")
    return summary[list(SUMMARY_COLUMNS)].sort_values(["standard_name", "species_id"]).reset_index(drop=True)


def compare_local_names(data: Dataset, filters: ComparisonFilters) -> dict[str, pd.DataFrame]:
    if len(filters.prefectures) != 2 or len(set(filters.prefectures)) != 2:
        raise ValueError("異なる2都道府県を指定してください。")
    tables = data.tables
    contexts = tables["contexts"]
    regions = tables["regions"]
    places = regions[regions["prefecture"].isin(filters.prefectures)]
    scope = contexts[contexts["context_id"].isin(filters.context_ids)].merge(
        places[["region_id", "prefecture"]], on="region_id",
    )
    names = tables["local_names"].merge(
        scope[["context_id", "region_id", "prefecture"]], on="context_id",
    )
    evidence = _record_evidence(data, names)
    included = evidence[evidence["evidence_status"].eq("confirmed")] if filters.confirmed_only else evidence
    summary = _comparison_summary(included, filters.prefectures)
    common = included[included["species_id"].isin(summary["species_id"])].sort_values(
        ["prefecture", "species_id", "context_id", "local_name_id", "evidence_id"],
    )
    for column, frame in (
        ("local_name_records", names),
        ("linked_name_records", evidence),
        ("eligible_name_records", included),
    ):
        counts = frame.groupby("context_id")["local_name_id"].nunique()
        scope[column] = scope["context_id"].map(counts).fillna(0).astype(int)
    return with_sources(data, {
        "regional_comparison": summary,
        "comparison_evidence": common,
        "contexts": scope,
        "regions": places[places["region_id"].isin(scope["region_id"])],
    })
