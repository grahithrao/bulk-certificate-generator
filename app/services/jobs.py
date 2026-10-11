import math
import uuid
from typing import Any

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Job, JobStatus, Recipient, RecipientStatus, utc_now
from app.schemas import JobCreateRequest
from app.services.certificates import validate_text_characters


def _contains_control_characters(s: str) -> bool:
    """Check if string contains ASCII control characters (0-31 or 127) excluding standard spaces."""
    return any(ord(c) < 32 or ord(c) == 127 for c in s)


def validate_and_create_job(
    db: Session,
    request_data: JobCreateRequest,
) -> tuple[Job, int, int, bool]:
    """
    Validates each recipient in the batch independently, persists the Job
    and all Recipient records (including diagnostic entries for malformed recipients),
    and determines whether the job is queued (mixed/valid) or immediately failed (all-invalid).

    Returns:
        (job, accepted_count, rejected_count, is_all_invalid)
    """
    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        event_name=request_data.event_name,
        issuer_name=request_data.issuer_name,
        issue_date=request_data.issue_date,
        created_at=utc_now(),
    )
    db.add(job)
    db.flush()  # Ensures job.id exists for foreign key references

    recipients_to_insert: list[Recipient] = []
    seen_emails: dict[str, int] = {}  # normalized_email -> first input_index
    accepted_count = 0
    rejected_count = 0

    for idx, raw_entry in enumerate(request_data.recipients):
        recipient_id = str(uuid.uuid4())

        # 1. Check if recipient entry is a dictionary
        if not isinstance(raw_entry, dict):
            rejected_count += 1
            rec = Recipient(
                id=recipient_id,
                job_id=job.id,
                input_index=idx,
                raw_name=None,
                raw_email=None,
                normalized_email=None,
                status=RecipientStatus.FAILED.value,
                error_code="INVALID_PAYLOAD",
                error_message="Recipient item must be a JSON object containing 'name' and 'email'",
                created_at=utc_now(),
                updated_at=utc_now(),
                processed_at=utc_now(),
            )
            recipients_to_insert.append(rec)
            continue

        raw_name_val = raw_entry.get("name")
        raw_email_val = raw_entry.get("email")

        # 2. Validate Name
        name_err_code: str | None = None
        name_err_msg: str | None = None

        if raw_name_val is None or not isinstance(raw_name_val, str):
            name_err_code = "INVALID_NAME"
            name_err_msg = "Recipient name is required and must be a string"
        elif not raw_name_val.strip():
            name_err_code = "INVALID_NAME"
            name_err_msg = "Recipient name cannot be empty or blank"
        elif len(raw_name_val.strip()) > 200:
            name_err_code = "NAME_TOO_LONG"
            name_err_msg = "Recipient name exceeds maximum allowed length of 200 characters"
        elif _contains_control_characters(raw_name_val):
            name_err_code = "INVALID_CHARACTERS"
            name_err_msg = "Recipient name contains forbidden control characters"
        else:
            # Check font glyph support
            is_valid_chars, char_err = validate_text_characters(raw_name_val.strip())
            if not is_valid_chars:
                name_err_code = "UNSUPPORTED_CHARACTERS"
                name_err_msg = char_err

        # 3. Validate Email
        email_err_code: str | None = None
        email_err_msg: str | None = None
        normalized_email: str | None = None

        if raw_email_val is None or not isinstance(raw_email_val, str):
            email_err_code = "INVALID_EMAIL"
            email_err_msg = "Recipient email is required and must be a string"
        elif not raw_email_val.strip():
            email_err_code = "INVALID_EMAIL"
            email_err_msg = "Recipient email cannot be empty or blank"
        elif len(raw_email_val.strip()) > 255:
            email_err_code = "EMAIL_TOO_LONG"
            email_err_msg = "Recipient email exceeds maximum allowed length of 255 characters"
        elif _contains_control_characters(raw_email_val):
            email_err_code = "INVALID_CHARACTERS"
            email_err_msg = "Recipient email contains forbidden control characters"
        else:
            try:
                parsed_email = validate_email(raw_email_val.strip(), check_deliverability=False)
                normalized_email = parsed_email.normalized.lower()
            except EmailNotValidError as e:
                email_err_code = "INVALID_EMAIL"
                email_err_msg = f"Invalid email format: {e!s}"

        # 4. Check Duplicate Recipient within Batch
        dup_err_code: str | None = None
        dup_err_msg: str | None = None

        if not name_err_code and not email_err_code and normalized_email:
            if normalized_email in seen_emails:
                first_seen = seen_emails[normalized_email]
                dup_err_code = "DUPLICATE_RECIPIENT"
                dup_err_msg = (
                    f"Duplicate recipient email in batch: '{normalized_email}' "
                    f"was already registered at input index {first_seen}"
                )
            else:
                seen_emails[normalized_email] = idx

        # 5. Determine Outcome for this Recipient
        final_err_code = name_err_code or email_err_code or dup_err_code
        final_err_msg = name_err_msg or email_err_msg or dup_err_msg

        name_str = str(raw_name_val).strip() if isinstance(raw_name_val, str) else None
        email_str = str(raw_email_val).strip() if isinstance(raw_email_val, str) else None

        if final_err_code:
            rejected_count += 1
            rec = Recipient(
                id=recipient_id,
                job_id=job.id,
                input_index=idx,
                raw_name=name_str,
                raw_email=email_str,
                normalized_email=normalized_email,
                status=RecipientStatus.FAILED.value,
                error_code=final_err_code,
                error_message=final_err_msg,
                created_at=utc_now(),
                updated_at=utc_now(),
                processed_at=utc_now(),
            )
        else:
            accepted_count += 1
            # Unique stable certificate ID generated upfront
            cert_id = f"CERT-{uuid.uuid4().hex[:12].upper()}"
            rec = Recipient(
                id=recipient_id,
                job_id=job.id,
                input_index=idx,
                raw_name=name_str,
                raw_email=email_str,
                normalized_email=normalized_email,
                status=RecipientStatus.PENDING.value,
                certificate_id=cert_id,
                created_at=utc_now(),
                updated_at=utc_now(),
            )

        recipients_to_insert.append(rec)

    # Batch-add recipients
    db.add_all(recipients_to_insert)

    # Determine Job status
    is_all_invalid = (accepted_count == 0)
    now = utc_now()
    if is_all_invalid:
        job.status = JobStatus.FAILED.value
        job.started_at = now
        job.finished_at = now
    else:
        job.status = JobStatus.QUEUED.value

    db.commit()
    db.refresh(job)

    return job, accepted_count, rejected_count, is_all_invalid


