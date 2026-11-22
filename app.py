"""streamlit run app.py で起動する。"""
import sqlite3

import streamlit as st

from ffta.comparison_ui import comparison_page
from ffta.datasets import get_database
from ffta.model import DATASETS, VERSION
from ffta.query import snapshot
from ffta.storage import DatabaseError
from ffta.ui import classification_page, management_page, search_page


def main() -> None:
    st.set_page_config(page_title="Fish Folk Taxonomy Analyzer", page_icon="🐟", layout="wide")
    st.sidebar.title("FFTA")
    kind = st.sidebar.radio("データ区分", list(DATASETS), format_func=DATASETS.get, key="dataset")
    page = st.sidebar.radio("画面", ("検索", "分類対応", "地域間比較", "データ管理"), key="page")
    st.sidebar.caption(f"FFTA v{VERSION}")

    st.title("Fish Folk Taxonomy Analyzer")
    if kind == "demo":
        st.warning("架空デモ。魚種・地名・地方名・利用記録・文献はすべて動作確認用です。")
    try:
        path = get_database(kind)
        data = snapshot(path)
        if page == "検索":
            search_page(data)
        elif page == "分類対応":
            classification_page(data)
        elif page == "地域間比較":
            comparison_page(data)
        else:
            management_page(path, data)
    except (DatabaseError, sqlite3.Error, OSError) as error:
        st.error(f"ローカルデータを処理できませんでした。{error}")


if __name__ == "__main__":
    main()
