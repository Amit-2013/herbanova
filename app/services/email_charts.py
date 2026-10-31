"""PNG charts for the scheduled emails, drawn locally with Pillow.

No JavaScript, no external chart service and no remote image: the email carries
the PNG as a CID attachment, so it renders in Outlook and Gmail with images
enabled. Every chart is followed by the same figures in a table, so the message
is complete when images are blocked. A drawing failure is not fatal: the caller
keeps the table and drops the image.
"""
from __future__ import annotations

import io
from decimal import Decimal

from PIL import Image, ImageDraw, ImageFont

GREEN = "#1F6B4A"
AMBER = "#D9A441"
RED = "#B3261E"
ORANGE = "#C9702A"
INK = "#16211B"
MUTED = "#56635B"
GRID = "#E2E8E4"


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                     # older Pillow without the size argument
        return ImageFont.load_default()


def short_money(value) -> str:
    amount = Decimal(value or 0)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount >= Decimal("10000000"):
        return f"{sign}₹ {amount / Decimal('10000000'):.2f} Cr"
    if amount >= Decimal("100000"):
        return f"{sign}₹ {amount / Decimal('100000'):.1f} L"
    if amount >= Decimal("1000"):
        return f"{sign}₹ {amount / Decimal('1000'):.1f} K"
    return f"{sign}₹ {amount:.0f}"


def _image(width: int, height: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (width, height), "white")
    return image, ImageDraw.Draw(image)


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def logo() -> bytes:
    """A small transparent leaf mark for the email header (CID inline)."""
    image = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 4, 92, 92), radius=18, fill=(255, 255, 255, 40),
                           outline=(255, 255, 255, 190), width=3)
    draw.ellipse((26, 22, 72, 66), outline=(255, 255, 255, 235), width=4)
    draw.line((38, 58, 62, 34), fill=(255, 255, 255, 235), width=4)
    draw.line((58, 34, 70, 38), fill=(255, 255, 255, 235), width=4)
    draw.text((40, 64), "H", fill=(255, 255, 255, 255), font=_font(16))
    return _png(image)


def sales_purchases(series: list[dict]) -> bytes:
    """Grouped bars: sales in green, purchases in amber, for each bucket."""
    width, height = 1000, 340
    image, draw = _image(width, height)
    left, right, top, bottom = 70, 20, 40, 60
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [abs(float(r.get("sales") or 0)) for r in series] + \
             [abs(float(r.get("purchases") or 0)) for r in series]
    peak = max(values or [0]) or 1.0
    draw.text((left, 12), "Sales vs purchases", fill=INK, font=_font(20))
    draw.line((left, height - bottom, width - right, height - bottom), fill=GRID, width=1)
    n = max(len(series), 1)
    slot = plot_w / n
    bar_w = min(24, slot / 3)
    for i, row in enumerate(series):
        cx = left + slot * i + slot / 2
        sales = float(row.get("sales") or 0)
        purchases = float(row.get("purchases") or 0)
        for offset, value, colour in ((-bar_w, sales, GREEN), (0, purchases, AMBER)):
            if not value:                  # no bar for zero, never an inverted rectangle
                continue
            h = max(1.0, min(1.0, abs(value) / peak) * (plot_h - 10))
            x0 = cx + offset - bar_w / 2
            draw.rectangle((x0, height - bottom - h, x0 + bar_w, height - bottom - 1),
                           fill=colour)
        draw.text((cx - slot / 2 + 4, height - bottom + 8), str(row.get("label", ""))[:10],
                  fill=MUTED, font=_font(13))
    legend_y = height - 24
    draw.rectangle((left, legend_y - 8, left + 12, legend_y + 4), fill=GREEN)
    draw.text((left + 18, legend_y - 10), "Sales", fill=MUTED, font=_font(14))
    draw.rectangle((left + 90, legend_y - 8, left + 102, legend_y + 4), fill=AMBER)
    draw.text((left + 108, legend_y - 10), "Purchases", fill=MUTED, font=_font(14))
    draw.text((width - right - 130, legend_y - 10), f"Peak {short_money(peak)}",
              fill=MUTED, font=_font(14))
    return _png(image)


def ageing(buckets: list[dict]) -> bytes:
    """Horizontal bars for the four ageing buckets."""
    width, height = 1000, 260
    image, draw = _image(width, height)
    left, right, top = 150, 90, 30
    bar_h, gap = 30, 18
    values = [float(b.get("total") or 0) for b in buckets]
    peak = max(values or [0]) or 1.0
    draw.text((20, 8), "Receivables ageing", fill=INK, font=_font(20))
    colours = {"0-30": GREEN, "31-60": AMBER, "61-90": ORANGE, "90+": RED}
    for i, bucket in enumerate(buckets):
        y = top + i * (bar_h + gap)
        draw.text((20, y + 6), str(bucket.get("label", "")), fill=MUTED, font=_font(15))
        span = width - left - right
        draw.rectangle((left, y, left + span, y + bar_h), fill="#F4F6F3")
        value = float(bucket.get("total") or 0)
        w = max(0.0, min(1.0, value / peak)) * span
        draw.rectangle((left, y, left + w, y + bar_h),
                       fill=colours.get(bucket.get("key"), GREEN))
        draw.text((left + span + 10, y + 6), short_money(value), fill=INK, font=_font(15))
    return _png(image)


def trend(rows: list[dict], series: tuple[tuple[str, str, str], ...] = (
        ("revenue", "Revenue", GREEN), ("collections", "Collections", AMBER))) -> bytes:
    """Line chart for the monthly accounts trend."""
    width, height = 1000, 320
    image, draw = _image(width, height)
    left, right, top, bottom = 70, 30, 40, 50
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [float(r.get(key) or 0) for r in rows for key, _label, _c in series]
    peak = max(values or [0]) or 1.0
    draw.text((left, 12), "Monthly trend", fill=INK, font=_font(20))
    for g in range(4):
        y = top + plot_h * g / 3
        draw.line((left, y, left + plot_w, y), fill=GRID, width=1)
    n = max(len(rows) - 1, 1)
    for key, label, colour in series:
        points = []
        for i, row in enumerate(rows):
            x = left + plot_w * i / n
            y = top + plot_h - (float(row.get(key) or 0) / peak) * (plot_h - 8)
            points.append((x, y))
        if len(points) >= 2:
            draw.line(points, fill=colour, width=3)
        for x, y in points:
            draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=colour)
    for i, row in enumerate(rows):
        if i % 2 == 0 or i == len(rows) - 1:
            x = left + plot_w * i / n
            draw.text((x - 22, height - bottom + 8), str(row.get("label", ""))[:9],
                      fill=MUTED, font=_font(12))
    legend_y = height - 20
    x = left
    for _key, label, colour in series:
        draw.rectangle((x, legend_y - 8, x + 12, legend_y + 4), fill=colour)
        draw.text((x + 18, legend_y - 10), label, fill=MUTED, font=_font(14))
        x += 130
    return _png(image)
