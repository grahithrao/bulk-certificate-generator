# Technical Interview & Architecture Guide — Grahith Rao

This guide prepares you to walk through, explain, defend, debug, and modify the **Bulk Certificate Generator** project during senior technical interviews.

---

## 1. End-to-End Request Walkthrough

Here is the exact lifecycle of a request from client submission to PDF download:

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant FastAPI as FastAPI API Server
    participant DB as SQLite DB (WAL Mode)
    participant Worker as Background Worker
    participant Storage as File Storage (PDFs)

    Client->>FastAPI: POST /api/v1/jobs (batch of recipients)
    FastAPI->>FastAPI: Validate Envelope (Pydantic) & Validate Items (Service)
    FastAPI->>DB: Insert Job ('queued') + Insert Recipients ('pending' / 'failed')
    FastAPI-->>Client: HTTP 202 Accepted (job_id, counts, status_url)

    loop Worker Polling
        Worker->>DB: Query for next Job & Batch of 'pending' Recipients
        Worker->>DB: Mark Recipient 'processing' (Short TX)
        Worker->>Storage: Render PDF to .tmp file & os.replace to final path
        alt Render Succeeded
            Worker->>DB: Mark Recipient 'completed', save relative_pdf_path (Short TX)
        else Render Failed
            Worker->>DB: Mark Recipient 'failed', save error_code & message (Short TX)
        end
    end

    Worker->>DB: Finalize Job Status ('completed' / 'completed_with_errors' / 'failed')

    Client->>FastAPI: GET /api/v1/jobs/{job_id}
    FastAPI->>DB: Query aggregated counters
    FastAPI-->>Client: 200 OK (status, progress_percent, counters)

    Client->>FastAPI: GET /api/v1/certificates/{cert_id}/download
    FastAPI->>DB: Query Recipient by cert_id
    FastAPI->>FastAPI: Verify Status == 'completed' & Validate Path Traversal
    FastAPI->>Storage: Stream FileResponse (application/pdf)
    FastAPI-->>Client: 200 OK (PDF Attachment)
