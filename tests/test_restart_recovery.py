import time
import uuid

from app.config import settings
from app.models import Job, JobStatus, Recipient, RecipientStatus, utc_now
from app.services.certificates import generate_certificate_pdf
from app.worker import process_next_batch, recover_interrupted_work


def test_restart_recovery_preserves_completed_and_retries_unfinished(db_session, temp_storage):
    # Setup a job that was interrupted while processing
    job = Job(
        id=str(uuid.uuid4()),
        event_name="Crash Recovery Workshop",
        issuer_name="Resilience Institute",
        issue_date="2026-10-11",
        status=JobStatus.PROCESSING.value,
        created_at=utc_now(),
        started_at=utc_now(),
    )
    db_session.add(job)
    db_session.flush()

    # Recipient 1: Already completed before the crash
    cert1_id = "CERT-RECOVERY-COMPLETED"
    pdf1_rel_path = f"certificates/{cert1_id}.pdf"
    pdf1_full_path = settings.storage_dir / pdf1_rel_path
    generate_certificate_pdf(
        recipient_name="Already Completed User",
        event_name=job.event_name,
        issuer_name=job.issuer_name,
        issue_date=job.issue_date,
        certificate_id=cert1_id,
        output_path=pdf1_full_path,
    )
    # Record initial mtime
    initial_mtime = pdf1_full_path.stat().st_mtime

    rec1 = Recipient(
        id=str(uuid.uuid4()),
        job_id=job.id,
        input_index=0,
        raw_name="Already Completed User",
        raw_email="user1@example.com",
        normalized_email="user1@example.com",
        status=RecipientStatus.COMPLETED.value,
        certificate_id=cert1_id,
        relative_pdf_path=pdf1_rel_path,
        created_at=utc_now(),
        updated_at=utc_now(),
        processed_at=utc_now(),
    )

    # Recipient 2: Was actively being processed when worker crashed
    cert2_id = "CERT-RECOVERY-INTERRUPTED"
    rec2 = Recipient(
        id=str(uuid.uuid4()),
        job_id=job.id,
        input_index=1,
        raw_name="Interrupted User",
        raw_email="user2@example.com",
        normalized_email="user2@example.com",
        status=RecipientStatus.PROCESSING.value,  # Left in 'processing' by crash
        certificate_id=cert2_id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    db_session.add_all([rec1, rec2])
    db_session.commit()

    # 1. Run recovery routine
    recovered = recover_interrupted_work(db_session)
    assert recovered == 1

    # Verify rec2 was reset to 'pending'
    db_session.refresh(rec2)
    assert rec2.status == RecipientStatus.PENDING.value

    # Verify rec1 was preserved intact
    db_session.refresh(rec1)
    assert rec1.status == RecipientStatus.COMPLETED.value

    # Verify job was reset to 'queued' so it will be picked up
    db_session.refresh(job)
    assert job.status == JobStatus.QUEUED.value

    # Small pause to ensure filesystem mtime would differ if file were overwritten
    time.sleep(0.05)

    # 2. Run worker batch processing
    work_done = process_next_batch(db_session)
    assert work_done is True

    # 3. Verify final state
    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED.value
    assert job.finished_at is not None

    db_session.refresh(rec2)
    assert rec2.status == RecipientStatus.COMPLETED.value
    pdf2_full_path = settings.storage_dir / rec2.relative_pdf_path
    assert pdf2_full_path.exists()

    # Ensure rec1 was not re-generated (mtime unchanged)
    assert pdf1_full_path.stat().st_mtime == initial_mtime
