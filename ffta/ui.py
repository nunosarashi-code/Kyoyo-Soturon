"""日本語のStreamlit画面。"""
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

from .csv_import import import_csv
from .datasets import DEMO_CSV, TEMPLATES
from .exports import archive, result_archive
from .model import PURPOSES, TABLES, VERIFICATION, Field
from .query import Dataset, SearchFilters, classification, search
from .storage import InputError, Issue, delete_record, read_table, save_record, transaction
from .visuals import correspondence_figure

EXTRA_LABELS = {
    "related_species_ids": "該当する魚種ID",
    "relation_route": "地方名と魚種の対応経路",
    "unit_source_id": "分類単位の出典ID",
    "species_source_id": "魚種の出典ID",
    "source_verification_status": "出典の確認状況",
    "evidence_route": "魚種への対応経路",
    "evidence_id": "対応記録ID",
    "evidence_status": "集計時の根拠区分",
    "name_source_id": "地方名の出典ID",
    "name_source_status": "地方名の出典の確認状況",
    "mapping_source_id": "対応の出典ID",
    "mapping_source_status": "対応の出典の確認状況",
    "local_name_records": "地方名記録数",
    "linked_name_records": "魚種との対応あり",
    "eligible_name_records": "確認条件を満たす記録数",
}
LABELS = {field.name: field.label for spec in TABLES.values() for field in spec.fields} | EXTRA_LABELS
CHOICES = {
    field.name: field.choices
    for spec in TABLES.values()
    for field in spec.fields
    if field.choices and field.kind != "purposes"
} | {
    "source_verification_status": VERIFICATION,
    "name_source_status": VERIFICATION,
    "mapping_source_status": VERIFICATION,
    "evidence_route": {"direct": "地方名の直接記載", "unit": "民俗分類単位を介した対応"},
    "evidence_status": {"confirmed": "確認済み", "pending": "暫定"},
}
LEADING_COLUMNS = {
    "local_names": ("spelling", "reading", "prefecture", "locality", "context_label", "form_type",
                    "unit_id", "related_species_ids", "relation_route", "source_id"),
    "unit_species": ("standard_name", "scientific_name", "unit_label", "context_label", "certainty",
                     "unit_status", "name_status", "source_id", "mapping_id"),
    "name_species": ("spelling", "standard_name", "scientific_name", "context_label", "certainty", "source_id"),
    "folk_units": ("unit_label", "context_label", "hierarchy_level", "parent_unit_id",
                   "life_stage_size", "criteria", "unit_status", "source_id"),
    "uses": ("use_status", "purposes", "species_id", "unit_id", "context_label", "source_id",
             "source_verification_status"),
    "sources": ("source_id", "title", "author", "year", "page", "verification_status"),
}


def show_table(table: str, frame: pd.DataFrame, *, empty: str = "該当する記録はありません。") -> None:
    if frame.empty:
        st.info(empty)
        return
    display = frame.copy()
    for name, choices in CHOICES.items():
        if name in display:
            display[name] = display[name].map(choices)
    if "purposes" in display:
        display["purposes"] = display["purposes"].map(
            lambda value: "・".join(PURPOSES[p] for p in value.split("|") if p) or "未記録"
        )
    for column in display.columns:
        if column.endswith("source_id"):
            display[column] = display[column].fillna("出典不明")
    preferred = [c for c in LEADING_COLUMNS.get(table, ()) if c in display]
    if "year" in display:
        display["year"] = display["year"].astype("Int64")
    labels = LABELS | {field.name: field.label for field in TABLES[table].fields}
    display = display[preferred + [c for c in display if c not in preferred]].rename(columns=labels)
    st.dataframe(display, hide_index=True, width="stretch")


def _issues(issues: list[Issue]) -> None:
    st.dataframe(
        pd.DataFrame(
            [{"場所": issue.location, "行": issue.line, "列": issue.field, "確認する内容": issue.message}
             for issue in issues]
        ).astype({"行": "Int64"}),
        hide_index=True, width="stretch",
    )


def _region_labels(data: Dataset) -> dict[str, str]:
    return {
        row.region_id: f"{row.prefecture} {row.locality} [{row.region_id}]"
        for row in data.tables["regions"].itertuples(index=False)
    }


def context_labels(data: Dataset) -> dict[str, str]:
    regions = _region_labels(data)
    return {
        row.context_id: (
            f"{regions[row.region_id]} ／ {row.context_label} [{row.context_id}]"
            f" ／ {row.period or '時期未記録'} ／ {row.user_group or '集団未記録'}"
        )
        for row in data.tables["contexts"].itertuples(index=False)
    }


