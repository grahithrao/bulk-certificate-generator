

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["owner"] == "Grahith Rao"
    assert "timestamp" in data


def test_create_valid_job(client):
    payload = {
        "event_name": "Python Backend Development Workshop",
        "issuer_name": "Example Learning Academy",
        "issue_date": "2026-10-11",
        "recipients": [
            {"name": "Aarav Sharma", "email": "aarav@example.com"},
            {"name": "Diya Rao", "email": "diya@example.com"},
        ],
    }
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "queued"
    assert data["total"] == 2
    assert data["accepted"] == 2
    assert data["rejected"] == 0
    assert data["status_url"] == f"/api/v1/jobs/{data['job_id']}"

    # Verify status endpoint immediately after creation
    job_resp = client.get(data["status_url"])
    assert job_resp.status_code == 200
    job_data = job_resp.json()
    assert job_data["status"] == "queued"
    assert job_data["counts"]["total"] == 2
    assert job_data["counts"]["pending"] == 2
    assert job_data["counts"]["processed"] == 0
    assert job_data["progress_percent"] == 0.0


def test_malformed_job_level_inputs(client):
    # Missing event_name
    resp1 = client.post(
        "/api/v1/jobs",
        json={
            "issuer_name": "Academy",
            "issue_date": "2026-10-11",
            "recipients": [{"name": "Aarav", "email": "aarav@example.com"}],
        },
    )
    assert resp1.status_code == 422

    # Blank event_name
    resp2 = client.post(
        "/api/v1/jobs",
        json={
            "event_name": "   ",
            "issuer_name": "Academy",
            "issue_date": "2026-10-11",
            "recipients": [{"name": "Aarav", "email": "aarav@example.com"}],
        },
    )
    assert resp2.status_code == 422

    # Invalid issue_date
    resp3 = client.post(
        "/api/v1/jobs",
        json={
            "event_name": "Course",
            "issuer_name": "Academy",
            "issue_date": "invalid-date",
            "recipients": [{"name": "Aarav", "email": "aarav@example.com"}],
        },
    )
    assert resp3.status_code == 422

    # Empty recipients array
    resp4 = client.post(
        "/api/v1/jobs",
        json={
            "event_name": "Course",
            "issuer_name": "Academy",
            "issue_date": "2026-10-11",
            "recipients": [],
        },
    )
    assert resp4.status_code == 422


def test_oversized_batch_rejected(client):
    large_batch = [{"name": f"User {i}", "email": f"user{i}@example.com"} for i in range(1001)]
    resp = client.post(
        "/api/v1/jobs",
        json={
            "event_name": "Large Event",
            "issuer_name": "Academy",
            "issue_date": "2026-10-11",
            "recipients": large_batch,
        },
    )
    assert resp.status_code == 422
    assert "exceeds maximum allowed limit" in resp.text


def test_mixed_valid_and_invalid_recipients(client):
    payload = {
        "event_name": "Mixed Batch Event",
        "issuer_name": "Academy",
        "issue_date": "2026-10-11",
        "recipients": [
            {"name": "Valid Recipient", "email": "valid@example.com"},       # idx 0: valid
            {"name": "   ", "email": "blank_name@example.com"},               # idx 1: blank name
            {"name": "Invalid Email User", "email": "not-an-email"},          # idx 2: bad email
            {"name": "Duplicate User", "email": "valid@example.com"},         # idx 3: duplicate of idx 0
            "malformed_string_entry",                                         # idx 4: not a dict
        ],
    }

    # Should accept the batch because there is at least one valid recipient
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "queued"
    assert data["total"] == 5
    assert data["accepted"] == 1
    assert data["rejected"] == 4

    # Fetch recipients
    rec_resp = client.get(f"/api/v1/jobs/{data['job_id']}/recipients")
    assert rec_resp.status_code == 200
    rec_data = rec_resp.json()
    assert rec_data["total"] == 5
    items = rec_data["items"]

    # Verify each recipient outcome and preserved input index
    assert items[0]["input_index"] == 0
    assert items[0]["status"] == "pending"
    assert items[0]["certificate_id"] is not None

    assert items[1]["input_index"] == 1
    assert items[1]["status"] == "failed"
    assert items[1]["error_code"] == "INVALID_NAME"

    assert items[2]["input_index"] == 2
    assert items[2]["status"] == "failed"
    assert items[2]["error_code"] == "INVALID_EMAIL"

    assert items[3]["input_index"] == 3
    assert items[3]["status"] == "failed"
    assert items[3]["error_code"] == "DUPLICATE_RECIPIENT"

    assert items[4]["input_index"] == 4
    assert items[4]["status"] == "failed"
    assert items[4]["error_code"] == "INVALID_PAYLOAD"


def test_all_invalid_batch_returns_201_failed(client):
    payload = {
        "event_name": "All Invalid Batch",
        "issuer_name": "Academy",
        "issue_date": "2026-10-11",
        "recipients": [
            {"name": "", "email": "user1@example.com"},
            {"name": "User 2", "email": "invalid-email@"},
            12345,
        ],
    }

    response = client.post("/api/v1/jobs", json=payload)
    # The requirement specifies HTTP 201 for all-invalid diagnostic batch
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "failed"
    assert data["total"] == 3
    assert data["accepted"] == 0
    assert data["rejected"] == 3

    # Check job status endpoint
    job_resp = client.get(f"/api/v1/jobs/{data['job_id']}")
    assert job_resp.status_code == 200
    job_data = job_resp.json()
    assert job_data["status"] == "failed"
    assert job_data["counts"]["total"] == 3
    assert job_data["counts"]["failed"] == 3
    assert job_data["counts"]["processed"] == 3
    assert job_data["progress_percent"] == 100.0


def test_recipients_pagination_and_status_filtering(client):
    payload = {
        "event_name": "Pagination Event",
        "issuer_name": "Academy",
        "issue_date": "2026-10-11",
        "recipients": [
            {"name": "User 1", "email": "u1@example.com"},
            {"name": "User 2", "email": "u2@example.com"},
            {"name": "User 3", "email": "u3@example.com"},
            {"name": "", "email": "invalid@example.com"},
        ],
    }
    create_resp = client.post("/api/v1/jobs", json=payload)
    job_id = create_resp.json()["job_id"]

    # Page 1 with page_size=2
    p1_resp = client.get(f"/api/v1/jobs/{job_id}/recipients?page=1&page_size=2")
    assert p1_resp.status_code == 200
    p1 = p1_resp.json()
    assert p1["total"] == 4
    assert len(p1["items"]) == 2
    assert p1["page"] == 1
    assert p1["total_pages"] == 2

    # Status filter: failed
    failed_resp = client.get(f"/api/v1/jobs/{job_id}/recipients?status=failed")
    assert failed_resp.status_code == 200
    failed_data = failed_resp.json()
    assert failed_data["total"] == 1
    assert failed_data["items"][0]["status"] == "failed"

    # Status filter: pending
    pending_resp = client.get(f"/api/v1/jobs/{job_id}/recipients?status=pending")
    assert pending_resp.status_code == 200
    pending_data = pending_resp.json()
    assert pending_data["total"] == 3
