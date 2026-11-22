"""検索と分類対応表。ソースIDと実際の利用対象を結果に保持する。"""
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .model import TABLES
from .storage import read_table, transaction


@dataclass
class Dataset:
    kind: str
    tables: dict[str, pd.DataFrame]
    paths: pd.DataFrame


@dataclass(frozen=True)
class SearchFilters:
    standard_name: str = ""
    scientific_name: str = ""
    local_name: str = ""
    taxon: str = ""
    region_ids: tuple[str, ...] = ()
    purposes: tuple[str, ...] = ()


def snapshot(path: Path) -> Dataset:
    with transaction(path) as db:
        tables = {
            table: pd.DataFrame(read_table(db, table), columns=spec.columns)
            for table, spec in TABLES.items()
        }
        tables["sources"]["year"] = tables["sources"]["year"].astype("Int64")
        paths = pd.read_sql_query("SELECT * FROM search_paths", db)
        kind = db.execute("SELECT dataset_kind FROM app_metadata").fetchone()[0]
    return Dataset(kind, tables, paths)


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().strip()


def _contains(frame: pd.DataFrame, columns: tuple[str, ...], text: str) -> pd.Series:
    term = _normalize(text)
    if not term:
        return pd.Series(True, index=frame.index, dtype=bool)
    return frame.loc[:, list(columns)].apply(
        lambda column: column.map(lambda value: isinstance(value, str) and term in _normalize(value))
    ).any(axis=1)


def _key_match(frame: pd.DataFrame, values: pd.DataFrame, keys: list[str]) -> pd.Series:
    known = values.loc[:, keys].dropna().drop_duplicates()
    if known.empty:
        return pd.Series(False, index=frame.index, dtype=bool)
    found = pd.MultiIndex.from_frame(frame[keys]).isin(pd.MultiIndex.from_frame(known))
    return pd.Series(found, index=frame.index)


def _same_use_target(frame: pd.DataFrame, values: pd.DataFrame) -> pd.Series:
    return (
        _key_match(frame, values, ["context_id", "species_id"])
        | _key_match(frame, values, ["context_id", "unit_id"])
    )


def _contexts(data: Dataset, context_ids: pd.Series) -> pd.DataFrame:
    table = data.tables["contexts"]
    return table[table["context_id"].isin(context_ids)].copy()


def _add_context(data: Dataset, frame: pd.DataFrame) -> pd.DataFrame:
    contexts = data.tables["contexts"][["context_id", "region_id", "context_label", "period", "user_group"]]
    regions = data.tables["regions"][["region_id", "prefecture", "locality"]]
    return frame.merge(contexts.merge(regions, on="region_id"), on="context_id", how="left")


def _unit_links(data: Dataset) -> pd.DataFrame:
    units = data.tables["folk_units"][
        ["unit_id", "context_id", "unit_label", "unit_status", "source_id"]
    ].rename(columns={"source_id": "unit_source_id"})
    species = data.tables["species"][
        ["species_id", "standard_name", "scientific_name", "name_status", "source_id"]
    ].rename(columns={"source_id": "species_source_id"})
    links = data.tables["unit_species"].merge(units, on="unit_id").merge(species, on="species_id")
    return _add_context(data, links)


def _name_links(data: Dataset, paths: pd.DataFrame) -> pd.DataFrame:
    direct = data.tables["name_species"]
    filtered = direct[_key_match(direct, paths, ["local_name_id", "species_id"])]
    name_cols = data.tables["local_names"][["local_name_id", "spelling", "context_id"]]
    species_cols = data.tables["species"][["species_id", "standard_name", "scientific_name", "name_status"]]
    return _add_context(data, filtered.merge(name_cols, on="local_name_id").merge(species_cols, on="species_id"))


def _names(data: Dataset, paths: pd.DataFrame) -> pd.DataFrame:
    names = data.tables["local_names"]
    result = names[names["local_name_id"].isin(paths["local_name_id"])].copy()
    pairs = paths[["local_name_id", "species_id"]].dropna().drop_duplicates()
    listed = pairs.groupby("local_name_id")["species_id"].agg(lambda ids: " / ".join(sorted(ids)))
    result["related_species_ids"] = result["local_name_id"].map(listed)
    recorded_directly = result["local_name_id"].isin(data.tables["name_species"]["local_name_id"])
    result["relation_route"] = result["related_species_ids"].notna().map({
        True: "民俗分類単位を介した対応", False: "対象魚種の記録なし",
    })
    result.loc[recorded_directly & result["related_species_ids"].notna(), "relation_route"] = "地方名の直接記載"
    return _add_context(data, result)