def show_sources(sources: pd.DataFrame, key: str) -> None:
    show_table("sources", sources, empty="出典が登録されている記録はありません。")
    if sources.empty:
        return
    choices = {row.source_id: f"{row.title or '表題未記録'} [{row.source_id}]"
               for row in sources.itertuples(index=False)}
    source_id = st.selectbox(
        "出典の詳細", list(choices), index=None, placeholder="確認する出典を選ぶ",
        format_func=choices.get, key=key,
    )
    if source_id:
        row = sources[sources["source_id"].eq(source_id)].iloc[0]
        st.text(row["excerpt"] or "原文の該当箇所は未記録です。")
        if row["doi_url"]:
            st.text(row["doi_url"])


def _download_results(
    data: Dataset, result: dict[str, pd.DataFrame], view: str, conditions: dict
) -> None:
    st.download_button(
        "結果CSV・出典・抽出条件をダウンロード",
        data=result_archive(result, dataset_kind=data.kind, view=view, conditions=conditions),
        file_name=f"ffta_{data.kind}_{view}.zip", mime="application/zip", on_click="ignore",
    )


def search_page(data: Dataset) -> None:
    st.header("検索")
    if data.kind == "research" and all(frame.empty for frame in data.tables.values()):
        st.info("研究データベースは空です。「データ管理」で登録するか、「架空デモ」で操作を試せます。")
    region_choices = _region_labels(data)
    state_key = f"search_filters_{data.kind}"
    old = st.session_state.get(state_key, SearchFilters())
    with st.form(f"search_{data.kind}"):
        fish, latin, local = st.columns(3)
        standard_name = fish.text_input("標準和名", value=old.standard_name)
        scientific_name = latin.text_input("学名", value=old.scientific_name)
        local_name = local.text_input("地方名・読み方", value=old.local_name)
        group, area, use = st.columns(3)
        taxon = group.text_input("分類群（属・科・目）", value=old.taxon)
        region_ids = area.multiselect(
            "地域", list(region_choices), default=[key for key in old.region_ids if key in region_choices],
            format_func=region_choices.get, placeholder="全地域",
        )
        purposes = use.multiselect(
            "利用目的", list(PURPOSES), default=old.purposes, format_func=PURPOSES.get, placeholder="指定なし",
        )
        st.caption("入力した項目を組み合わせて検索します。地域と利用目的は、それぞれ選んだ候補のいずれかに一致すれば対象になります。")
        submitted = st.form_submit_button("検索", type="primary")
    if submitted:
        st.session_state[state_key] = SearchFilters(
            standard_name, scientific_name, local_name, taxon, tuple(region_ids), tuple(purposes)
        )
    filters = st.session_state.get(state_key, old)
    result = search(data, filters)

    st.subheader("検索結果")
    _download_results(data, result, "search", asdict(filters))
    names, species, links, uses, sources, contexts = st.tabs([
        f"地方名（{len(result['local_names'])}）", f"魚種（{len(result['species'])}）",
        "分類対応", f"利用（{len(result['uses'])}）", "出典", "地域・調査文脈",
    ])
    with names:
        show_table("local_names", result["local_names"])
    with species:
        show_table("species", result["species"])
    with links:
        show_table("unit_species", result["unit_species"])
        st.subheader("地方名と魚種の直接記載")
        show_table("name_species", result["name_species"])
        st.subheader("民俗分類単位")
        show_table("folk_units", result["folk_units"])
    with uses:
        st.caption("利用の対象は、資料に記載された魚種または民俗分類単位です。行がない場合は未記録です。")
        show_table("uses", result["uses"], empty="選択条件に合う利用記録はありません。")
    with sources:
        show_sources(result["sources"], f"search_sources_{data.kind}")
    with contexts:
        show_table("contexts", result["contexts"])
        st.subheader("地域")
        show_table("regions", result["regions"])


