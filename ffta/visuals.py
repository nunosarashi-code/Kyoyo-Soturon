"""文脈ごとの分類単位と魚種の対応図。"""
from html import escape
from math import ceil

import pandas as pd
import plotly.graph_objects as go

from .model import CERTAINTY, DATASETS

EDGE_LABELS = {
    "checked": "確認済み",
    "mixed": "確認済みと暫定の記録が混在",
    "pending": "暫定",
}
EDGE_COLORS = {
    "checked": "rgba(0, 113, 111, 0.57)",
    "mixed": "rgba(190, 99, 12, 0.62)",
    "pending": "rgba(105, 117, 138, 0.56)",
}


def _text(value) -> str:
    return escape(str(value)) if pd.notna(value) else "未記録"


def correspondence_figure(
    evidence: pd.DataFrame, *, context_id: str, context_label: str, kind: str
) -> go.Figure | None:
    links = evidence[evidence["context_id"].eq(context_id)]
    if links.empty:
        return None

    species = links[["species_id", "standard_name", "scientific_name"]].drop_duplicates("species_id")
    units = links[["unit_id", "unit_label"]].drop_duplicates("unit_id")
    labels = []
    for row in species.itertuples(index=False):
        name = row.standard_name or row.scientific_name or row.species_id
        labels.append(f"{_text(name)} [{_text(row.species_id)}]")
    for row in units.itertuples(index=False):
        name = row.unit_label or row.unit_id
        labels.append(f"{_text(name)} [{_text(row.unit_id)}]")

    species_index = {key: i for i, key in enumerate(species["species_id"])}
    unit_index = {key: i for i, key in enumerate(units["unit_id"], start=len(species))}
    starts, ends, colors, details = [], [], [], []
    for (species_id, unit_id), claims in links.groupby(["species_id", "unit_id"], sort=True):
        checked = (
            claims["certainty"].eq("confirmed")
            & claims["unit_status"].eq("documented")
            & claims["name_status"].eq("verified")
        )
        status = "checked" if checked.all() else "mixed" if checked.any() else "pending"
        citations = [
            f"{_text(row.mapping_id)}（{CERTAINTY[row.certainty]}・出典 {_text(row.source_id)}）"
            for row in claims.itertuples(index=False)
        ]
        starts.append(species_index[species_id])
        ends.append(unit_index[unit_id])
        colors.append(EDGE_COLORS[status])
        details.append("<br>".join([EDGE_LABELS[status], *citations]))

    figure = go.Figure(go.Sankey(
        arrangement="snap",
        textfont={"color": "#182D37", "size": 13, "shadow": "none"},
        node={
            "label": labels, "pad": 22, "thickness": 16,
            "color": ["#246682"] * len(species) + ["#1e8175"] * len(units),
            "line": {"width": 0},
            "hovertemplate": "%{label}<extra></extra>",
        },
        link={
            "source": starts, "target": ends, "value": [1] * len(starts),
            "color": colors, "customdata": details,
            "hovertemplate": "%{source.label} → %{target.label}<br>%{customdata}<extra></extra>",
        },
    ))
    figure.update_layout(
        title={
            "text": f"{DATASETS[kind]}  ·  {_text(context_label)} [{_text(context_id)}]"
                    "<br><sup>魚種 → 民俗分類単位</sup>"
                    "<br><sup>青緑 確認済み　橙 混在　灰 暫定</sup>",
            "x": 0.02,
        },
        height=max(360, 46 * max(len(species), len(units)) + 116),
        font={"size": 13, "color": "#182D37", "family": "Noto Sans JP, Hiragino Sans, Meiryo, sans-serif"},
        margin={"l": 16, "r": 16, "t": 98, "b": 24},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
    )
    return figure


def comparison_figure(summary: pd.DataFrame, prefectures: tuple[str, str]) -> go.Figure:
    names = [
        f"{_text(row.standard_name or row.scientific_name or row.species_id)} [{_text(row.species_id)}]"
        for row in summary.itertuples(index=False)
    ]
    figure = go.Figure()
    for side, prefecture, color in zip(("left", "right"), prefectures, ("#246682", "#08746B"), strict=True):
        figure.add_bar(
            name=_text(prefecture), x=summary[f"record_count_{side}"], y=names, orientation="h",
            marker_color=color, hovertemplate="%{y}<br>地方名記録数 %{x}<extra>%{fullData.name}</extra>",
        )
    max_count = summary[["record_count_left", "record_count_right"]].max().max() if len(summary) else 0
    figure.update_layout(barmode="group", xaxis_title="地方名記録数", height=max(350, 46 * len(summary) + 130))
    figure.update_xaxes(rangemode="tozero", dtick=max(1, ceil(max_count / 12)))
    figure.update_yaxes(autorange="reversed", automargin=True)
    return figure