```

---

## 2. File-by-File Architecture Breakdown

| File | Purpose & Responsibilities |
| :--- | :--- |
| **`app/main.py`** | Application entry point. Configures FastAPI, lifespan hooks (directories, DB, font init), global 500 error sanitization, route mounts, and the `/health` endpoint. |
| **`app/config.py`** | Central configuration with Pydantic `BaseSettings`. Manages environment variables, directory paths, batch size limits, and worker polling intervals. |
| **`app/database.py`** | SQLite engine and session factory. Configures SQLite connection pragmas: `journal_mode=WAL`, `foreign_keys=ON`, and `busy_timeout=5000`. |
| **`app/models.py`** | SQLAlchemy 2.x declarative models for `Job` and `Recipient`. Defines statuses, indexes, foreign keys, timestamps, and cascade behavior. |
| **`app/schemas.py`** | Pydantic v2 data models for API input/output validation. Contains envelope validation rules and pagination/status response structures. |
| **`app/api/routes.py`** | Versioned HTTP endpoints (`POST /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/recipients`, `GET /certificates/{id}/download`, `GET /certificates/preview`). Maps business outcomes to HTTP status codes. |
| **`app/services/jobs.py`** | Core business logic for job creation, envelope separation, recipient item validation, batch deduplication, and counter calculation. |
| **`app/services/certificates.py`** | PDF rendering engine built on ReportLab. Manages TrueType serif (`DejaVuSerif-Bold`) and sans-serif (`DejaVuSans`) font registration, glyph verification, dynamic font scaling, and atomic file writes. |
| **`app/worker.py`** | Standalone queue worker process. Manages advisory OS file locks (`SingleWorkerLock`), startup restart recovery, batch polling, failure isolation, and terminal state resolution. |
| **`alembic/`** | Database schema migration definitions and environment configuration. |
| **`static/`** | Same-origin frontend demonstration interface (HTML, CSS, JS) with real-time polling and download links. |

---

## 3. Key Architectural Decisions & Rationales

### Why FastAPI?
- Native async capabilities with ASGI (Uvicorn).
- Automatic OpenAPI/Swagger generation with strict Pydantic schemas.
- Lightweight, predictable dependency injection (`Depends(get_db)`).

### Why SQLite with WAL Mode?
- **Zero operational overhead:** Runs out-of-the-box on local developer machines without installing Docker, Redis, or Postgres.
- **Concurrency:** Standard SQLite locks the entire database on write. By enabling **Write-Ahead Logging (`PRAGMA journal_mode=WAL`)**, readers do not block writers and writers do not block readers. Adding `PRAGMA busy_timeout=5000` ensures concurrent transactions wait up to 5 seconds rather than failing immediately.

### Why ReportLab?
- Native Python library generating vector PDFs directly with precise geometric layouts.
- Does not require heavy browser runtimes or headless Chrome (unlike Puppeteer/Weasyprint), keeping memory footprint small and dependencies self-contained.

### Why a Standalone Worker Process Instead of BackgroundTasks or Celery?
- **FastAPI `BackgroundTasks` run in the API process:** If the API crashes or is restarted during deployment, in-flight background tasks in memory are permanently lost. A database-backed job queue guarantees **durability**.
- **Celery + Redis introduces unnecessary complexity:** Requires running Redis, managing broker connection timeouts, serialization overhead, and worker daemon management. A database queue in SQLite/PostgreSQL is simple, auditable, transactionally safe, and self-contained.

---

## 4. Deep-Dive Design Concepts

### Why Return `202 Accepted` vs `201 Created`?
- **`202 Accepted`:** Standard HTTP semantics for asynchronous processing. The server accepted the batch for processing, but certificate rendering has not completed. The client is provided a status URL (`/api/v1/jobs/{job_id}`) to poll.
- **`201 Created` (for all-invalid batches):** When every single recipient in a batch fails validation, the system persists a terminal `failed` job record and all individual recipient diagnostics. Because the diagnostic job resource is completely created and final (no async work remains), `201 Created` is returned with status `"failed"`.

### How Mixed Validation & Envelope Separation Works
If we validated `recipients: list[RecipientItem]` directly in Pydantic, a single typo in row #487 would cause FastAPI to reject the entire 500-recipient payload with a `422 Unprocessable Entity`.
**Solution:**
1. Pydantic validates the **request envelope**: required fields (`event_name`, `issuer_name`, `issue_date`), batch size limits ($1 \le N \le 1000$).
2. The `recipients` field accepts `list[Any]`.
3. In `services/jobs.py`, we iterate with `enumerate(recipients)`. Each item is evaluated individually. Valid items become `pending`; invalid items become `failed` with safe error codes (`INVALID_NAME`, `INVALID_EMAIL`, `DUPLICATE_RECIPIENT`).
4. This ensures every submitted row is accounted for at its original `input_index`.

### How Failure Isolation Works in the Worker
- Processing occurs recipient-by-recipient in **short transactions**.
- Step 1: In a short transaction, transition recipient status to `processing`.
- Step 2: **Outside any DB transaction**, render the PDF.
- Step 3: If rendering throws an exception (e.g. disk fault, unexpected character, memory limit), the worker catches the error, logs a safe warning without PII, and in a new short transaction marks that recipient as `failed` with `RENDER_ERROR`.
- The worker loop then continues to the next recipient without crashing or terminating the job.

### Atomic PDF Generation
To prevent clients from downloading half-written or corrupted PDFs if a crash occurs mid-write:
1. ReportLab writes to a temporary file: `.tmp_CERT-XXXXXX.pdf`.
2. Upon successful completion of `canvas.save()`, we call `os.replace(temp_file, final_file)`. On POSIX and modern Windows systems, `os.replace` is an **atomic filesystem operation**.
3. If an error occurs, the `.tmp` file is unlinked.

### Restart Recovery Policy
When a worker crashes (e.g. `kill -9` or server reboot), some recipients might be stranded in `processing` status.
On worker startup, `recover_interrupted_work(db)`:
1. Queries all recipients in `processing` and resets them to `pending`.
2. Queries all jobs in `processing` and resets them to `queued`.
3. **Preserves already-completed recipients:** Any recipient already marked `completed` is left untouched. When processing resumes, existing PDF files on disk are verified and not re-rendered.
4. **Preserves already-failed recipients:** Validation failures and prior rendering failures remain recorded.

### Path Traversal Defense
In `GET /api/v1/certificates/{certificate_id}/download`:
- The client passes **only** the `certificate_id` string (e.g. `CERT-8D3A1B4C9E0F`).
- The server queries the database for the associated `relative_pdf_path`.
- The full path is resolved: `(storage_dir / relative_pdf_path).resolve()`.
- We verify: `full_path.relative_to(storage_dir.resolve())`.
- If a path attempts directory traversal (`../`), it raises an HTTP error. Arbitrary client filesystem paths are never accepted.

---

## 5. Scaling: Migrating to PostgreSQL & Multi-Worker

If asked how to scale this system beyond a single node:

### 1. Database Migration (PostgreSQL)
Change `DATABASE_URL` to `postgresql://user:password@host:5432/cert_db`. Alembic handles schema deployment.