def classification_page(data: Dataset) -> None:
    st.header("分類対応")
    context_choices = context_labels(data)
    if not context_choices:
        st.info("調査文脈を登録すると、分類対応を表示できます。")
        return
    selected = st.multiselect(
        "調査文脈", list(context_choices), default=list(context_choices)[:1], format_func=context_choices.get,
        key=f"graph_contexts_{data.kind}", placeholder="表示する文脈を選ぶ",
    )
    if not selected:
        st.info("調査文脈を1つ以上選んでください。")
        return
    result = classification(data, tuple(selected))
    _download_results(data, result, "classification", {"context_ids": selected})
    context_names = result["contexts"].set_index("context_id")["context_label"]
    graph, links, units, scope = st.tabs(["対応図", "対応表", "民俗分類単位・地方名", "調査文脈・出典"])
    with graph:
        st.caption(
            "左が魚種、右が民俗分類単位です。出典や別名の数にかかわらず、1組の対応を重み1の線で示します。"
            "比較する際は調査範囲、時期、利用者集団、記録方法を確認してください。"
        )
        for context_id in selected:
            figure = correspondence_figure(
                result["unit_species"], context_id=context_id, context_label=context_names[context_id], kind=data.kind,
            )
            if figure is None:
                st.text(context_choices[context_id])
                st.info("魚種と民俗分類単位の対応は未記録です。")
                continue
            st.plotly_chart(figure, width="stretch", key=f"sankey_{context_id}", config={"displaylogo": False})
            st.download_button(
                "この対応図をHTMLでダウンロード",
                data=figure.to_html(full_html=True, include_plotlyjs=True, config={"displaylogo": False}),
                file_name=f"ffta_{data.kind}_{selected.index(context_id) + 1}_sankey.html",
                mime="text/html", on_click="ignore", key=f"sankey_export_{context_id}",
            )
    with links:
        st.caption("出典ごとに1行を表示します。複数の出典から得られた対応は個別に確認できます。")
        show_table("unit_species", result["unit_species"])
    with units:
        show_table("folk_units", result["folk_units"])
        st.subheader("地方名")
        show_table("local_names", result["local_names"])
        st.subheader("地方名と魚種の直接記載")
        show_table("name_species", result["name_species"])
    with scope:
        show_table("contexts", result["contexts"])
        st.subheader("地域")
        show_table("regions", result["regions"])
        st.subheader("出典")
        show_sources(result["sources"], f"classification_sources_{data.kind}")


def _show_import_report(report) -> None:
    st.dataframe(
        pd.DataFrame([{"ファイル": name, "読み取った行数": count} for name, count in report.counts.items()]),
        hide_index=True, width="stretch",
    )
    if report.issues:
        st.error(f"{len(report.issues)} 件の確認事項があります。CSVを修正して再検証してください。")
        _issues(report.issues)
    elif report.total:
        st.success(f"{report.total} 件の入力を検証しました。")
        with st.expander("取り込む値を確認する（各ファイル先頭5行）"):
            for name, samples in report.samples.items():
                st.text(name)
                st.dataframe(pd.DataFrame(samples), hide_index=True, width="stretch")


def _import_panel(path: Path) -> None:
    st.caption("テンプレートと同じファイル名で保存し、参照関係のあるCSVをまとめて選択できます。")
    uploads = st.file_uploader("CSVファイル", type="csv", accept_multiple_files=True, key="csv_files")
    if message := st.session_state.pop("import_message", None):
        st.success(message)
    if not uploads:
        return
    files = {upload.name: upload.getvalue() for upload in uploads}
    if len(files) != len(uploads):
        st.error("同じ名前のファイルが複数あります。各テーブルにつき1つのCSVを選んでください。")
        return
    fingerprint = json.dumps({name: hashlib.sha256(body).hexdigest() for name, body in files.items()}, sort_keys=True)
    if st.button("検証する", type="primary"):
        st.session_state["import_preview"] = (fingerprint, import_csv(path, files))
        st.session_state.pop("confirm_import", None)
    previous = st.session_state.get("import_preview")
    if not previous or previous[0] != fingerprint:
        return
    report = previous[1]
    _show_import_report(report)
    if report.issues or not report.total:
        return
    confirmed = st.checkbox("検証結果を確認しました", key="confirm_import")
    if st.button("取り込む", type="primary", disabled=not confirmed):
        committed = import_csv(path, files, preview=False)
        if committed.issues:
            st.session_state["import_preview"] = (fingerprint, committed)
        else:
            del st.session_state["import_preview"]
            st.session_state["import_message"] = f"{committed.total} 件を取り込みました。"
        st.rerun()


def _reference_options(data: Dataset, table: str) -> dict[str, str]:
    frame = data.tables[table]
    key = TABLES[table].key
    display_fields = {
        "sources": ("title",),
        "species": ("standard_name", "scientific_name"),
        "regions": ("prefecture", "locality"),
        "contexts": ("context_label", "region_id"),
        "folk_units": ("unit_label", "context_id"),
        "local_names": ("spelling", "context_id"),
    }
    return {
        row[key]: f"{' ／ '.join(str(row[name]) for name in display_fields[table] if row[name])} [{row[key]}]"
        for row in frame.to_dict(orient="records")
    }


def _field_widget(place, field: Field, value, data: Dataset, *, key: str, locked: bool) -> str | None:
    label = f"{field.label}（必須）" if field.required else field.label
    if field.kind == "purposes":
        chosen = place.multiselect(
            label, list(PURPOSES), default=value.split("|") if value else [],
            format_func=PURPOSES.get, key=key, placeholder="利用目的を選ぶ",
        )
        return "|".join(chosen)
    if field.choices or field.reference:
        options = field.choices or _reference_options(data, field.reference)
        codes = list(options)
        return place.selectbox(
            label, codes, index=codes.index(value) if value in codes else None,
            format_func=options.get, key=key, placeholder="選択してください",
        )
    widget = place.text_area if field.multiline else place.text_input
    placeholder = {
        "date": "YYYY-MM-DD",
        "latitude": "十進度",
        "longitude": "十進度",
        "locator": "10.… または https://…",
    }.get(field.kind)
    return widget(
        label, value="" if value is None else str(value), key=key,
        disabled=locked, placeholder=placeholder,
    )


