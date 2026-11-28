"""Markdownから卒論の表・模式図・Word・PDFを再生成する。"""
import csv
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import fitz
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from draw_figures import draw_all


ROOT = Path(__file__).resolve().parent
SERIF = "Noto Serif CJK JP"
SANS = "Noto Sans CJK JP"
INK = RGBColor.from_string("192D43")
TABLE_FILES = ("table_1_sources.csv", "table_2_names_and_uses.csv", "table_3_onahama_shipments.csv")
COLUMN_WIDTHS = ((38, 41, 45, 40), (34, 37, 46, 47), (20, 33, 40, 50, 21))
TOC_EXPRESSION = re.compile(r"^## 目次\n\n((?:- .+\n)+)", re.MULTILINE)
TABLE_EXPRESSION = re.compile(r"^\*\*表([1-3])　.+\*\*\n\n((?:\|[^\n]+\|\n)+)", re.MULTILINE)


def manuscript_text():
    path = ROOT / "thesis.md"
    original = path.read_text(encoding="utf-8")
    bibliography = (ROOT / "bibliography.md").read_text(encoding="utf-8")
    references = re.sub(r"^#", "##", bibliography, flags=re.MULTILINE)
    appendix = "## 付録　資料の追跡方法"
    main, appendix_text = original.split(appendix, 1)
    main = main.split("\n## 参考文献\n", 1)[0].rstrip()
    text = f"{main}\n\n{references.rstrip()}\n\n{appendix}{appendix_text}"
    if text != original:
        path.write_text(text, encoding="utf-8")
    return text


def write_tables(text):
    directory = ROOT / "tables"
    directory.mkdir(exist_ok=True)
    blocks = TABLE_EXPRESSION.findall(text)
    if [number for number, _ in blocks] != ["1", "2", "3"]:
        raise ValueError("表1〜3が文書内で一意に並ぶ必要がある。")
    outputs = []
    for filename, widths, (_, block) in zip(TABLE_FILES, COLUMN_WIDTHS, blocks):
        lines = block.splitlines()
        rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in [lines[0], *lines[2:]]]
        if any(len(row) != len(widths) for row in rows):
            raise ValueError(f"{filename} の列数が一致しない。")
        with (directory / filename).open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream, lineterminator="\n").writerows(rows)
        outputs.append(rows)
    return outputs


def set_fonts(style, family, size):
    style.font.name = family
    style.font.size = Pt(size)
    fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
    for name in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        fonts.attrib.pop(qn(f"w:{name}"), None)
    fonts.set(qn("w:eastAsia"), family)
    fonts.set(qn("w:cs"), family)


def xml_child(parent, name):
    existing = parent.find(qn(f"w:{name}"))
    if existing is not None:
        return existing
    child = OxmlElement(f"w:{name}")
    parent.append(child)
    return child


def style_document(document):
    styles = {style.style_id: style for style in document.styles}
    for name in ("Normal", "BodyText", "FirstParagraph", "Compact"):
        style = styles[name]
        set_fonts(style, SERIF, 11)
        style.paragraph_format.space_after = Pt(6)
        style.paragraph_format.line_spacing = Pt(18 if name != "Compact" else 16)
    for name, size in (("Heading2", 17), ("Heading3", 12), ("Title", 23), ("Subtitle", 13), ("Caption", 10)):
        style = styles[name]
        set_fonts(style, SANS, size)
        style.font.color.rgb = INK
        style.font.italic = False
        style.paragraph_format.line_spacing = 1.10
        style.paragraph_format.keep_with_next = name != "Caption"
        style.paragraph_format.space_before = Pt(12 if name == "Heading3" else 4)
        style.paragraph_format.space_after = Pt(6)

    section = document.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.top_margin, section.bottom_margin = Mm(23), Mm(22)
    section.left_margin, section.right_margin = Mm(23), Mm(23)
    section.footer_distance = Mm(10)
    section.different_first_page_header_footer = True
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    field = xml_child(footer._p, "fldSimple")
    field.set(qn("w:instr"), "PAGE")


