from pathlib import Path

from pypdf import PdfReader

from app.services.certificates import (
    format_issue_date,
    generate_certificate_pdf,
    validate_text_characters,
)


def test_pdf_generation_and_text_extraction(tmp_path: Path):
    output_pdf = tmp_path / "cert_test.pdf"

    generate_certificate_pdf(
        recipient_name="Diya Rao",
        event_name="Advanced Python Architecture",
        issuer_name="Global Tech University",
        issue_date="2026-10-11",
        certificate_id="CERT-TEST-9988",
        output_path=output_pdf,
    )

    assert output_pdf.exists()
    assert output_pdf.stat().st_size > 5000

    # Ensure no lingering temporary files
    temp_files = list(tmp_path.glob(".tmp_*"))
    assert len(temp_files) == 0

    # Read and inspect PDF text content
    reader = PdfReader(str(output_pdf))
    assert len(reader.pages) == 1
    page_text = reader.pages[0].extract_text()

    assert "CERTIFICATE" in page_text
    assert "OF COMPLETION" in page_text
    assert "This certificate is proudly presented to" in page_text
    assert "Diya Rao" in page_text
    assert "For successfully completing" in page_text
    assert "Advanced Python Architecture" in page_text
    assert "GLOBAL TECH UNIVERSITY" in page_text
    assert "October 11, 2026" in page_text
    assert "CERT-TEST-9988" in page_text


def test_long_names_and_multiline_event_titles(tmp_path: Path):
    output_pdf = tmp_path / "cert_long.pdf"

    very_long_name = "Alexander Constantine Montgomery-Wellington III of Cambridge"
    very_long_event = (
        "Comprehensive Distributed Systems Architecture and High-Performance Cloud "
        "Engineering Intensive Specialization 2026"
    )

    generate_certificate_pdf(
        recipient_name=very_long_name,
        event_name=very_long_event,
        issuer_name="International Institute of Advanced Software Engineering",
        issue_date="2026-10-15",
        certificate_id="CERT-LONG-001",
        output_path=output_pdf,
    )

    assert output_pdf.exists()
    reader = PdfReader(str(output_pdf))
    text = reader.pages[0].extract_text()
    assert "Alexander Constantine" in text
    assert "Distributed Systems Architecture" in text


def test_supported_unicode_characters(tmp_path: Path):
    output_pdf = tmp_path / "cert_unicode.pdf"

    unicode_name = "José García-Núñez Åsa Müller"
    generate_certificate_pdf(
        recipient_name=unicode_name,
        event_name="Modern Web Engineering",
        issuer_name="European Tech Academy",
        issue_date="2026-10-11",
        certificate_id="CERT-UNI-001",
        output_path=output_pdf,
    )

    assert output_pdf.exists()
    reader = PdfReader(str(output_pdf))
    text = reader.pages[0].extract_text()
    assert "José García-Núñez" in text or "García" in text


def test_unsupported_glyph_detection():
    # Egyptian Hieroglyph or unsupported symbol
    unsupported_string = "User Name \U00013000"
    is_valid, err = validate_text_characters(unsupported_string)
    assert is_valid is False
    assert "unsupported character glyphs" in err

    # Valid string
    valid_string = "Aarav Sharma - Special Edition"
    is_valid, err = validate_text_characters(valid_string)
    assert is_valid is True
    assert err is None


def test_format_issue_date():
    assert format_issue_date("2026-10-11") == "October 11, 2026"
    assert format_issue_date("2026-01-01") == "January 01, 2026"
    # Fallback for unexpected format
    assert format_issue_date("InvalidDate") == "InvalidDate"