### 2. Multi-Worker Concurrency (`SKIP LOCKED`)
In a multi-worker setup, multiple worker processes would race to claim the same pending recipients. In PostgreSQL, we replace simple polling with `SELECT ... FOR UPDATE SKIP LOCKED`:
```sql
SELECT * FROM recipients 
WHERE status = 'pending' 
ORDER BY input_index ASC 
LIMIT 50 
FOR UPDATE SKIP LOCKED;
```
This allows $N$ worker instances to process batches concurrently without lock contention or duplicate certificate generation.

### 3. Distributed Object Storage (S3 / GCS)
Instead of local filesystem storage, upload generated PDFs to AWS S3 or Google Cloud Storage using presigned URLs or direct streams.

---

## 6. Template Customization & Adding Fields

### How to add a "Grade / Score" field:
1. **Schema (`schemas.py`):** Add optional `grade: Optional[str] = None` to `RecipientInput`.
2. **Model (`models.py`):** Add `grade = Column(String(50), nullable=True)` to `Recipient` model and generate an Alembic migration (`alembic revision --autogenerate`).
3. **Job Service (`services/jobs.py`):** Parse and sanitize `raw_entry.get("grade")`.
4. **Template (`services/certificates.py`):** Update `generate_certificate_pdf` to accept `grade` and draw a badge (e.g. "Distinction" or "Score: 98%") on the canvas.

---

## 7. Likely Interview Questions & Answers

### Q: "Why derive progress counters from SQL instead of maintaining counter columns on the Job table?"
> **Answer:**  
> Maintaining duplicate counter columns (`completed_count`, `failed_count`) on the `Job` row requires locking and updating the `Job` row after every single recipient. In concurrent environments, this causes lock contention on the parent job record and creates the risk of state drift (where the counter does not match the actual number of completed recipient rows). Querying `COUNT()` grouped by status is fast, indexed (`ix_recipients_job_status`), and represents the single source of truth.

### Q: "What happens if a recipient name has 200 characters?"
> **Answer:**  
> The certificate generator uses `_draw_fitted_text()`, which measures the rendered string width against the printable boundary (620 points) using `c.stringWidth()`. If the name exceeds the boundary, it dynamically decrements the font size from 32pt down to 18pt until it fits cleanly within the certificate borders without clipping.

### Q: "How does the system prevent PII leakage in application logs?"
> **Answer:**  
> Logging throughout the API and worker processes only logs internal system identifiers: `job_id`, `recipient_id`, and `certificate_id`. Personal data (names, emails) is never written to log sinks, ensuring compliance with privacy standards.

---

## 8. Three Hands-On Modification Exercises

### Exercise 1: Add a Certificate Expiry Date
- **Goal:** Allow an optional `expiry_date` in the job request. If provided, render "Valid Until: [Date]" on the certificate footer.
- **Files to touch:** `app/models.py` (add column to `Job`), `app/schemas.py` (add field and validator), `app/services/certificates.py` (draw text).

### Exercise 2: Add Batch Cancellation Endpoint
- **Goal:** Implement `POST /api/v1/jobs/{job_id}/cancel`.
- **Files to touch:** `app/api/routes.py` (add endpoint), `app/models.py` (add `CANCELLED` status). Any recipient still in `pending` status is transitioned to `failed` with error code `CANCELLED_BY_USER`.

### Exercise 3: Add Webhook Notification on Job Completion
- **Goal:** Allow an optional `webhook_url` in `JobCreateRequest`. When the worker finalizes the job status, dispatch an HTTP POST payload with the completion summary to the webhook.
- **Files to touch:** `app/schemas.py`, `app/worker.py` (using `httpx.post` after `_finalize_job_status`).
