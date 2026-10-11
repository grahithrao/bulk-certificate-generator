import fcntl
import logging
import os
import sys
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, init_db
from app.models import Job, JobStatus, Recipient, RecipientStatus, utc_now
from app.services.certificates import generate_certificate_pdf
from app.services.jobs import get_job_counters

# Structured logger setup (no PII in log records)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [worker] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("worker")


class SingleWorkerLock:
    """
    OS-level advisory file lock to enforce the single-worker guarantee.
    Prevents race conditions, duplicate processing, and SQLite concurrency errors
    arising from multiple worker instances running against the same database.
    """

    def __init__(self, lock_file_path: Path):
        self.lock_file_path = lock_file_path
        self._fd: int | None = None

    def acquire(self) -> bool:
        self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(str(self.lock_file_path), os.O_CREAT | os.O_RDWR)
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (OSError, BlockingIOError):
            return False

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None


def recover_interrupted_work(db: Session) -> int:
    """
    Restart recovery policy for single-worker execution:
    1. Identify any recipients interrupted mid-processing and reset to 'pending'.
    2. Identify interrupted jobs in 'processing' and reset to 'queued'.
    3. Preserve all already 'completed' recipients and their generated certificates.
    4. Preserve all already 'failed' recipients.
    Returns the count of recovered recipients.
    """
    # 1. Reset interrupted recipients
    interrupted_recipients = (
        db.query(Recipient)
        .filter(Recipient.status == RecipientStatus.PROCESSING.value)
        .all()
    )
    recovered_count = len(interrupted_recipients)
    now = utc_now()
    for rec in interrupted_recipients:
        rec.status = RecipientStatus.PENDING.value
        rec.updated_at = now

    # 2. Reset interrupted jobs that have remaining pending work
    interrupted_jobs = (
        db.query(Job)
        .filter(Job.status == JobStatus.PROCESSING.value)
        .all()
    )
    for job in interrupted_jobs:
        job.status = JobStatus.QUEUED.value

    if recovered_count > 0 or interrupted_jobs:
        db.commit()
        logger.info(
            f"Restart recovery complete: recovered {recovered_count} interrupted recipient(s) "
            f"across {len(interrupted_jobs)} job(s)."
        )

    return recovered_count


def _finalize_job_status(db: Session, job: Job) -> str:
    """
    Compute and assign the terminal job status once all recipients are processed.
    Terminal status rules:
    - All completed -> 'completed'
    - Some completed, some failed -> 'completed_with_errors'
    - Zero completed -> 'failed'
    """
    counters = get_job_counters(db, job.id)
    completed = counters["completed"]
    failed = counters["failed"]
    total = counters["total"]

    if completed == total:
        terminal_status = JobStatus.COMPLETED.value
    elif completed > 0 and failed > 0:
        terminal_status = JobStatus.COMPLETED_WITH_ERRORS.value
    else:
        terminal_status = JobStatus.FAILED.value

    job.status = terminal_status
    job.finished_at = utc_now()
    db.commit()
    db.refresh(job)

    logger.info(
        f"Job {job.id} finalized with terminal status '{terminal_status}'. "
        f"Completed: {completed}/{total}, Failed: {failed}/{total}."
    )
    return terminal_status


def process_one_recipient(
    db: Session,
    recipient: Recipient,
    job: Job,
) -> bool:
    """
    Process a single recipient independently:
    1. Short DB transaction to mark as 'processing'.
    2. Render PDF outside the DB transaction.
    3. Short DB transaction to mark outcome as 'completed' or 'failed'.
    """
    recipient_id = recipient.id
    cert_id = recipient.certificate_id or f"CERT-{recipient_id[:8].upper()}"
    filename = f"{cert_id}.pdf"
    rel_path = f"certificates/{filename}"
    dest_path = settings.certificates_dir / filename

    # Step 1: Claim recipient in short transaction
    recipient.status = RecipientStatus.PROCESSING.value
    recipient.updated_at = utc_now()
    db.commit()

    # Step 2: Render PDF outside of any DB write transaction
    render_error = None
    try:
        # Check if already generated (e.g. from a prior run)
        if not dest_path.exists() or dest_path.stat().st_size == 0:
            generate_certificate_pdf(
                recipient_name=recipient.raw_name or "Recipient",
                event_name=job.event_name,
                issuer_name=job.issuer_name,
                issue_date=job.issue_date,
                certificate_id=cert_id,
                output_path=dest_path,
            )
    except Exception as e:
        render_error = f"PDF generation failed: {type(e).__name__} - {e!s}"
        logger.warning(
            f"Failed rendering certificate for job={job.id} recipient={recipient_id}: {type(e).__name__}"
        )

    # Step 3: Record outcome in short transaction
    now = utc_now()
    if render_error is None:
        recipient.status = RecipientStatus.COMPLETED.value
        recipient.relative_pdf_path = rel_path
        recipient.error_code = None
        recipient.error_message = None
        recipient.processed_at = now
        recipient.updated_at = now
        db.commit()
        return True
    else:
        recipient.status = RecipientStatus.FAILED.value
        recipient.error_code = "RENDER_ERROR"
        recipient.error_message = render_error
        recipient.processed_at = now
        recipient.updated_at = now
        db.commit()
        return False