def with_sources(data: Dataset, tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    ids = {
        source
        for frame in tables.values()
        for column in frame.columns
        if column.endswith("source_id")
        for source in frame[column].dropna()
    }
    sources = data.tables["sources"]
    statuses = sources.set_index("source_id")["verification_status"]
    return {
        **{
            table: frame.assign(source_verification_status=frame["source_id"].map(statuses).fillna("unknown"))
            if "source_id" in frame else frame
            for table, frame in tables.items()
        },
        "sources": sources[sources["source_id"].isin(ids)].copy(),
    }


def search(data: Dataset, filters: SearchFilters) -> dict[str, pd.DataFrame]:
    tables, paths = data.tables, data.paths
    species = tables["species"]
    names = tables["local_names"]
    has_species_filter = any(_normalize(term) for term in (
        filters.standard_name, filters.scientific_name, filters.taxon
    ))
    if has_species_filter:
        species_match = (
            _contains(species, ("standard_name",), filters.standard_name)
            & _contains(species, ("scientific_name",), filters.scientific_name)
            & _contains(species, ("genus", "family", "taxonomic_order"), filters.taxon)
        )
        paths = paths[paths["species_id"].isin(species.loc[species_match, "species_id"])]
    if _normalize(filters.local_name):
        name_match = _contains(names, ("spelling", "reading"), filters.local_name)
        paths = paths[paths["local_name_id"].isin(names.loc[name_match, "local_name_id"])]
    if filters.region_ids:
        contexts = tables["contexts"]
        regions_match = contexts.loc[contexts["region_id"].isin(filters.region_ids), "context_id"]
        paths = paths[paths["context_id"].isin(regions_match)]

    uses = tables["uses"]
    if filters.purposes:
        wanted = set(filters.purposes)
        uses = uses[
            uses["use_status"].eq("used")
            & uses["purposes"].map(lambda value: bool(wanted.intersection(value.split("|"))))
        ]
        paths = paths[_same_use_target(paths, uses)]

    unit_links = _unit_links(data)
    contexts = _contexts(data, paths["context_id"])
    region_ids = contexts["region_id"]
    if not (has_species_filter or _normalize(filters.local_name) or filters.purposes):
        regions = tables["regions"]
        if filters.region_ids:
            regions = regions[regions["region_id"].isin(filters.region_ids)]
        contexts = _contexts(
            data, tables["contexts"].loc[tables["contexts"]["region_id"].isin(regions["region_id"]), "context_id"]
        )
    else:
        regions = tables["regions"][tables["regions"]["region_id"].isin(region_ids)]

    return with_sources(data, {
        "local_names": _names(data, paths),
        "species": species[species["species_id"].isin(paths["species_id"])].copy(),
        "unit_species": unit_links[
            _key_match(unit_links, paths, ["context_id", "unit_id", "species_id"])
        ].copy(),
        "name_species": _name_links(data, paths),
        "folk_units": _add_context(
            data, tables["folk_units"][tables["folk_units"]["unit_id"].isin(paths["unit_id"])]
        ),
        "uses": _add_context(data, uses[_same_use_target(uses, paths)]),
        "contexts": contexts,
        "regions": regions,
    })


def classification(data: Dataset, context_ids: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    contexts = _contexts(data, pd.Series(context_ids, dtype=object))
    region_ids = contexts["region_id"]
    regions = data.tables["regions"]
    units = data.tables["folk_units"]
    links = _unit_links(data)
    paths = data.paths[data.paths["context_id"].isin(context_ids)]
    return with_sources(data, {
        "unit_species": links[links["context_id"].isin(context_ids)].copy(),
        "folk_units": _add_context(data, units[units["context_id"].isin(context_ids)]),
        "local_names": _names(data, paths),
        "name_species": _name_links(data, paths),
        "species": data.tables["species"][
            data.tables["species"]["species_id"].isin(paths["species_id"])
        ].copy(),
        "contexts": contexts,
        "regions": regions[regions["region_id"].isin(region_ids)].copy(),
    })
