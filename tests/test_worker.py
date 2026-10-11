from unittest.mock import patch

from app.config import settings
from app.models import JobStatus, Recipient, RecipientStatus
from app.schemas import JobCreateRequest
from app.services.jobs import get_job_counters, validate_and_create_job
from app.worker import SingleWorkerLock, process_next_batch


def test_worker_processes_job_to_completed(db_session, temp_storage):
    # Create valid job with 2 recipients
    req = JobCreateRequest(
        event_name="Worker Processing Test",
        issuer_name="Code Academy",
        issue_date="2026-10-11",
        recipients=[
            {"name": "Aarav Sharma", "email": "aarav@example.com"},
            {"name": "Diya Rao", "email": "diya@example.com"},
        ],
    )
    job, accepted, rejected, is_all_invalid = validate_and_create_job(db_session, req)
    assert job.status == JobStatus.QUEUED.value

    # Process next batch
    work_done = process_next_batch(db_session)
    assert work_done is True

    # Refresh job
    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED.value
    assert job.finished_at is not None

    # Check recipient records
    counters = get_job_counters(db_session, job.id)
    assert counters["total"] == 2
    assert counters["completed"] == 2
    assert counters["failed"] == 0
    assert counters["progress_percent"] == 100.0

    # Verify generated PDF files exist on disk
    recipients = db_session.query(Recipient).filter(Recipient.job_id == job.id).all()
    for rec in recipients:
        assert rec.status == RecipientStatus.COMPLETED.value
        assert rec.relative_pdf_path is not None
        pdf_path = settings.storage_dir / rec.relative_pdf_path
        assert pdf_path.exists()
        assert pdf_path.stat().st_size > 1000


def test_injected_rendering_failure_isolates_and_completes_with_errors(db_session, temp_storage):
    # Create job with 2 recipients
    req = JobCreateRequest(
        event_name="Failure Isolation Test",
        issuer_name="Fault Academy",
        issue_date="2026-10-11",
        recipients=[
            {"name": "Success User", "email": "success@example.com"},
            {"name": "Injected Failure User", "email": "fail@example.com"},
        ],
    )
    job, accepted, rejected, is_all_invalid = validate_and_create_job(db_session, req)

    # Mock generate_certificate_pdf so that it fails only when recipient name is "Injected Failure User"
    from app.services import certificates
    orig_generate = certificates.generate_certificate_pdf

    def faulty_generate(recipient_name, *args, **kwargs):
        if recipient_name == "Injected Failure User":
            raise RuntimeError("Injected disk/rendering hardware fault")
        return orig_generate(recipient_name, *args, **kwargs)

    with patch("app.worker.generate_certificate_pdf", side_effect=faulty_generate):
        process_next_batch(db_session)

    db_session.refresh(job)
    # The terminal status must be COMPLETED_WITH_ERRORS!
    assert job.status == JobStatus.COMPLETED_WITH_ERRORS.value

    recipients = (
        db_session.query(Recipient)
        .filter(Recipient.job_id == job.id)
        .order_by(Recipient.input_index.asc())
        .all()
    )

    # First recipient succeeded
    assert recipients[0].status == RecipientStatus.COMPLETED.value
    assert (settings.storage_dir / recipients[0].relative_pdf_path).exists()

    # Second recipient failed safely without crashing the batch
    assert recipients[1].status == RecipientStatus.FAILED.value
    assert recipients[1].error_code == "RENDER_ERROR"
    assert "Injected disk/rendering hardware fault" in recipients[1].error_message


def test_all_failed_generation_results_in_failed_terminal_status(db_session, temp_storage):
    req = JobCreateRequest(
        event_name="All Fail Test",
        issuer_name="Fault Academy",
        issue_date="2026-10-11",
        recipients=[
            {"name": "Fault User 1", "email": "f1@example.com"},
            {"name": "Fault User 2", "email": "f2@example.com"},
        ],
    )
    job, accepted, rejected, is_all_invalid = validate_and_create_job(db_session, req)

    with patch("app.worker.generate_certificate_pdf", side_effect=RuntimeError("Total outage")):
        process_next_batch(db_session)

    db_session.refresh(job)
    assert job.status == JobStatus.FAILED.value
    counters = get_job_counters(db_session, job.id)
    assert counters["completed"] == 0
    assert counters["failed"] == 2
    assert counters["progress_percent"] == 100.0


def test_single_worker_lock(tmp_path):
    lock_file = tmp_path / ".test_worker.lock"
    lock1 = SingleWorkerLock(lock_file)
    lock2 = SingleWorkerLock(lock_file)

    # First acquire succeeds
    assert lock1.acquire() is True

    # Second concurrent acquire on same lock file must fail
    assert lock2.acquire() is False

    # Release first lock
    lock1.release()

    # Now second acquire succeeds
    assert lock2.acquire() is True
    lock2.release()