def process_next_batch(db: Session) -> bool:
    """
    Finds the next job with pending work and processes a bounded batch of recipients.
    Returns True if work was done, False if no work was available.
    """
    # Find next queued or processing job that has pending recipients
    pending_recipient = (
        db.query(Recipient)
        .join(Job, Recipient.job_id == Job.id)
        .filter(
            Job.status.in_([JobStatus.QUEUED.value, JobStatus.PROCESSING.value]),
            Recipient.status == RecipientStatus.PENDING.value,
        )
        .order_by(Job.created_at.asc(), Recipient.input_index.asc())
        .first()
    )

    if not pending_recipient:
        # Check if there are any jobs currently in 'processing' that need terminal status calculation
        unfinalized_job = (
            db.query(Job)
            .filter(Job.status.in_([JobStatus.PROCESSING.value, JobStatus.QUEUED.value]))
            .first()
        )
        if unfinalized_job:
            counters = get_job_counters(db, unfinalized_job.id)
            if counters["remaining"] == 0 and counters["total"] > 0:
                _finalize_job_status(db, unfinalized_job)
                return True
        return False

    job = pending_recipient.job

    # Transition job to 'processing' if currently queued
    if job.status == JobStatus.QUEUED.value:
        job.status = JobStatus.PROCESSING.value
        if job.started_at is None:
            job.started_at = utc_now()
        db.commit()
        logger.info(f"Started processing job {job.id} for event '{job.event_name}'.")

    # Fetch a bounded batch of pending recipients for this job
    batch = (
        db.query(Recipient)
        .filter(
            Recipient.job_id == job.id,
            Recipient.status == RecipientStatus.PENDING.value,
        )
        .order_by(Recipient.input_index.asc())
        .limit(settings.worker_batch_size)
        .all()
    )

    for recipient in batch:
        process_one_recipient(db, recipient, job)

    # Check if this job has completed all recipients
    counters = get_job_counters(db, job.id)
    if counters["remaining"] == 0:
        _finalize_job_status(db, job)

    return True


def run_worker_loop(single_iteration: bool = False, max_iterations: int | None = None) -> None:
    """
    Main worker loop. Runs continuously until interrupted, or for a fixed number of iterations.
    Guarded by the SingleWorkerLock.
    """
    settings.ensure_directories()
    init_db()

    lock_file = settings.storage_dir / ".worker.lock"
    worker_lock = SingleWorkerLock(lock_file)

    if not worker_lock.acquire():
        logger.error(
            "Another worker process is currently running or holding the worker lock. "
            "Exiting to prevent concurrent worker execution."
        )
        sys.exit(1)

    logger.info("Worker process initialized and lock acquired.")

    db = SessionLocal()
    try:
        # Perform restart recovery on startup
        recover_interrupted_work(db)

        iterations = 0
        while True:
            try:
                work_done = process_next_batch(db)
                iterations += 1

                if single_iteration:
                    break
                if max_iterations is not None and iterations >= max_iterations:
                    break

                if not work_done:
                    time.sleep(settings.worker_poll_interval)

            except Exception as e:
                logger.error(f"Unexpected error in worker loop iteration: {e}", exc_info=True)
                time.sleep(settings.worker_poll_interval)

    finally:
        db.close()
        worker_lock.release()
        logger.info("Worker process stopped and lock released.")


if __name__ == "__main__":
    run_worker_loop()
