"""提出用の本文・図表と事例証拠CSVの対応を確認する。"""
import csv
from hashlib import sha256
import re
from unicodedata import normalize
from zipfile import ZipFile

import fitz
from docx import Document

from build_thesis import ROOT, TABLE_EXPRESSION, TABLE_FILES, body_count, page_locations


def check(condition, message):
    if not condition:
        raise ValueError(message)


def normalized(text):
    return re.sub(r"\s+", "", normalize("NFKC", text))


def read_rows(path, *, named=False):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader if named else csv.reader
        return list(reader(stream, strict=True))


def verify_references(text, ledger):
    references = (ROOT / "bibliography.md").read_text(encoding="utf-8")
    excerpt, appendix = text.split("\n## 参考文献\n", 1)[1].split("\n## 付録", 1)
    bibliography = references.split("\n", 1)[1].rstrip()
    check(excerpt.strip() == re.sub(r"^## ", "### ", bibliography, flags=re.MULTILINE).strip(),
          "本文と独立した参考文献一覧が一致しない。")
    citing_text = text.split("\n## 参考文献\n", 1)[0] + "\n" + appendix
    citations = [row["citation"] for row in ledger if row["kind"] == "参考文献"]
    check(len(citations) == len(set(citations)) == len(re.findall(r"^- ", bibliography, re.MULTILINE)),
          "引用台帳に欠落または重複がある。")
    for label in citations:
        author, year = label.rsplit(" ", 1)
        check(re.search(rf"{re.escape(author)}[^\n。]{{0,45}}{re.escape(year)}", citing_text) is not None,
              f"本文で {label} を確認できない。")
    return len(citations)


def verify_tables(text, docx, cases):
    word_tables = [[[cell.text.strip() for cell in row.cells] for row in table.rows] for table in docx.tables]
    stored_tables = [read_rows(ROOT / "tables" / file) for file in TABLE_FILES]
    markdown_tables = []
    for _, block in TABLE_EXPRESSION.findall(text):
        header, _, *lines = block.splitlines()
        markdown_tables.append([[s.strip() for s in row.strip("|").split("|")] for row in [header, *lines]])
    check(word_tables == stored_tables == markdown_tables, "本文・Word・CSVの表が一致しない。")

    for row, start in zip(stored_tables[2][1:], (14, 18)):
        total, fresh, processed, feed = [cases[f"SAR-{n:02d}"]["value"] for n in range(start, start + 4)]
        check([item.replace(",", "") for item in row[1:]] == [fresh, processed, feed, total],
              f"表3の{row[0]}がPhase 3の公表値と一致しない。")
    for row, identity in zip(stored_tables[1][3:8], ("SAR-01", "SAR-02", "SAR-03", "SAR-04", "SAR-05")):
        source = cases[identity]
        check(row[1] == source["local_names"] and row[2] == source["distinguishing_trait"],
              f"表2の呼称・体長が {identity} と一致しない。")
    return stored_tables


def verify():
    text = (ROOT / "thesis.md").read_text(encoding="utf-8")
    ledger = read_rows(ROOT / "final_evidence_check.csv", named=True)
    cases = {row["evidence_id"]: row for row in read_rows(ROOT.parent / "phase3" / "case_evidence.csv", named=True)}
    check(len({row["check_id"] for row in ledger}) == len(ledger), "照合IDが重複している。")
    for row in ledger:
        ids = set(row["case_evidence_ids"].split(" | ")) - {""}
        check(ids <= cases.keys(), f"{row['check_id']} に無効な事例証拠IDがある。")
        check(bool(row["source_urls"] and row["locator"] and row["status"]), f"{row['check_id']} に照合情報がない。")
    references = verify_references(text, ledger)

    docx_file = ROOT / "thesis.docx"
    figure_paths = [ROOT / path for path in re.findall(r"^!\[.+\]\((figures/[^)]+)\)$", text, re.MULTILINE)]
    with ZipFile(docx_file) as archive:
        check(archive.testzip() is None, "WordファイルのZIP整合性エラー。")
        embedded = {sha256(archive.read(name)).hexdigest() for name in archive.namelist() if name.startswith("word/media/")}
    check(len(figure_paths) == 3 and {sha256(p.read_bytes()).hexdigest() for p in figure_paths} <= embedded,
          "Wordの模式図がMarkdownの図と一致しない。")
    docx = Document(docx_file)
    tables = verify_tables(text, docx, cases)

    pdf_file = ROOT / "thesis.pdf"
    titles = re.findall(r"^## (第[1-5]章　.+|参考文献|付録　資料の追跡方法)$", text, re.MULTILINE)
    pages = page_locations(pdf_file, titles)
    check(len(pages) == 7, "章・参考文献・付録の見出しが欠落している。")
    for title, page in pages.items():
        check(any(p.text == f"{title}\t{page}" for p in docx.paragraphs), f"{title} の目次の頁が異なる。")
    with fitz.open(pdf_file) as pdf:
        check(all(abs(p.rect.width - 595.3) < 1 and abs(p.rect.height - 841.9) < 1 for p in pdf),
              "PDFがA4でない。")
        words = normalized("\n".join(p.get_text() for p in pdf))
        for datum in ("5〜6 cm", "約15 cm", "2,606", "222百万円", "5,751 kg", "107円/kg", "5.6 t", "1.0百万円"):
            check(normalized(datum) in words, f"PDFに数値 {datum} がない。")
        captions = re.findall(r"^\*\*(図[1-3]　.+)\*\*$", text, re.MULTILINE)
        check(len(captions) == 3, "図のキャプションに欠落または重複がある。")
        for caption in captions:
            check(any(normalized(caption) in normalized(p.get_text()) and p.get_image_info() for p in pdf),
                  f"PDFの「{caption}」と図を同じ頁で確認できない。")
        for number, rows in enumerate(tables, 1):
            check(all(normalized(cell) in words for row in rows for cell in row), f"PDFの表{number}に欠落がある。")
        page_count = len(pdf)
    print(f"本文{body_count(text):,}字、PDF {page_count}頁、図3点、表3点、引用文献{references}項目、最終照合{len(ledger)}行。")


if __name__ == "__main__":
    verify()
