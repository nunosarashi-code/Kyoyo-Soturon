"""卒論の三つの模式図を作る。値を推計する処理は行わない。"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


INK = "#192d43"
TEAL = "#17625d"
BORDER = "#a5b5c2"
GRAY = "#576673"
PALE = "#f2f5f7"
GREEN = "#e9f5f2"
WHEAT = "#f8f4eb"


def canvas(figsize):
    figure, ax = plt.subplots(figsize=figsize)
    figure.subplots_adjust(left=0, right=1, bottom=0, top=1)
    ax.set(xlim=(0, 1), ylim=(0, 1))
    ax.set_axis_off()
    return figure, ax


def box(ax, x, y, width, height, *, fill=PALE, border=BORDER, dashed=False):
    ax.add_patch(
        FancyBboxPatch(
            (x, y), width, height, boxstyle="round,pad=0.004,rounding_size=0.012",
            facecolor=fill, edgecolor=border, linewidth=1.0,
            linestyle="--" if dashed else "-", transform=ax.transAxes,
        )
    )


def label(ax, x, y, text, *, size=12, color=INK, weight="normal"):
    ax.text(
        x, y, text, ha="center", va="center", fontsize=size, color=color,
        weight=weight, multialignment="center", linespacing=1.30,
    )


def arrow(ax, x1, x2, y):
    ax.add_patch(
        FancyArrowPatch((x1, y), (x2, y), arrowstyle="-|>", mutation_scale=13,
                        color=GRAY, linewidth=1.15)
    )


def save(figure, path):
    figure.savefig(path, dpi=300, facecolor="white")
    plt.close(figure)


def workflow(path):
    figure, ax = canvas((9, 2.26))
    width = 0.211
    positions = [0.018, 0.270, 0.522, 0.774]
    steps = [
        ("資料を集める", "方言集・漁業解説\n出荷統計・先行研究"),
        ("原資料に照合する", "掲載箇所と記載を確認\n対象・時点・出典を記録"),
        ("文脈を分けて記録する", "呼称・指示対象・用途\n確かめられない点を保持"),
        ("事例を比較する", "呼び分けと用途の対応\n成立・維持の根拠を検討"),
    ]
    for i, (x, (title, detail)) in enumerate(zip(positions, steps)):
        shade = GREEN if i == len(steps) - 1 else PALE
        box(ax, x, 0.15, width, 0.70, fill=shade)
        label(ax, x + width / 2, 0.65, title, size=13, weight="bold")
        label(ax, x + width / 2, 0.38, detail, size=10.7)
        if i < len(positions) - 1:
            arrow(ax, x + width + 0.006, positions[i + 1] - 0.006, 0.52)
    save(figure, path)


def dohoku(path, name_rows):
    figure, ax = canvas((9, 3.03))
    width = 0.279
    positions = [0.035, 0.360, 0.685]
    for x, category in zip(positions, ("解説の呼称と大きさ", "解説にある漁法", "解説にある用途")):
        label(ax, x + width / 2, 0.89, category, weight="bold", color=TEAL)
    gears = ("棒受け網など", "沖合底びき網・定置網など")
    uses = ("食用", "主に養殖餌料")
    for y, row, gear, use in zip((0.57, 0.31), name_rows, gears, uses):
        for i, (x, text) in enumerate(
            zip(positions, (f"{row[1]}\n{row[2]}", gear, use))
        ):
            box(ax, x, y, width, 0.196, fill=GREEN if i == 2 else PALE)
            label(ax, x + width / 2, y + 0.098, text, size=13)
            if i < len(positions) - 1:
                arrow(ax, x + width + 0.008, positions[i + 1] - 0.008, y + 0.098)
    box(ax, 0.035, 0.035, 0.929, 0.16, fill=WHEAT, dashed=True)
    label(ax, 0.5, 0.115, "別資料のオオナゴの食用例　燻製・かば焼きなど", size=12.5)
    save(figure, path)


def evidence(path):
    figure, ax = canvas((9, 2.77))
    positions = [0.225, 0.483, 0.741]
    width = 0.235
    heading = ("大きさの記載", "呼称と用途の対応", "成立・維持の理由")
    for x, text in zip(positions, heading):
        label(ax, x + width / 2, 0.91, text, color=TEAL, weight="bold")
    rows = [
        ("道北\nイカナゴ属", "記載あり", "同じ解説に記載", "未確認"),
        ("福島\nマイワシ", "記載あり", "用途は別年代の\n港別統計", "未確認"),
        ("福島\nマダラ", "記載あり", "利用は別資料の\n市況・加工記事", "未確認"),
    ]
    for index, (y, row) in enumerate(zip((0.56, 0.30, 0.04), rows)):
        box(ax, 0.026, y, 0.178, 0.203, fill=PALE)
        label(ax, 0.115, y + 0.1015, row[0], weight="bold")
        for j, (x, value) in enumerate(zip(positions, row[1:])):
            shade = (GREEN, (GREEN if index == 0 else WHEAT), PALE)[j]
            box(ax, x, y, width, 0.203, fill=shade)
            label(ax, x + width / 2, y + 0.1015, value, color=GRAY if j == 2 else INK)
    save(figure, path)


def draw_all(destination: Path, dohoku_rows) -> None:
    destination.mkdir(exist_ok=True)
    with plt.rc_context({"font.family": ["Noto Sans CJK JP"], "axes.unicode_minus": False}):
        workflow(destination / "figure_1_workflow.png")
        dohoku(destination / "figure_2_dohoku.png", dohoku_rows)
        evidence(destination / "figure_3_evidence.png")
