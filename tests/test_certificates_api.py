import uuid

from app.config import settings
from app.models import Job, JobStatus, Recipient, RecipientStatus, utc_now
from app.services.certificates import generate_certificate_pdf


def test_download_valid_certificate(client, db_session, temp_storage):
    # Setup job and completed recipient in database
    job = Job(
        id=str(uuid.uuid4()),
        event_name="FastAPI Masterclass",
        issuer_name="Python Academy",
        issue_date="2026-10-11",
        status=JobStatus.COMPLETED.value,
        created_at=utc_now(),
    )
    db_session.add(job)

    cert_id = "CERT-VALID-001"
    pdf_rel_path = f"certificates/{cert_id}.pdf"
    full_pdf_path = settings.storage_dir / pdf_rel_path

    # Generate actual PDF file
    generate_certificate_pdf(
        recipient_name="Diya Rao",
        event_name=job.event_name,
        issuer_name=job.issuer_name,
        issue_date=job.issue_date,
        certificate_id=cert_id,
        output_path=full_pdf_path,
    )

    recipient = Recipient(
        id=str(uuid.uuid4()),
        job_id=job.id,
        input_index=0,
        raw_name="Diya Rao",
        raw_email="diya@example.com",
        normalized_email="diya@example.com",
        status=RecipientStatus.COMPLETED.value,
        certificate_id=cert_id,
        relative_pdf_path=pdf_rel_path,
        created_at=utc_now(),
        updated_at=utc_now(),
        processed_at=utc_now(),
    )
    db_session.add(recipient)
    db_session.commit()

    # Download request
    response = client.get(f"/api/v1/certificates/{cert_id}/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert f'filename="certificate_{cert_id}.pdf"' in response.headers["content-disposition"]
    assert len(response.content) > 1000
    assert response.content.startswith(b"%PDF")


def test_download_unknown_certificate(client):
    response = client.get("/api/v1/certificates/CERT-NONEXISTENT/download")
    assert response.status_code == 404
    assert "was not found" in response.json()["detail"]


def test_download_pending_or_processing_certificate_returns_409(client, db_session):
    job = Job(
        id=str(uuid.uuid4()),
        event_name="Event",
        issuer_name="Academy",
        issue_date="2026-10-11",
        status=JobStatus.PROCESSING.value,
        created_at=utc_now(),
    )
    db_session.add(job)

    cert_id = "CERT-PENDING-001"
    recipient = Recipient(
        id=str(uuid.uuid4()),
        job_id=job.id,
        input_index=0,
        raw_name="Pending User",
        raw_email="pending@example.com",
        status=RecipientStatus.PENDING.value,
        certificate_id=cert_id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(recipient)
    db_session.commit()

    response = client.get(f"/api/v1/certificates/{cert_id}/download")
    assert response.status_code == 409
    assert "currently being generated" in response.json()["detail"]


def test_download_failed_recipient_returns_409(client, db_session):
    job = Job(
        id=str(uuid.uuid4()),
        event_name="Event",
        issuer_name="Academy",
        issue_date="2026-10-11",
        status=JobStatus.FAILED.value,
        created_at=utc_now(),
    )
    db_session.add(job)

    cert_id = "CERT-FAILED-001"
    recipient = Recipient(
        id=str(uuid.uuid4()),
        job_id=job.id,
        input_index=0,
        raw_name="Failed User",
        raw_email="failed@example.com",
        status=RecipientStatus.FAILED.value,
        certificate_id=cert_id,
        error_code="RENDER_ERROR",
        error_message="Simulation failure",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(recipient)
    db_session.commit()

    response = client.get(f"/api/v1/certificates/{cert_id}/download")
    assert response.status_code == 409
    assert "generation failed" in response.json()["detail"]


def test_download_missing_file_on_disk_returns_safe_404(client, db_session, temp_storage):
    job = Job(
        id=str(uuid.uuid4()),
        event_name="Event",
        issuer_name="Academy",
        issue_date="2026-10-11",
        status=JobStatus.COMPLETED.value,
        created_at=utc_now(),
    )
    db_session.add(job)

    cert_id = "CERT-MISSING-FILE"
    # Point to a file that does not exist on disk
    recipient = Recipient(
        id=str(uuid.uuid4()),
        job_id=job.id,
        input_index=0,
        raw_name="Missing File User",
        raw_email="user@example.com",
        status=RecipientStatus.COMPLETED.value,
        certificate_id=cert_id,
        relative_pdf_path="certificates/non_existent.pdf",
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db_session.add(recipient)
    db_session.commit()

    response = client.get(f"/api/v1/certificates/{cert_id}/download")
    assert response.status_code == 404
    assert "missing from local storage" in response.json()["detail"]


def test_preview_certificate_endpoint(client):
    response = client.get(
        "/api/v1/certificates/preview?recipient_name=Sample+Student&event_name=Workshop&issuer_name=Academy"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert len(response.content) > 5000
