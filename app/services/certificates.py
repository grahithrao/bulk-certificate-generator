import io
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from app.config import settings

# Global flag to track font registration and cached character maps
_FONTS_REGISTERED = False
_GLYPH_MAP_SANS = None
_GLYPH_MAP_SERIF = None


def init_fonts(fonts_dir: Optional[Path] = None) -> None:
    """Register TrueType fonts for serif and sans-serif typography with Unicode coverage."""
    global _FONTS_REGISTERED, _GLYPH_MAP_SANS, _GLYPH_MAP_SERIF
    if _FONTS_REGISTERED:
        return

    f_dir = fonts_dir or settings.fonts_dir
    sans_reg_path = f_dir / "DejaVuSans.ttf"
    sans_bold_path = f_dir / "DejaVuSans-Bold.ttf"
    serif_reg_path = f_dir / "DejaVuSerif.ttf"
    serif_bold_path = f_dir / "DejaVuSerif-Bold.ttf"

    for path in (sans_reg_path, sans_bold_path, serif_reg_path, serif_bold_path):
        if not path.exists():
            raise FileNotFoundError(
                f"Required TrueType font not found at {path}. "
                "Please ensure DejaVuSans.ttf, DejaVuSans-Bold.ttf, "
                "DejaVuSerif.ttf, and DejaVuSerif-Bold.ttf exist."
            )

    sans_reg = TTFont("DejaVuSans", str(sans_reg_path))
    sans_bold = TTFont("DejaVuSans-Bold", str(sans_bold_path))
    serif_reg = TTFont("DejaVuSerif", str(serif_reg_path))
    serif_bold = TTFont("DejaVuSerif-Bold", str(serif_bold_path))

    pdfmetrics.registerFont(sans_reg)
    pdfmetrics.registerFont(sans_bold)
    pdfmetrics.registerFont(serif_reg)
    pdfmetrics.registerFont(serif_bold)

    _GLYPH_MAP_SANS = sans_reg.face.charToGlyph
    _GLYPH_MAP_SERIF = serif_reg.face.charToGlyph
    _FONTS_REGISTERED = True


def validate_text_characters(text: str) -> Tuple[bool, Optional[str]]:
    """
    Check if all characters in the text are supported by the embedded fonts.
    Returns (True, None) if supported, or (False, error_description) if unsupported.
    """
    if not _FONTS_REGISTERED:
        init_fonts()

    unsupported: List[str] = []
    for char in text:
        # Standard whitespaces are always allowed
        if char in (" ", "\t", "\n", "\r"):
            continue
        code_point = ord(char)
        glyph_sans = _GLYPH_MAP_SANS.get(code_point, 0) if _GLYPH_MAP_SANS else 1
        glyph_serif = _GLYPH_MAP_SERIF.get(code_point, 0) if _GLYPH_MAP_SERIF else 1
        if glyph_sans == 0 or glyph_serif == 0:
            unsupported.append(char)

    if unsupported:
        unique_chars = sorted(set(unsupported))
        escaped_repr = ", ".join(repr(c) for c in unique_chars[:5])
        return False, f"Text contains unsupported character glyphs: {escaped_repr}"

    return True, None


def format_issue_date(date_str: str) -> str:
    """Format ISO date YYYY-MM-DD into a human-readable certificate date string."""
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return dt.strftime("%B %d, %Y")
    except Exception:
        return date_str.strip()


def _draw_centered_text(c: canvas.Canvas, text: str, font_name: str, font_size: float, y: float) -> None:
    c.setFont(font_name, font_size)
    c.drawCentredString(841.89 / 2.0, y, text)


def _draw_fitted_text(
    c: canvas.Canvas,
    text: str,
    font_name: str,
    initial_font_size: float,
    min_font_size: float,
    max_width: float,
    y: float,
) -> float:
    """
    Dynamically scale font size down to fit within max_width without clipping or overlap.
    Returns the font size used.
    """
    size = initial_font_size
    while size > min_font_size:
        width = c.stringWidth(text, font_name, size)
        if width <= max_width:
            break
        size -= 0.5

    c.setFont(font_name, size)
    c.drawCentredString(841.89 / 2.0, y, text)
    return size


