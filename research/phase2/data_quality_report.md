# FFTA Phase 2 データ品質評価

確認日　2026年11月25日（日本時間）

対象は `ffta-recovery` の復旧版 `c52a0fb` と2026年11月24日の研究用DBです。福島県の公開抜粋、稚内水試の掲載表、分類資料を直接参照しました。

| 監査対象 | 確認済み | 未確認・部分確認 | 判断不能・見解差 |
| --- | ---: | ---: | ---: |
| 福島県の前回未照合行 | 34 | 0 | 0 |
| 資料に地方名が掲載されること（福島61、道北18） | 79 | 0 | 0 |
| 現行標準和名と学名の二資料間の一致 | 12 | 0 | 2 |
| 各地方名行の指示対象を現行分類で再同定 | 0 | 79 | 0 |
| 既存の仮置き民俗分類単位の確定 | 0 | 0 | 28 |
| 既存出典の書誌同定と日付情報 | 5 | 2（部分確認） | 0 |

## 名称の原資料照合

福島県の61行について、元データに記載されたPDF頁、標準和名の行、福島県列の表記と地域注記が一致しました。列位置を分けて確認し、アブラツノザメのp.1からp.2への続きも追跡しました。道北の18行は稚内水試のHTML表で地方名本体と標準和名の対応を照合しました。各行の既存ID、頁またはHTML表の行、該当箇所、判定理由と取得原資料のSHA-256を `source_audit.csv` に記録しました。 [福島の公開抜粋](https://www.pref.fukushima.lg.jp/uploaded/attachment/36932.pdf) · [道北の魚類編](https://www.hro.or.jp/fisheries/research/wakkanai/surveys-knowledge-of-fish/inpvt400000007sg/inpvt40000000l0z.html)

福島の照合対象は公開抜粋です。冊子は1995年2月刊・103頁と確認し、個別の採録年月と抜粋外の頁は未確認です。FUKのヒラメ行には復旧データの5呼称に加え「バラ」も掲載されています。件数は復旧済みの79行を対象に集計しました。 [県の資料案内](https://www.pref.fukushima.lg.jp/sec/37380b/hougen.html) · [国立国会図書館書誌](https://ndlsearch.ndl.go.jp/books/R100000002-I000002422598) · [福島の公開抜粋p.12](https://www.pref.fukushima.lg.jp/uploaded/attachment/36932.pdf#page=12)

## 学名と分類の見解差

本村浩之『日本産魚類全種目録』Online ver.43（2026年10月25日）のシートで14標準和名の対応を取得し、WoRMSと照合しました。12件の学名表記が一致しました。ウミタナゴはJAFの `Ditrema temminckii temminckii` とWoRMSの `Ditrema temminckii`、マイワシはJAFの `Sardinops melanostictus` とWoRMSの `Sardinops sagax` を併記し、検証DBではJAF掲載名を入れたうえで両者の確認状態を未確認としました。科や目の違いも監査CSVに保持しています。 [JAFの版と推奨引用](https://www.museum.kagoshima-u.ac.jp/staff/motomura/jaf.html) · [WoRMS ウミタナゴ](https://www.marinespecies.org/aphia.php?p=taxdetails&id=712926) · [WoRMS マイワシ](https://www.marinespecies.org/aphia.php?p=taxdetails&id=309913)

`scientific_name_audit.csv` には1995年福島の分類表、JAF ver.1（2020年）とver.43、WoRMSの名前・階級・各該当箇所を保持しました。福島旧表のイカナゴは `Ammodytes personatus`、クロマグロは `Thunnus thynnus`、イシガレイは `Kareius bicoloratus` でした。アブラツノザメは福島旧表およびJAF ver.1の `Squalus acanthias` から現行JAFの `Squalus suckleyi` へ扱いが変わっています。地方名資料の個体を新しい種概念で再同定した記録はありません。 [福島旧分類表](https://www.pref.fukushima.lg.jp/uploaded/attachment/36933.pdf) · [イカナゴ属の改訂](https://spo.nmfs.noaa.gov/sites/default/files/orr.pdf) · [アブラツノザメの再記載](https://doi.org/10.11646/zootaxa.2612.1.2)

## 民俗分類の根拠

| 仮置きグループ内の資料上のパターン | グループ数 |
| --- | ---: |
| 成長段階・大きさの明記 | 9 |
| 同一標準和名への複数呼称の掲載 | 7 |
| 単一呼称の掲載 | 12 |

24の地方名レコード（道北4、福島20）に大きさ・成長段階の根拠を確認しました。福島の資料集の大きさ別表では、マイワシの体長帯やブリの名称別の全長を確認しました。別表には個別の採録地点欄がなく、数値の境界が重なる記載も保持しました。マグロの行とクロマグロ、ビルとヒルの対応を保留しました。道北の表で「おおなご」「そい」が複数の標準和名に対応する例も記録しました。これらは復旧79件の外にある群名候補で、同一の民俗的総称としての範囲は判断不能です。 [福島の大きさ別表](https://www.pref.fukushima.lg.jp/uploaded/attachment/36934.pdf) · [道北の魚類編](https://www.hro.or.jp/fisheries/research/wakkanai/surveys-knowledge-of-fish/inpvt400000007sg/inpvt40000000l0z.html)

28グループ全てで、話者・集団が共有する厳密な同義性、排他的な下位区分、分類の全範囲を確定する情報が不足しています。`folk_unit_audit.csv` で資料上の同一標準和名への記載、複数種にまたがる呼称の手掛かり、成長・大きさ、下位分類の判断を区別し、旧単位は全件 `provisional` としました。

## 書誌と利用

既存7件のURLを開きました。福島方言集、道北魚類編、北水試だよりのカスベ記事、北海道庁のクロソイ、森中の鮫皮資料の5件は、表題・責任主体と刊行年または表示された日付・大会年を確認しました。2件の農水省郷土料理ページは表題・公開主体・内容確認までで、初出年と個別採録年は不明です。ウェブ頁の更新日は採録年と区別しました。 [カスベ記事](https://www.hro.or.jp/upload/41158/dayori1003_kasube.pdf) · [北海道庁クロソイ](https://www.pref.hokkaido.lg.jp/sr/gid/fis033.html) · [鮫皮資料の大会書誌](https://jses.info/archives/symposium/2005-1) · [栃木](https://www.maff.go.jp/j/keikaku/syokubunka/k_ryouri/search_menu/menu/31_5_tochigi.html) · [青森](https://www.maff.go.jp/j/keikaku/syokubunka/k_ryouri/search_menu/menu/sameno_sukume_aomori.html)

`use_evidence.csv` は既存2行、同一資料内の使用事例2記載、照合保留・対象外6行です。追加の種単位利用登録は0件です。稚内水試のイカナゴ解説には、サイズ別の呼称と食用・養殖餌料の対応が記載されています。漁業で近縁2種を一括するという記載もあるため、現行の単一種IDや辞典の採録集団に割り当てず、属レベルの質的事例として保存しました。福島の漁況資料、販売資料、同資料集の海産食用動物別表も調べ、対象集団・方法・時期・対象分類群の違いを記録しました。 [稚内水試イカナゴ解説](https://www.hro.or.jp/fisheries/research/wakkanai/surveys-knowledge-of-fish/inpvt400000007sg/inpvt4000000081j.html) · [福島漁況p.5](https://www.pref.fukushima.lg.jp/download/1/gyokyou2012-01.pdf#page=5) · [福島鮮魚便](https://www.pref.fukushima.lg.jp/sec/36035e/suisan-event-aeon.html) · [福島の海産食用動物別表](https://www.pref.fukushima.lg.jp/uploaded/attachment/36936.pdf)

## 検証DB

別の検証DBに名称の掲載照合、24件の大きさ・成長段階、現行目録の学名、書誌状態を反映しました。既存スキーマ版1を使用し、地方名79件、仮置き28件、利用2件、地域・文脈各4件を保持しました。出典はJAF版43を加え8件です。地方名と魚種の対応の確実性は79件とも `uncertain` を保持しました。元DBのハッシュ、外部キー違反0件、SQLite整合性検査、既存の地域別名記録数を再確認しました。

| DB | SHA-256 |
| --- | --- |
| 復旧版の元DB | `6691469c99e9b50b178d4b4c4353d691e2e88b5ae6787860a3c13753bab2a2cb` |
| Phase 2検証DB | `d2ef3a2b010707fdaac68e435fe5fe0aac6076e4f88977133fc0957ffa48a76e` |

復旧用ZIPと元DBを指定したpytestはPython 3.11・3.12で各46件に合格しました。検証DBのコピーを使った操作テストでは、現行学名の検索、2文脈のSankey図、14標準和名の地域間比較とCSV出力を確認しました。「確認済みの記録に限定する」を選んだ地域間比較は0件です。

公開ブランチには監査結果、出典のURLと箇所、検証DBを作るコードを置きます。原資料のPDF・HTML・全種リストとSQLiteはローカルに保管します。解析に使える範囲と不足条件は別紙にまとめました。 [分析準備状況](./analysis_readiness.md)