def style_cover(document, first, abstract):
    title = first.text
    main, subtitle, _ = title.split(" ―")
    document.core_properties.title = title
    document.core_properties.subject = "魚類地方名と利用文化の文献事例研究"
    document.core_properties.author = ""
    document.core_properties.last_modified_by = ""
    label = first.insert_paragraph_before("教養卒業論文", style="Subtitle")
    label.alignment = WD_ALIGN_PARAGRAPH.CENTER
    label.paragraph_format.space_before = Pt(92)

    first.text = main.replace("による", "による\n", 1)
    first.style = document.styles["Title"]
    first.alignment = WD_ALIGN_PARAGRAPH.CENTER
    first.paragraph_format.space_before = Pt(64)
    first.paragraph_format.space_after = Pt(24)

    cover_subtitle = abstract.insert_paragraph_before("― " + subtitle.strip() + " ―", style="Subtitle")
    cover_subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cover_subtitle.paragraph_format.keep_with_next = False
    abstract.paragraph_format.page_break_before = True


def style_tables(document):
    if len(document.tables) != len(COLUMN_WIDTHS):
        raise ValueError("生成したWordに表1〜3がそろっていない。")
    for table_index, (table, widths) in enumerate(zip(document.tables, COLUMN_WIDTHS)):
        table.autofit = False
        for column, width in zip(table.columns, widths):
            column.width = Mm(width)
        borders = xml_child(table._tbl.tblPr, "tblBorders")
        for edge in ("top", "bottom", "insideH"):
            line = xml_child(borders, edge)
            line.set(qn("w:val"), "single")
            line.set(qn("w:sz"), "4")
            line.set(qn("w:color"), "B6C7D3")
        for edge in ("left", "right", "insideV"):
            xml_child(borders, edge).set(qn("w:val"), "nil")
        for row_index, row in enumerate(table.rows):
            props = row._tr.get_or_add_trPr()
            xml_child(props, "cantSplit")
            if row_index == 0:
                xml_child(props, "tblHeader")
            for column_index, (cell, width) in enumerate(zip(row.cells, widths)):
                cell.width = Mm(width)
                cell_props = cell._tc.get_or_add_tcPr()
                if row_index == 0:
                    xml_child(cell_props, "shd").set(qn("w:fill"), "E7EEF4")
                for edge in ("top", "bottom", "left", "right"):
                    padding = xml_child(xml_child(cell_props, "tcMar"), edge)
                    padding.set(qn("w:w"), "78")
                    padding.set(qn("w:type"), "dxa")
                for paragraph in cell.paragraphs:
                    fmt = paragraph.paragraph_format
                    fmt.line_spacing = Pt(14.5)
                    fmt.space_before = Pt(0)
                    fmt.space_after = Pt(0)
                    fmt.keep_with_next = True
                    if table_index == 2 and column_index > 0 and row_index > 0:
                        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    for run in paragraph.runs:
                        run.font.size = Pt(9.6)
                        if row_index == 0:
                            run.font.bold = True
                            run.font.color.rgb = INK