def _wrap_text_to_lines(c: canvas.Canvas, text: str, font_name: str, font_size: float, max_width: float) -> List[str]:
    """Split text into wrapped lines that each fit within max_width."""
    words = text.split()
    if not words:
        return [""]

    lines: List[str] = []
    current_line = words[0]

    for word in words[1:]:
        test_line = f"{current_line} {word}"
        if c.stringWidth(test_line, font_name, font_size) <= max_width:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word
    lines.append(current_line)
    return lines


def _draw_certificate_canvas(
    c: canvas.Canvas,
    recipient_name: str,
    event_name: str,
    issuer_name: str,
    issue_date: str,
    certificate_id: str,
) -> None:
    """
    Draw the refined, print-ready A4 landscape certificate.
    Design:
    - Pure white background with deep navy typography (#0F172A).
    - Restrained muted gold accents (#B89B5E).
    - Fine double-line border with geometric corner details.
    - Serif font (DejaVuSerif-Bold) for recipient name and main heading.
    - Sans-serif font (DejaVuSans) for metadata and supporting text.
    - No fake signatures, seals, or logos.
    """
    page_width, page_height = landscape(A4)  # 841.89 x 595.27 points
    center_x = page_width / 2.0

    c.setTitle(f"Certificate - {recipient_name}")
    c.setAuthor(issuer_name)
    c.setSubject(event_name)

    # 1. Background (Pure Crisp White)
    c.setFillColor(colors.HexColor("#FFFFFF"))
    c.rect(0, 0, page_width, page_height, fill=1, stroke=0)

    # 2. Fine Double-Line Border with Geometric Accents
    # Outer frame: Deep Navy (#0F172A)
    c.setStrokeColor(colors.HexColor("#0F172A"))
    c.setLineWidth(1.2)
    c.rect(36, 36, page_width - 72, page_height - 72, fill=0, stroke=1)

    # Inner frame: Restrained Muted Gold (#B89B5E)
    c.setStrokeColor(colors.HexColor("#B89B5E"))
    c.setLineWidth(0.6)
    c.rect(42, 42, page_width - 84, page_height - 84, fill=0, stroke=1)

    # Subtle geometric corner marks
    c.setStrokeColor(colors.HexColor("#B89B5E"))
    c.setLineWidth(0.8)
    corner_size = 12
    for x_origin, y_origin, x_dir, y_dir in [
        (42, 42, 1, 1),
        (page_width - 42, 42, -1, 1),
        (42, page_height - 42, 1, -1),
        (page_width - 42, page_height - 42, -1, -1),
    ]:
        c.line(x_origin, y_origin, x_origin + (x_dir * corner_size), y_origin)
        c.line(x_origin, y_origin, x_origin, y_origin + (y_dir * corner_size))

    # -------------------------------------------------------------
    # 3. Content Hierarchy (from top to bottom)
    # -------------------------------------------------------------

    # Hierarchy 1: Issuer name at the top
    c.setFillColor(colors.HexColor("#475569"))
    _draw_fitted_text(
        c,
        text=issuer_name.upper(),
        font_name="DejaVuSans-Bold",
        initial_font_size=11.0,
        min_font_size=9.0,
        max_width=600.0,
        y=512,
    )

    # Hierarchy 2: "CERTIFICATE" as the main heading (Serif)
    c.setFillColor(colors.HexColor("#0F172A"))
    _draw_centered_text(c, "CERTIFICATE", "DejaVuSerif-Bold", 34.0, 458)

    # Hierarchy 3: "OF COMPLETION" as a smaller, letter-spaced subtitle
    c.setFillColor(colors.HexColor("#B89B5E"))
    _draw_centered_text(c, "OF COMPLETION", "DejaVuSans-Bold", 10.0, 432)

    # Hierarchy 4: "This certificate is proudly presented to"
    c.setFillColor(colors.HexColor("#475569"))
    _draw_centered_text(c, "This certificate is proudly presented to", "DejaVuSans", 11.5, 382)

    # Hierarchy 5: Recipient's full name as the visual focal point (Serif)
    c.setFillColor(colors.HexColor("#0F172A"))
    _draw_fitted_text(
        c,
        text=recipient_name,
        font_name="DejaVuSerif-Bold",
        initial_font_size=32.0,
        min_font_size=18.0,
        max_width=620.0,
        y=324,
    )

    # Restrained gold underline below recipient name
    c.setStrokeColor(colors.HexColor("#B89B5E"))
    c.setLineWidth(0.75)
    c.line(center_x - 130, 310, center_x + 130, 310)

    # Hierarchy 6: "For successfully completing"
    c.setFillColor(colors.HexColor("#475569"))
    _draw_centered_text(c, "For successfully completing", "DejaVuSans", 11.5, 268)

    # Hierarchy 7: Event or course name
    c.setFillColor(colors.HexColor("#0F172A"))
    event_lines = _wrap_text_to_lines(
        c,
        event_name,
        "DejaVuSans-Bold",
        font_size=18.0,
        max_width=620.0,
    )
    if len(event_lines) == 1:
        _draw_centered_text(c, event_lines[0], "DejaVuSans-Bold", 18.0, 222)
    else:
        line_y = 232
        for line in event_lines[:2]:
            _draw_centered_text(c, line, "DejaVuSans-Bold", 16.0, line_y)
            line_y -= 22

    # -------------------------------------------------------------
    # 4. Balanced Footer (Issue Date & Certificate ID)
    # -------------------------------------------------------------
    # Subtle horizontal divider rule
    c.setStrokeColor(colors.HexColor("#E2E8F0"))
    c.setLineWidth(0.6)
    c.line(54, 95, page_width - 54, 95)

    # Left Column: Date of Issuance
    c.setFillColor(colors.HexColor("#64748B"))
    c.setFont("DejaVuSans-Bold", 8.0)
    c.drawString(70, 80, "DATE OF ISSUANCE")

    formatted_date = format_issue_date(issue_date)
    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("DejaVuSans-Bold", 11.0)
    c.drawString(70, 64, formatted_date)

    # Right Column: Certificate ID
    c.setFillColor(colors.HexColor("#64748B"))
    c.setFont("DejaVuSans-Bold", 8.0)
    c.drawRightString(page_width - 70, 80, "CERTIFICATE ID")

    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("DejaVuSans", 10.5)
    c.drawRightString(page_width - 70, 64, certificate_id)

    c.showPage()


