from pathlib import Path

from streamlit.testing.v1 import AppTest

from ffta.datasets import get_database
from ffta.storage import read_table, transaction

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_demo_search_and_classification(tmp_path, monkeypatch):
    monkeypatch.setenv("FFTA_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    assert not app.exception and not app.error
    assert any("空です" in info.value for info in app.info)
    app.radio(key="dataset").set_value("demo").run()
    assert not app.exception and not app.error
    assert any("架空デモ" in notice.value for notice in app.warning)
    next(box for box in app.text_input if box.label == "地方名・読み方").set_value("シオミオ")
    next(button for button in app.button if button.label == "検索").click().run()
    assert not app.exception and not app.error
    assert any("シオミオ" in df.value.to_string() for df in app.dataframe)
    app.radio(key="page").set_value("分類対応").run()
    assert not app.exception and not app.error
    assert len(app.get("plotly_chart")) == 1
    app.multiselect(key="graph_contexts_demo").set_value(["DEMO_CA", "DEMO_CB"]).run()
    assert not app.exception and not app.error
    assert len(app.get("plotly_chart")) == 2


def test_register_edit_delete_source_from_management(tmp_path, monkeypatch):
    monkeypatch.setenv("FFTA_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    app.radio(key="page").set_value("データ管理").run()
    by_label = lambda elements, label: next(element for element in elements if element.label == label)
    by_label(app.text_input, "出典ID（必須）").set_value("TEST_CITATION")
    by_label(app.selectbox, "出典の確認状況（必須）").set_value("unverified")
    by_label(app.button, "保存する").click().run()
    assert not app.exception and not app.error
    assert any("保存しました" in message.value for message in app.success)

    by_label(app.radio, "操作").set_value("編集").run()
    by_label(app.text_input, "著者").set_value("試験著者")
    by_label(app.button, "保存する").click().run()
    assert not app.exception and not app.error
    with transaction(get_database("research")) as db:
        assert read_table(db, "sources")[0]["author"] == "試験著者"

    by_label(app.radio, "操作").set_value("削除").run()
    app.checkbox[0].check().run()
    by_label(app.button, "削除する").click().run()
    assert not app.exception and not app.error
    with transaction(get_database("research")) as db:
        assert read_table(db, "sources") == []
