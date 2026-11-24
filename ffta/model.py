"""CSV と画面入力で共有する列定義。"""
from dataclasses import dataclass

SCHEMA_VERSION = 1
VERSION = "1.2.0"
DEMO_PREFIX = "DEMO_"

VERIFICATION = {"verified": "確認済み", "unverified": "未確認", "unknown": "出典不明"}
NAME_STATUS = {key: VERIFICATION[key] for key in ("verified", "unverified")}
UNIT_STATUS = {"documented": "区別の記載を確認済み", "provisional": "分類単位が未確定"}
FORM_TYPES = {"label": "分類単位の呼称", "synonym": "同じ分類単位の別名", "unresolved": "単位への所属が未確認"}
CERTAINTY = {"confirmed": "対応の根拠を確認済み", "probable": "推定", "uncertain": "不明"}
USE_STATUS = {"used": "利用あり", "not_used": "利用なしの記載あり", "unknown": "利用について記録なし"}
PURPOSES = {
    "food": "食用", "craft": "工芸", "tool": "道具", "medicine": "薬用",
    "ritual": "儀礼", "commercial": "商業", "other": "その他",
}
DATASETS = {"research": "研究データ", "demo": "架空デモ"}


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "text"
    required: bool = False
    choices: dict[str, str] | None = None
    reference: str | None = None
    multiline: bool = False


@dataclass(frozen=True)
class Table:
    label: str
    fields: tuple[Field, ...]

    @property
    def key(self) -> str:
        return self.fields[0].name

    @property
    def columns(self) -> list[str]:
        return [field.name for field in self.fields]


SOURCE = Field("source_id", "出典ID", "id", reference="sources")
CONTEXT = Field("context_id", "調査文脈ID", "id", True, reference="contexts")
UNIT = Field("unit_id", "民俗分類単位ID", "id", reference="folk_units")
SPECIES = Field("species_id", "魚種ID", "id", reference="species")
NOTES = Field("notes", "備考", multiline=True)

TABLES = {
    "sources": Table("出典", (
        Field("source_id", "出典ID", "id", True),
        Field("author", "著者"),
        Field("year", "発表年", "year"),
        Field("title", "文献タイトル"),
        Field("publication", "掲載誌・出版社"),
        Field("doi_url", "DOIまたはURL", "locator"),
        Field("page", "ページ・該当箇所"),
        Field("excerpt", "原文の該当箇所", multiline=True),
        Field("extracted_on", "データ抽出日", "date"),
        Field("verification_status", "出典の確認状況", required=True, choices=VERIFICATION),
    )),
    "species": Table("魚種", (
        Field("species_id", "魚種ID", "id", True),
        Field("standard_name", "標準和名"),
        Field("scientific_name", "学名"),
        Field("genus", "属"),
        Field("family", "科"),
        Field("taxonomic_order", "目"),
        SOURCE,
        Field("checked_on", "分類情報の確認日", "date"),
        Field("name_status", "和名・学名の対応", required=True, choices=NAME_STATUS),
    )),
    "regions": Table("地域", (
        Field("region_id", "地域ID", "id", True),
        Field("prefecture", "都道府県", required=True),
        Field("locality", "市町村・集落", required=True),
        Field("latitude", "緯度", "latitude"),
        Field("longitude", "経度", "longitude"),
        Field("characteristics", "地域の特徴", multiline=True),
        Field("survey_period", "地域資料の調査時期"),
        SOURCE,
    )),
    "contexts": Table("調査文脈", (
        Field("context_id", "調査文脈ID", "id", True),
        Field("region_id", "地域ID", "id", True, reference="regions"),
        Field("context_label", "調査文脈の名称", required=True),
        Field("period", "調査時期・対象時代"),
        Field("user_group", "利用者集団"),
        Field("survey_method", "調査・記録方法"),
        Field("coverage", "調査範囲", multiline=True),
        NOTES,
        SOURCE,
    )),
    "folk_units": Table("民俗分類単位", (
        Field("unit_id", "民俗分類単位ID", "id", True),
        CONTEXT,
        Field("unit_label", "民俗分類単位の表示名"),
        Field("parent_unit_id", "上位分類単位ID", "id", reference="folk_units"),
        Field("hierarchy_level", "階層の記載"),
        Field("life_stage_size", "サイズ・成長段階"),
        Field("criteria", "分類基準", multiline=True),
        Field("unit_status", "分類単位の確定度", required=True, choices=UNIT_STATUS),
        SOURCE,
    )),
    "local_names": Table("地方名", (
        Field("local_name_id", "地方名ID", "id", True),
        Field("spelling", "地方名の表記", required=True),
        Field("reading", "地方名の読み方"),
        CONTEXT,
        UNIT,
        Field("form_type", "呼称の扱い", required=True, choices=FORM_TYPES),
        Field("life_stage_size", "呼称のサイズ・成長段階"),
        NOTES,
        SOURCE,
    )),
    "unit_species": Table("民俗分類単位と魚種の対応", (
        Field("mapping_id", "分類対応ID", "id", True),
        Field("unit_id", "民俗分類単位ID", "id", True, reference="folk_units"),
        Field("species_id", "魚種ID", "id", True, reference="species"),
        Field("certainty", "対応の確実性", required=True, choices=CERTAINTY),
        SOURCE,
        NOTES,
    )),
    "name_species": Table("地方名と魚種の直接記載", (
        Field("name_mapping_id", "地方名の直接対応ID", "id", True),
        Field("local_name_id", "地方名ID", "id", True, reference="local_names"),
        Field("species_id", "魚種ID", "id", True, reference="species"),
        Field("certainty", "対応の確実性", required=True, choices=CERTAINTY),
        SOURCE,
        NOTES,
    )),
    "uses": Table("利用記録", (
        Field("use_id", "利用記録ID", "id", True),
        CONTEXT,
        SPECIES,
        UNIT,
        Field("use_status", "利用の記録状況", required=True, choices=USE_STATUS),
        Field("purposes", "利用目的", kind="purposes", choices=PURPOSES),
        Field("part", "利用部位"),
        Field("method", "利用方法", multiline=True),
        Field("frequency", "資料にある利用頻度"),
        Field("importance_notes", "文化的重要性の記述", multiline=True),
        NOTES,
        SOURCE,
    )),
}