def render_certificate_pdf_bytes(
    recipient_name: str,
    event_name: str,
    issuer_name: str,
    issue_date: str,
    certificate_id: str,
) -> bytes:
    """Render a certificate directly to an in-memory byte buffer (used for live previews)."""
    init_fonts()

    for field_val, field_name in [
        (recipient_name, "recipient name"),
        (event_name, "event name"),
        (issuer_name, "issuer name"),
    ]:
        ok, err = validate_text_characters(field_val)
        if not ok:
            raise ValueError(f"Invalid {field_name}: {err}")

    buffer = io.BytesIO()
    page_width, page_height = landscape(A4)
    c = canvas.Canvas(buffer, pagesize=(page_width, page_height))
    _draw_certificate_canvas(c, recipient_name, event_name, issuer_name, issue_date, certificate_id)
    c.save()
    return buffer.getvalue()


def generate_certificate_pdf(
    recipient_name: str,
    event_name: str,
    issuer_name: str,
    issue_date: str,
    certificate_id: str,
    output_path: Path,
) -> None:
    """
    Render a professional landscape certificate PDF using ReportLab.
    Uses atomic file writing: renders to a temporary file first, then atomically replaces
    the destination path on completion to prevent partial or corrupted files.
    """
    init_fonts()

    # Pre-render character validation
    for field_val, field_name in [
        (recipient_name, "recipient name"),
        (event_name, "event name"),
        (issuer_name, "issuer name"),
    ]:
        ok, err = validate_text_characters(field_val)
        if not ok:
            raise ValueError(f"Invalid {field_name}: {err}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = output_path.with_name(f".tmp_{output_path.name}")

    try:
        page_width, page_height = landscape(A4)  # 841.89 x 595.27 points
        c = canvas.Canvas(str(temp_file), pagesize=(page_width, page_height))
        _draw_certificate_canvas(c, recipient_name, event_name, issuer_name, issue_date, certificate_id)
        c.save()

        # Atomically replace final file
        os.replace(temp_file, output_path)

    except Exception as e:
        # Clean up temporary file on failure
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass
        raise e
