"""調査文脈と出典を参照できる地域比較画面。"""
from dataclasses import asdict
from html import escape
from math import ceil

import plotly.graph_objects as go
import streamlit as st

from .comparison import EVIDENCE_POLICY, ComparisonFilters, compare_local_names
from .exports import csv_bytes, result_archive
from .model import NAME_STATUS
from .query import Dataset
from .ui import context_labels, show_sources, show_table


def _chart(summary, prefectures: tuple[str, str]) -> go.Figure:
    names = [
        f"{escape(row.standard_name or row.scientific_name or row.species_id)} [{escape(row.species_id)}]"
        for row in summary.itertuples(index=False)
    ]
    figure = go.Figure()
    for side, prefecture, color in zip(("left", "right"), prefectures, ("#246682", "#08746B"), strict=True):
        figure.add_bar(
            name=escape(prefecture), x=summary[f"record_count_{side}"], y=names, orientation="h",
            marker_color=color, hovertemplate="%{y}<br>地方名記録数 %{x}<extra>%{fullData.name}</extra>",
        )
    max_count = summary[["record_count_left", "record_count_right"]].max().max()
    figure.update_layout(barmode="group", xaxis_title="地方名記録数", height=max(350, 46 * len(summary) + 130))
    figure.update_xaxes(rangemode="tozero", dtick=max(1, ceil(max_count / 12)))
    figure.update_yaxes(autorange="reversed", automargin=True)
    return figure


def comparison_page(data: Dataset) -> None:
    st.header("地域間比較")
    st.caption("各都道府県で魚種に結び付いた地方名レコードを数え、両方に記録がある魚種を表示します。")
    prefectures = sorted(data.tables["regions"]["prefecture"].unique())
    if len(prefectures) < 2:
        st.info("比較する2都道府県と、それぞれの調査文脈を登録してください。")
        return
    columns = st.columns(2)
    first = columns[0].selectbox(
        "都道府県1", prefectures, index=prefectures.index("北海道") if "北海道" in prefectures else 0,
        key=f"compare_left_{data.kind}",
    )
    other = [prefecture for prefecture in prefectures if prefecture != first]
    second = columns[1].selectbox(
        "都道府県2", other, index=other.index("福島県") if "福島県" in other else 0,
        key=f"compare_right_{data.kind}_{first}",
    )
    labels = context_labels(data)
    regions = data.tables["regions"]
    contexts = data.tables["contexts"].merge(regions[["region_id", "prefecture"]], on="region_id")
    chosen = []
    for index, (column, prefecture) in enumerate(zip(columns, (first, second), strict=True)):
        options = contexts.loc[contexts["prefecture"].eq(prefecture), "context_id"].tolist()
        selected = column.multiselect(
            "調査文脈", options, default=options, format_func=labels.get,
            key=f"compare_contexts_{data.kind}_{index}_{prefecture}",
        )
        chosen.append(selected)
    st.caption("集計範囲は選択した調査文脈です。時期、記録方法、資料の網羅性を「調査文脈・出典」で確認できます。")
    confirmed_only = st.checkbox("出典・魚種の対応を確認済みの記録に限定する", key=f"compare_verified_{data.kind}")
    if not all(chosen):
        st.info("各都道府県で調査文脈を1件以上選択してください。")
        return
    filters = ComparisonFilters((first, second), tuple(chosen[0] + chosen[1]), confirmed_only)
    tables = compare_local_names(data, filters)
    summary = tables["regional_comparison"]
    comparison, sources = st.tabs(["地方名記録数", "調査文脈・出典"])
    with comparison:
        st.caption(
            "同じ魚種に対する同一地方名IDは、複数の根拠があっても1件です。"
            "複数の魚種に結び付く記録は各魚種に含まれます。"
            "記録数は資料に残った呼称の件数です。"
        )
        if summary.empty:
            st.info("選択した条件で両方に記録がある魚種はありません。")
        else:
            display = summary.drop(columns=["prefecture_left", "prefecture_right"]).copy()
            display["name_status"] = display["name_status"].map(NAME_STATUS)
            display = display.rename(columns={
                "species_id": "魚種ID", "standard_name": "標準和名", "scientific_name": "学名",
                "name_status": "和名・学名の対応", "record_count_left": f"{first}の記録数",
                "record_count_right": f"{second}の記録数",
            })
            st.dataframe(display, hide_index=True, width="stretch")
            st.plotly_chart(_chart(summary, filters.prefectures), width="stretch", key=f"comparison_chart_{data.kind}")
            st.download_button(
                "比較表をCSVでダウンロード", csv_bytes(summary, data.kind), "ffta_regional_comparison.csv",
                "text/csv", on_click="ignore",
            )
            with st.expander("集計に含めた地方名と対応の根拠"):
                show_table("local_names", tables["comparison_evidence"])
    with sources:
        show_table("contexts", tables["contexts"])
        show_table("regions", tables["regions"])
        show_sources(tables["sources"], f"compare_sources_{data.kind}")
    st.download_button(
        "比較表・根拠・出典・抽出条件をダウンロード",
        result_archive(
            tables, dataset_kind=data.kind, view="regional_comparison",
            conditions={**asdict(filters), "counting_policy": EVIDENCE_POLICY},
        ),
        "ffta_regional_comparison.zip", "application/zip", on_click="ignore",
    )
