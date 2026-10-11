#!/usr/bin/env python3
"""
render_cards.py - 把 knowledge-cards-mark 的 Markdown 卡片输出渲染成图片卡片（PNG）。

用法:
    python render_cards.py <cards.md> [--out DIR] [--scale N] [--font PATH] [--bold-font PATH]
    python render_cards.py <cards.md> --sheet [--sheet-name NAME] [--scale N]

输入格式与 SKILL.md 定义的文本输出完全一致:
    # 知识卡片（N 张）· 《文章标题》
    > 说明：...(可选)
    ## 1. 卡片标题
    **核心知识**：...
    **简明解释**：...
    **例子**：... 或 **自测问题**：...

输出:
    默认: 每张卡片一个 PNG, 文件名为 01-title.png, 02-title.png ...
         输出到输入文件同目录下的 cards/ 子目录。
    --sheet: 把所有卡片渲染为 1 张合并长图（顶部文章标题横幅 + 纵向排列的卡片单元）。
"""

import argparse
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------- 默认版式（统一规格，可按 --scale 整体放大） ----------
W, H = 1080, 1350          # 单卡画布（3:4 竖版）
SCALE = 1
MARGIN = 56                # 外框边距
BORDER_W = 4               # 外框线宽
TITLE_H = 168              # 卡片标题栏高度
TITLE_BG = (43, 76, 126)   # 标题栏深蓝
BORDER_COLOR = (60, 90, 140)
BG = (255, 255, 255)
INK = (33, 37, 41)         # 正文深灰黑
LABEL_BG = {"核心知识": (43, 76, 126), "简明解释": (39, 126, 99), "例子": (203, 112, 30), "自测问题": (203, 112, 30)}
FONT_FALLBACK = [
    "C:/Windows/Fonts/msyh.ttc",        # Windows 微软雅黑
    "C:/Windows/Fonts/simhei.ttf",      # Windows 黑体
    "/System/Library/Fonts/PingFang.ttc",  # macOS 苹方
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Linux Noto
]
BOLD_FALLBACK = [
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]


def find_font(candidates):
    for p in candidates:
        if Path(p).exists():
            return p
    return None


def parse_cards(md_text):
    """解析 SKILL.md 输出格式的 Markdown, 返回 (article_title, note, cards)。"""
    article = None
    note = None
    cards = []
    cur = None
    for line in md_text.splitlines():
        m = re.match(r"^#\s+知识卡片.*《(.+)》", line)
        if m:
            article = m.group(1).strip()
            continue
        m = re.match(r"^>\s*说明[:：]\s*(.+)", line)
        if m:
            note = m.group(1).strip()
            continue
        m = re.match(r"^##\s+(\d+)\.\s*(.+)$", line)
        if m:
            if cur:
                cards.append(cur)
            cur = {"title": m.group(2).strip(), "fields": []}
            continue
        if cur:
            m = re.match(r"^\*\*(核心知识|简明解释|例子|自测问题)\*\*[:：]\s*(.+)$", line)
            if m:
                cur["fields"].append((m.group(1), m.group(2).strip()))
    if cur:
        cards.append(cur)
    return article, note, cards


def wrap_text(draw, text, font, max_width):
    """按像素宽度换行（中英文混排）。行首禁则：短行若以中文标点开头，把标点并入上一行，避免"。"单独成行。"""
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) <= max_width or not cur:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        while cur and len(cur) <= 2 and lines and cur[0] in "。，、；：）】》！」？":
            lines[-1] += cur[0]
            cur = cur[1:]
        lines.append(cur)
    return lines


def layout_fields(card, inner_w, fonts):
    """预排版字段：返回 [(label, weight_font, lines)]。"""
    font_body, font_bold, font_label, font_small = fonts
    tmp = Image.new("RGB", (10, 10))
    d = ImageDraw.Draw(tmp)
    out = []
    for label, text in card["fields"]:
        weight = font_bold if label == "核心知识" else font_body
        out.append((label, weight, wrap_text(d, text, weight, inner_w)))
    return out


def fields_height(layout, fonts):
    """字段区总高度。"""
    s = SCALE
    line_h = int(fonts[0].size * 1.7)
    h = 0
    for _label, _weight, lines in layout:
        h += int(62 * s) + len(lines) * line_h + int(22 * s)
    return h