def get_job_counters(db: Session, job_id: str) -> dict[str, Any]:
    """
    Derive accurate progress and status counters from recipient records.
    Avoids fragile duplicate counters.
    """
    counts = (
        db.query(
            Recipient.status,
            func.count(Recipient.id),
        )
        .filter(Recipient.job_id == job_id)
        .group_by(Recipient.status)
        .all()
    )

    status_map = {status: count for status, count in counts}

    completed = status_map.get(RecipientStatus.COMPLETED.value, 0)
    failed = status_map.get(RecipientStatus.FAILED.value, 0)
    pending = status_map.get(RecipientStatus.PENDING.value, 0)
    processing = status_map.get(RecipientStatus.PROCESSING.value, 0)

    total = completed + failed + pending + processing
    processed = completed + failed
    remaining = pending + processing

    progress_percent = round((processed / total * 100.0), 2) if total > 0 else 0.0

    return {
        "total": total,
        "processed": processed,
        "completed": completed,
        "failed": failed,
        "pending": pending,
        "processing": processing,
        "remaining": remaining,
        "progress_percent": progress_percent,
    }


def get_job_by_id(db: Session, job_id: str) -> Job | None:
    """Retrieve job by primary key."""
    return db.query(Job).filter(Job.id == job_id).first()


def get_paginated_recipients(
    db: Session,
    job_id: str,
    page: int = 1,
    page_size: int = 50,
    status_filter: str | None = None,
) -> tuple[list[Recipient], int, int]:
    """
    Retrieve paginated recipient outcomes for a job.
    Returns: (items, total_matching, total_pages)
    """
    query = db.query(Recipient).filter(Recipient.job_id == job_id)

    if status_filter:
        query = query.filter(Recipient.status == status_filter)

    total_count = query.count()
    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1

    items = (
        query.order_by(Recipient.input_index.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return items, total_count, total_pages


def get_recipient_by_certificate_id(db: Session, certificate_id: str) -> Recipient | None:
    """Retrieve recipient record associated with a certificate identifier."""
    return db.query(Recipient).filter(Recipient.certificate_id == certificate_id).first()
