# 再現性・最終検証報告

検証日　2026年11月29日（日本時間）

## 原稿と入力資料

- [完成原稿](./thesis.md) の本文は9,561字である。第1〜5章の段落から空白とMarkdownの装飾記号を除いて数えた。章節見出し、要旨、目次、図表・注・出典行、参考文献、付録は集計から外した。
- [Word](./thesis.docx) と [PDF](./thesis.pdf) はA4縦・横書きで作成した。PDFは20頁、表3点、図3点である。図はいずれも資料の関係を示す模式図であり、表3は公表された出荷数量である。[参考文献](./bibliography.md) は著者・年の引用ラベルで30項目あり、うち2項目はFFTAの研究資料である。1995年の方言集は公開抜粋ごとにa〜dを付けた。
- 入力に用いた `ffta-recovery` はコミット `ef2503ea4fdd7314b50132348dc1c69892af4b0c` である。Phase 2の監査・品質評価・分析準備判定、Phase 3の事例証拠CSV・文献調査・章草稿を照合した。履歴と参照可能な成果物で確認できた卒論草稿はPhase 3の結果・考察であり、別の初稿・改訂稿は確認できなかった。 [Phase 2](../phase2/data_quality_report.md) · [Phase 3](../phase3/case_evidence.csv)

## 数値・記載の照合

[最終証拠照合CSV](./final_evidence_check.csv) の90行には、本文の節、確認した事項、著者・年、Phase 3証拠ID、資料へのURL、頁や表位置、確認範囲を記録した。内訳は原資料の記載57行、書誌・引用30行、FFTAの監査・集計2行、解釈の範囲1行である。主要な原資料16ファイルを再取得し、Phase 3で保存したファイルとSHA-256が一致した。原資料本文のデジタルコピーは添付していない。

小名浜港の値は農林水産省の原表「表2」の `c007-05-003` と `c007-06-003` で確認した。いずれも154行目で、列D（計）、E（生鮮食用）、H（その他の食用加工品）、J（養殖用又は漁業用餌料）を照合した。表3の値はPhase 3証拠 `SAR-14`〜`SAR-21` と一致する。集計方法に前年等の構成比による補完が規定されており、小名浜港の個々の公表値への適用は判断できなかった。 [2023年原表](https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040221745&fileKind=0) · [2024年原表](https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040303754&fileKind=0) · [調査方法](https://www.maff.go.jp/j/tokei/kouhyou/suisan_ryutu/santi_ryutu/gaiyou/index.html#10)

| 原表 | 取得したXLSのSHA-256 |
| --- | --- |
| 2023年 | `7514dd307d3c21321e6937d57967c708ac6a133049d8bd7012cdd27fc090772d` |
| 2024年 | `70c65539f1f8ead7330299cbd54e808b4f2064afb6d068237988e47372a1a0cd` |

## Word・PDF・図表の再生成

本文の編集元は `thesis.md`、参考文献の編集元は `bibliography.md` である。生成時に参考文献を本文に反映し、表のCSV、模式図のPNG、Word、PDFを生成する。検証環境ではPython 3.12.14、Pandoc 3.1.11.1、LibreOfficeDev Writer 26.8.0.0.alpha0、Noto Serif CJK JPとNoto Sans CJK JPを使用した。Pandoc、LibreOfficeの `soffice` または `libreoffice`、日本語フォントを利用できる状態で、リポジトリのルートから以下を実行する。

```bash
python -m venv /tmp/ffta-thesis-venv
. /tmp/ffta-thesis-venv/bin/activate
python -m pip install python-docx==1.2.0 matplotlib==3.10.8 PyMuPDF==1.26.6
python research/final/build_thesis.py
python research/final/check_thesis.py
```

`check_thesis.py` で、参考文献30項目と本文の著者年引用、証拠ID、表のMarkdown・Word・CSV・PDF表示、図のWord内データとPDF上の配置、図表参照、目次と実頁を照合した。Wordの構造を読み取り、Writerで開いてPDFに変換し、日本語文字と図表の表示を確認した。フォントやレンダラーの差は改ページやファイルのハッシュに影響し得る。提出環境での確認項目を [提出前チェックリスト](./submission_checklist.md) に示す。

## FFTAの回帰試験とデータ保全

Python 3.11.18で46件成功（4.05秒）、Python 3.12.14で46件成功（4.24秒）。復旧用ZIPとPhase 2の適用前の研究用DBを使う試験も含め、スキップは0件だった。検索、分類対応とSankey図、地域間比較、CSV出力、インポートと入力制約、復旧時の重複検出、仮置き・未確認の維持、デモと研究データの分離を試験範囲に含めた。Phase 4の変更は `research/final/` に収まる。

Phase 2の検証用DBの別コピーでStreamlitの動作も確認した。「マイワシ」で魚種1件が返り、道北・福島の調査文脈を選ぶとSankey図が2点表示された。北海道・福島県の比較図と出力CSVで、共通の14標準和名に基づく記録数を確認した。CSVのデータ区分は全14行で `research` であり、検証に使ったコピーは操作前後で同じ内容だった。

同じ試験には、この研究の復旧用ZIPと、Phase 2を適用する前の復旧済み研究用DBが必要である。パスは手元の保管先に置き換える。試験が作成するDBはpytestの一時ディレクトリに作られる。

```bash
python -m pip install -r requirements.txt
FFTA_RECOVERY_TEST_BUNDLE=/path/to/FFTA_recovery_bundle_2026-11-23.zip \
FFTA_PHASE2_TEST_DB=/path/to/recovered/research/ffta.sqlite3 \
python -m pytest -q -ra
```

保管中の2つのSQLiteデータベースは読み取り専用で整合性を確認した。どちらも `PRAGMA integrity_check` は `ok`、`PRAGMA foreign_key_check` は0行であり、作業前後のSHA-256が一致した。

| 保管DB | SHA-256 |
| --- | --- |
| Phase 1のスキーマで復旧済みの研究用DB | `6691469c99e9b50b178d4b4c4353d691e2e88b5ae6787860a3c13753bab2a2cb` |
| Phase 2の検証用DB | `d2ef3a2b010707fdaac68e435fe5fe0aac6076e4f88977133fc0957ffa48a76e` |

## 確認済み成果物のSHA-256

| 原稿 | SHA-256 |
| --- | --- |
| `thesis.md` | `f4de58ba4b28b5ab137e49f49d00f29b86674c061d551b9fafff1ce38dc23746` |
| `thesis.docx` | `adac753c8b4166c5161d2b3bc7d21318eb6c7a72b4ce3a750967f36d0d72930d` |
| `thesis.pdf` | `cfe04221ac684310a0ef95fc257c2d80e486de4666512744007d4584f4e92721` |