def _edit_panel(path: Path, data: Dataset) -> None:
    table = st.selectbox("対象テーブル", list(TABLES), format_func=lambda key: TABLES[key].label)
    spec = TABLES[table]
    if message := st.session_state.pop("record_message", None):
        st.success(message)
    with st.expander("登録状況を表示", expanded=False):
        show_table(table, data.tables[table])
    mode = st.radio("操作", ("登録", "編集", "削除"), horizontal=True)
    if table == "uses":
        st.caption("対象の魚種IDか民俗分類単位IDを一方だけ指定します。利用ありの場合は用途を選択します。")
    elif table == "local_names":
        st.caption("既存単位の別名には同じ単位IDを指定します。所属未確認の場合は単位IDを空欄にします。")
    elif table == "folk_units":
        st.caption("上位単位を登録する場合は、同じ調査文脈の単位IDを指定します。")

    revision = st.session_state.get("editor_revision", 0)
    original = {}
    if mode != "登録":
        with transaction(path) as db:
            records = read_table(db, table)
        by_id = {row[spec.key]: row for row in records}
        if not by_id:
            st.info("対象テーブルに記録がありません。")
            return
        record_id = st.selectbox("レコードID", list(by_id), key=f"record_id_{table}_{revision}")
        identity = (table, record_id, mode, revision)
        saved = st.session_state.get("editor_original")
        if not saved or saved[0] != identity:
            st.session_state["editor_original"] = (identity, by_id[record_id])
        original = st.session_state["editor_original"][1]
        if st.button("最新の値を読み直す", key=f"reload_{table}"):
            st.session_state["editor_revision"] = revision + 1
            st.rerun()
        if by_id[record_id] != original:
            st.warning("この記録は他の操作で変更されました。最新の値を読み直してください。")

    form_key = f"record_{table}_{mode}_{original.get(spec.key, '')}_{revision}"
    try:
        if mode == "削除":
            confirmed = st.checkbox(f"レコード「{original[spec.key]}」を削除する", key=form_key)
            if st.button("削除する", disabled=not confirmed, type="primary"):
                delete_record(path, table, original)
                st.session_state["record_message"] = "記録を削除しました。"
            else:
                return
        else:
            with st.form(form_key):
                raw = {}
                compact = [field for field in spec.fields if not field.multiline]
                for index in range(0, len(compact), 2):
                    spots = st.columns(2)
                    for field, spot in zip(compact[index:index + 2], spots):
                        raw[field.name] = _field_widget(
                            spot, field, original.get(field.name), data,
                            key=f"{form_key}_{field.name}", locked=mode == "編集" and field.name == spec.key,
                        )
                for field in spec.fields:
                    if field.multiline:
                        raw[field.name] = _field_widget(
                            st, field, original.get(field.name), data, key=f"{form_key}_{field.name}", locked=False,
                        )
                saved = st.form_submit_button("保存する", type="primary")
            if not saved:
                return
            save_record(path, table, raw, original=original if mode == "編集" else None)
            st.session_state["record_message"] = "記録を保存しました。"
    except InputError as exc:
        _issues(exc.issues)
        return
    st.session_state["editor_revision"] = revision + 1
    st.rerun()


def _download_inputs(*, show_demo: bool = True) -> None:
    st.caption("テンプレートは列見出し付きの空のCSVです。文字コードはUTF-8です。")
    st.download_button(
        "CSVテンプレート一式", archive({p.name: p.read_bytes() for p in sorted(TEMPLATES.glob("*.csv"))}),
        "ffta_templates.zip", "application/zip", on_click="ignore",
    )
    if show_demo:
        st.download_button(
            "架空デモCSV一式", archive({p.name: p.read_bytes() for p in sorted(DEMO_CSV.iterdir()) if p.is_file()}),
            "ffta_demo_csv.zip", "application/zip", on_click="ignore",
        )


def management_page(path: Path, data: Dataset) -> None:
    st.header("データ管理")
    if data.kind == "demo":
        st.info("架空デモは閲覧専用です。登録・編集・削除は「研究データ」で行えます。")
        _download_inputs()
        return
    csv_tab, editor, templates = st.tabs(["CSVインポート", "登録・編集・削除", "テンプレート"])
    with csv_tab:
        _import_panel(path)
    with editor:
        _edit_panel(path, data)
    with templates:
        _download_inputs()
