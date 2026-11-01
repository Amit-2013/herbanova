"""The font and drawing helpers every generated PDF uses.

Helvetica carries no Devanagari and no rupee sign, so a Hindi name and an
amount printed with ₹ came out as black squares. Mukta (SIL Open Font
License, see app/assets/fonts/OFL.txt) covers Latin, Devanagari and U+20B9,
and ReportLab only joins Devanagari through a *shaped* draw: a plain
drawString writes the code points in logical order, which renders conjuncts
and vowel signs wrongly. The helpers here register the font once, hand out
paragraph styles that shape their text, and offer a canvas whose draw calls
shape automatically.
"""
from functools import lru_cache
from pathlib import Path

from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
FONT = "Mukta"
FONT_BOLD = "Mukta-Bold"

_ALIASES = {"Helvetica": FONT, "Helvetica-Bold": FONT_BOLD,
            "Helvetica-Oblique": FONT, "Helvetica-BoldOblique": FONT_BOLD}


def _patch_ligature_default(module) -> None:
    original = getattr(module, "shapeFragWord", None)
    if original is None or getattr(original, "_no_optional_ligatures", False):
        return

    def shapeFragWord(w, features=None, force=False):
        # HarfBuzz keeps the font's defaults for every feature not listed, so
        # kern alone still turns "offer" into a single ff glyph. Turning the
        # Latin ligature features off leaves Devanagari conjuncts untouched
        # (they come from akhn/rphf, verified glyph-for-glyph) and keeps
        # English text extractable: "Office" stays O-f-f-i-c-e.
        if features is None:
            features = {"kern": True, "liga": False, "clig": False, "dlig": False}
        return original(w, features, force)

    shapeFragWord._no_optional_ligatures = True
    module.shapeFragWord = shapeFragWord


def _disable_latin_ligatures() -> None:
    """Shape without the font's Latin ligatures.

    Mukta replaces ff/fi/fl and ct/st pairs with single glyphs, which reads
    oddly inside an English sentence and extracts as U+FB00-style codes.
    Devanagari shaping is unchanged: with the features off the same conjunct
    glyphs are produced.
    """
    from reportlab.pdfbase import ttfonts
    from reportlab.platypus import paragraph
    # paragraph imports the function directly, so both bindings need the
    # wrapper; shapeStr inside ttfonts resolves its global at call time.
    _patch_ligature_default(paragraph)
    _patch_ligature_default(ttfonts)


@lru_cache(maxsize=1)
def register() -> None:
    pdfmetrics.registerFont(TTFont(FONT, str(FONT_DIR / "Mukta-Regular.ttf"),
                                   shapable=True))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(FONT_DIR / "Mukta-Bold.ttf"),
                                   shapable=True))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_BOLD,
                                  italic=FONT, boldItalic=FONT_BOLD)
    _disable_latin_ligatures()


@lru_cache(maxsize=None)
def style(name: str, size: float | None = None) -> ParagraphStyle:
    """A sample-sheet style re-set in Mukta and shaped.

    The bold sample styles keep their weight; everything else uses the regular
    face. ``size`` overrides the sample size where a table cell needs it.
    """
    register()
    base = getSampleStyleSheet()[name]
    settings = {"fontName": FONT_BOLD if "Bold" in base.fontName else FONT,
                "shaping": 1}
    if size is not None:
        settings["fontSize"] = size
    return ParagraphStyle(f"mukta-{name}-{size or base.fontSize}", parent=base,
                          **settings)


def cell_style(size: float = 8, bold: bool = False, align: int = 0) -> ParagraphStyle:
    """A compact style for table cells: shaped, wrapped, no added spacing."""
    register()
    return ParagraphStyle(f"mukta-cell-{bold}-{align}-{size}",
                          parent=getSampleStyleSheet()["Normal"],
                          fontName=FONT_BOLD if bold else FONT, fontSize=size,
                          leading=size * 1.3, shaping=1, alignment=align)


class ShapedCanvas(Canvas):
    """A canvas that sets every string in Mukta and shapes it.

    Helvetica names are mapped to the Mukta faces so existing drawing code
    keeps working, and the three draw methods pass ``direction``/``shaping``
    so Devanagari is rendered by harfbuzz rather than code point by code point.
    """

    def setFont(self, psfontname, size, leading=None):
        register()
        return super().setFont(_ALIASES.get(psfontname, psfontname), size, leading)

    def drawString(self, x, y, text, **kwargs):
        kwargs.setdefault("direction", "LTR")
        kwargs.setdefault("shaping", True)
        return super().drawString(x, y, text, **kwargs)

    def drawRightString(self, x, y, text, **kwargs):
        kwargs.setdefault("direction", "LTR")
        kwargs.setdefault("shaping", True)
        return super().drawRightString(x, y, text, **kwargs)

    def drawCentredString(self, x, y, text, **kwargs):
        kwargs.setdefault("direction", "LTR")
        kwargs.setdefault("shaping", True)
        return super().drawCentredString(x, y, text, **kwargs)