def draw_fields(d, layout, y, inner_l, fonts):
    """绘制字段区, 返回结束 y。"""
    s = SCALE
    _font_body, _font_bold, font_label, _font_small = fonts
    line_h = int(fonts[0].size * 1.7)
    for label, weight, lines in layout:
        lw = d.textlength(label, font=font_label) + int(36 * s)
        d.rounded_rectangle([inner_l, y, inner_l + lw, y + int(46 * s)],
                            radius=int(23 * s), fill=LABEL_BG.get(label, TITLE_BG))
        d.text((inner_l + int(18 * s), y + int(5 * s)), label, font=font_label, fill=(255, 255, 255))
        y += int(62 * s)
        for line in lines:
            d.text((inner_l, y), line, font=weight, fill=INK)
            y += line_h
        y += int(22 * s)
    return y


def render_card(card, idx, total, note, out_path, fonts):
    """渲染单张卡片。"""
    s = SCALE
    font_body, font_bold, font_label, font_small = fonts
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # 外框（四边统一描边, 保证对齐）
    d.rounded_rectangle([MARGIN, MARGIN, W - MARGIN, H - MARGIN],
                        radius=int(24 * s), outline=BORDER_COLOR, width=BORDER_W)

    # 标题栏
    tb = (MARGIN + BORDER_W, MARGIN + BORDER_W,
          W - MARGIN - BORDER_W, MARGIN + BORDER_W + TITLE_H)
    d.rounded_rectangle(tb, radius=int(18 * s), fill=TITLE_BG)
    title_lines = wrap_text(d, card["title"], font_bold, tb[2] - tb[0] - int(80 * s))
    ty = tb[1] + (tb[3] - tb[1] - len(title_lines) * int(62 * s)) // 2
    for line in title_lines:
        tw = d.textlength(line, font=font_bold)
        d.text(((tb[0] + tb[2]) // 2 - tw / 2, ty), line, font=font_bold, fill=(255, 255, 255))
        ty += int(62 * s)

    # 字段区
    inner_l, inner_r = tb[0] + int(26 * s), tb[2] - int(26 * s)
    y = draw_fields(d, layout_fields(card, inner_r - inner_l, fonts), tb[3] + int(30 * s), inner_l, fonts)

    # 底部：页码 + 说明
    d.text((inner_l, H - MARGIN - int(46 * s)), f"{idx} / {total}", font=font_small, fill=(120, 128, 140))
    if note:
        d.text((inner_r - d.textlength(note, font=font_small), H - MARGIN - int(46 * s)),
               note, font=font_small, fill=(160, 166, 176))

    img.save(out_path, "PNG")
    return out_path


def render_sheet(cards, article, note, out_path, fonts):
    """把所有卡片渲染为 1 张合并长图：顶部文章标题横幅 + 纵向卡片单元。"""
    s = SCALE
    font_body, font_bold, font_label, font_small = fonts
    x0, x1 = MARGIN + BORDER_W, W - MARGIN - BORDER_W
    inner_l, inner_r = x0 + int(26 * s), x1 - int(26 * s)
    inner_w = inner_r - inner_l

    # 预排版与高度计算
    layouts = [layout_fields(c, inner_w, fonts) for c in cards]
    unit_heights = [TITLE_H + int(30 * s) + fields_height(l, fonts) + int(14 * s) for l in layouts]

    header_h = int(150 * s)          # 文章标题横幅
    gap = int(36 * s)                # 单元间距
    bottom_pad = int(80 * s)
    total_h = (MARGIN * 2 + BORDER_W * 2 + header_h + gap
               + sum(unit_heights) + gap * (len(cards) - 1) + bottom_pad)

    img = Image.new("RGB", (W, total_h), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([MARGIN, MARGIN, W - MARGIN, total_h - MARGIN],
                        radius=int(24 * s), outline=BORDER_COLOR, width=BORDER_W)

    # 顶部文章标题横幅
    title = article or "知识卡片"
    d.rounded_rectangle([x0, MARGIN + BORDER_W, x1, MARGIN + BORDER_W + header_h],
                        radius=int(18 * s), fill=TITLE_BG)
    tlines = wrap_text(d, title, font_bold, inner_w)
    ty = MARGIN + BORDER_W + (header_h - len(tlines) * int(62 * s)) // 2
    for tl in tlines:
        tw = d.textlength(tl, font=font_bold)
        d.text(((x0 + x1) // 2 - tw / 2, ty), tl, font=font_bold, fill=(255, 255, 255))
        ty += int(62 * s)

    y = MARGIN + BORDER_W + header_h + gap
    for i, (card, lay, uh) in enumerate(zip(cards, layouts, unit_heights), 1):
        # 卡片单元细外框
        d.rounded_rectangle([x0, y, x1, y + uh], radius=int(16 * s),
                            outline=(206, 214, 226), width=max(2, int(2 * s)))
        # 卡片标题栏（单元内部, 保留 2px 内边距）
        ins = max(2, int(2 * s))
        cb = (x0 + ins, y + ins, x1 - ins, y + ins + TITLE_H)
        d.rounded_rectangle(cb, radius=int(16 * s), fill=TITLE_BG)
        d.text((cb[0] + int(14 * s), cb[1] + int(8 * s)), f"{i}", font=font_small, fill=(150, 165, 190))
        ct = wrap_text(d, card["title"], font_bold, inner_w)
        cty = cb[1] + (cb[3] - cb[1] - len(ct) * int(62 * s)) // 2
        for cl in ct:
            cw = d.textlength(cl, font=font_bold)
            d.text(((cb[0] + cb[2]) // 2 - cw / 2, cty), cl, font=font_bold, fill=(255, 255, 255))
            cty += int(62 * s)
        # 字段区
        draw_fields(d, lay, cb[3] + int(30 * s), inner_l, fonts)
        y += uh + gap

    # 底部：总张数 + 说明
    d.text((inner_l, total_h - MARGIN - int(46 * s)), f"共 {len(cards)} 张 · {title}",
           font=font_small, fill=(120, 128, 140))
    if note:
        d.text((inner_r - d.textlength(note, font=font_small), total_h - MARGIN - int(46 * s)),
               note, font=font_small, fill=(160, 166, 176))

    img.save(out_path, "PNG")
    return out_path


def main():
    ap = argparse.ArgumentParser(description="把 knowledge-cards-mark 的 Markdown 卡片渲染为 PNG")
    ap.add_argument("cards_md", help="知识卡片 Markdown 文件路径")
    ap.add_argument("--out", default=None, help="输出目录（默认: 输入文件同目录/cards）")
    ap.add_argument("--scale", type=float, default=1.0, help="整体放大倍数（如 2 输出 2160x2700）")
    ap.add_argument("--font", default=None, help="正文字体文件路径")
    ap.add_argument("--bold-font", default=None, help="标题/加粗字体文件路径")
    ap.add_argument("--sheet", action="store_true", help="把所有卡片渲染为 1 张合并长图（默认每卡一张 PNG）")
    ap.add_argument("--sheet-name", default=None, help="合并长图文件名（默认: <文章标题>-知识卡片.png）")
    args = ap.parse_args()

    src = Path(args.cards_md)
    if not src.exists():
        print(f"错误: 找不到文件 {src}", file=sys.stderr)
        return 1

    md_text = src.read_text(encoding="utf-8")
    article, note, cards = parse_cards(md_text)
    if not cards:
        print("错误: 未解析到任何卡片，请检查 Markdown 是否符合 SKILL.md 输出格式", file=sys.stderr)
        return 1

    out_dir = Path(args.out) if args.out else src.parent / "cards"
    out_dir.mkdir(parents=True, exist_ok=True)

    font_p = args.font or find_font(FONT_FALLBACK)
    bold_p = args.bold_font or find_font(BOLD_FALLBACK)
    if not font_p or not bold_p:
        print("错误: 未找到可用中文字体，请用 --font / --bold-font 指定", file=sys.stderr)
        return 1

    s = args.scale
    size = lambda px: max(8, int(px * s))
    fonts = (
        ImageFont.truetype(font_p, size(34)),
        ImageFont.truetype(bold_p, size(36)),
        ImageFont.truetype(font_p, size(30)),
        ImageFont.truetype(font_p, size(24)),
    )

    global W, H, SCALE, MARGIN, BORDER_W, TITLE_H
    SCALE = s
    W, H = int(W * s), int(H * s)
    MARGIN, BORDER_W, TITLE_H = int(MARGIN * s), max(2, int(BORDER_W * s)), int(TITLE_H * s)

    if args.sheet:
        fname = args.sheet_name or f"{re.sub(r'[\\/:*?\"<>|\s]+', '-', article or '知识卡片')[:40]}-知识卡片.png"
        out = render_sheet(cards, article, note, out_dir / fname, fonts)
        print(f"✅ 合并长图: {out}")
        return 0

    saved = []
    for i, card in enumerate(cards, 1):
        name = f"{i:02d}-{re.sub(r'[\\/:*?\"<>|\s]+', '-', card['title'])[:30]}.png"
        out = render_card(card, i, len(cards), note, out_dir / name, fonts)
        saved.append(str(out))
        print(f"✅ {out}")

    print(f"\n共渲染 {len(saved)} 张卡片 -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