def format_toc(paragraph, page):
    props = paragraph._p.get_or_add_pPr()
    number_properties = props.find(qn("w:numPr"))
    if number_properties is not None:
        props.remove(number_properties)
    paragraph.style = "Normal"
    paragraph.paragraph_format.space_after = Pt(3)
    paragraph.paragraph_format.left_indent = Mm(0)
    paragraph.paragraph_format.first_line_indent = Pt(0)
    paragraph.paragraph_format.tab_stops.add_tab_stop(Mm(158), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
    if page is not None:
        paragraph.add_run(f"\t{page}")


def format_manuscript(source, destination, toc_titles, page_map):
    document = Document(source)
    style_document(document)
    paragraphs = document.paragraphs
    abstract = next(p for p in paragraphs if p.text == "要旨")
    style_cover(document, paragraphs[0], abstract)
    in_toc = False
    paragraphs = document.paragraphs
    for index, paragraph in enumerate(paragraphs):
        text = paragraph.text
        fmt = paragraph.paragraph_format
        if text == "目次":
            in_toc = True
            continue
        if in_toc and text in toc_titles and not paragraph.style.name.startswith("Heading"):
            format_toc(paragraph, page_map.get(text))
            continue
        if paragraph.style.name == "Heading 2" and text in toc_titles:
            fmt.page_break_before = True
            in_toc = False
        if paragraph._p.xpath(".//w:drawing"):
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            fmt.line_spacing = 1.0
            fmt.keep_with_next = True
            fmt.space_before = Pt(6)
        elif re.match(r"^[図表][1-3]　", text):
            paragraph.style = document.styles.get_by_id("Caption", paragraph.style.type)
            fmt.keep_with_next = True
            for run in paragraph.runs:
                run.font.bold = True
        elif text.startswith(("注　", "出典　")):
            fmt.space_after = Pt(5)
            fmt.line_spacing = Pt(13)
            fmt.keep_with_next = text.startswith("注　")
            for run in paragraph.runs:
                run.font.size = Pt(9)
        elif paragraph.style.name in ("Normal", "Body Text", "First Paragraph") and text:
            fmt.first_line_indent = Pt(11)
            if index + 1 < len(paragraphs) and paragraphs[index + 1]._p.xpath(".//w:drawing"):
                fmt.keep_with_next = True

    for shape in document.inline_shapes:
        factor = min(Mm(158) / shape.width, Mm(70) / shape.height)
        shape.width = round(shape.width * factor)
        shape.height = round(shape.height * factor)
    style_tables(document)
    document.save(destination)


def command(args, directory):
    completed = subprocess.run(args, cwd=directory, capture_output=True, text=True, timeout=60)
    if completed.returncode:
        raise RuntimeError(f"{args[0]} の処理に失敗した。\n{completed.stderr}\n{completed.stdout}")


def export_pdf(office, docx_path, directory):
    profile = (directory / "lo-profile").as_uri()
    command([office, f"-env:UserInstallation={profile}", "--headless",
             "--convert-to", "pdf:writer_pdf_Export",
             "--outdir", str(directory), str(docx_path)], ROOT)
    pdf_path = docx_path.with_suffix(".pdf")
    if not pdf_path.is_file():
        raise RuntimeError("LibreOfficeのPDF出力が見つからない。")
    return pdf_path


def page_locations(pdf_path, titles):
    with fitz.open(pdf_path) as pdf:
        page_lines = [
            {re.sub(r"\s+", "", line) for line in page.get_text().splitlines()}
            for page in pdf
        ]
    locations = {}
    for title in titles:
        plain = re.sub(r"\s+", "", title)
        matches = [i + 1 for i, lines in enumerate(page_lines) if i >= 2 and plain in lines]
        if len(matches) != 1:
            raise ValueError(f"PDFの見出し「{title}」の位置を確定できない。")
        locations[title] = matches[0]
    return locations


def body_count(text):
    main = re.split(r"^## (?:第1章　はじめに|参考文献)$", text, flags=re.MULTILINE)[1]
    paragraphs = [
        line for line in main.splitlines()
        if not line.startswith(("#", "|", "![", "**表", "**図", "注　", "出典　"))
    ]
    return len(re.sub(r"\s|\*", "", "".join(paragraphs)))


def build():
    pandoc = shutil.which("pandoc")
    office = shutil.which("soffice") or shutil.which("libreoffice")
    if pandoc is None or office is None:
        raise RuntimeError("PandocおよびLibreOfficeが必要である。")

    text = manuscript_text()
    tables = write_tables(text)
    draw_all(ROOT / "figures", tables[1][1:3])
    toc_titles = [line[2:] for line in TOC_EXPRESSION.search(text)[1].splitlines()]
    with TemporaryDirectory(prefix="ffta-thesis-", dir=ROOT.parent) as temp:
        directory = Path(temp)
        raw = directory / "raw.docx"
        command([pandoc, "--from=markdown-implicit_figures-smart", "--to=docx",
                 "-o", str(raw), "thesis.md"], ROOT)
        probe = directory / "probe.docx"
        format_manuscript(raw, probe, toc_titles, {})
        page_map = page_locations(export_pdf(office, probe, directory), toc_titles)
        docx_path = directory / "thesis.docx"
        format_manuscript(raw, docx_path, toc_titles, page_map)
        pdf_path = export_pdf(office, docx_path, directory)
        if page_locations(pdf_path, toc_titles) != page_map:
            raise ValueError("目次の頁と最終PDFの頁が一致しない。")
        docx_path.replace(ROOT / "thesis.docx")
        pdf_path.replace(ROOT / "thesis.pdf")
    with fitz.open(ROOT / "thesis.pdf") as pdf:
        print(f"本文{body_count(text):,}字。PDF {len(pdf)}頁。")
    print("、".join(f"{name} {page}頁" for name, page in page_map.items()))


if __name__ == "__main__":
    build()
