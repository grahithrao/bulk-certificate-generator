document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const form = document.getElementById("job-form");
  const eventNameInput = document.getElementById("event_name");
  const issuerNameInput = document.getElementById("issuer_name");
  const issueDateInput = document.getElementById("issue_date");
  const recipientsTbody = document.getElementById("recipients-tbody");
  const recipientCountSpan = document.getElementById("recipient-count");
  const btnAddRecipient = document.getElementById("btn-add-recipient");
  const formErrorBanner = document.getElementById("form-error-banner");

  // Presets
  const btnSampleMixed = document.getElementById("btn-sample-mixed");
  const btnSampleValid = document.getElementById("btn-sample-valid");
  const btnSampleUnicode = document.getElementById("btn-sample-unicode");

  // Submit button
  const btnSubmitJob = document.getElementById("btn-submit-job");
  const btnSubmitText = document.getElementById("btn-submit-text");
  const btnSubmitSpinner = document.getElementById("btn-submit-spinner");

  // Preview elements
  const certPreviewFrame = document.getElementById("cert-preview-frame");
  const previewModeBadge = document.getElementById("preview-mode-badge");
  const previewDescription = document.getElementById("preview-description");
  const btnPreviewNewTab = document.getElementById("btn-preview-new-tab");

  // Monitoring elements
  const monitorEmptyState = document.getElementById("monitor-empty-state");
  const monitorActiveWrapper = document.getElementById("monitor-active-wrapper");
  const jobStatusPill = document.getElementById("job-status-pill");

  const dispJobId = document.getElementById("disp-job-id");
  const dispEventName = document.getElementById("disp-event-name");
  const dispIssuerName = document.getElementById("disp-issuer-name");
  const dispProgressPercent = document.getElementById("disp-progress-percent");
  const progressBarFill = document.getElementById("progress-bar-fill");

  const cntTotal = document.getElementById("cnt-total");
  const cntCompleted = document.getElementById("cnt-completed");
  const cntFailed = document.getElementById("cnt-failed");
  const cntRemaining = document.getElementById("cnt-remaining");

  const outcomesTbody = document.getElementById("outcomes-tbody");
  const outcomeFilter = document.getElementById("outcome-filter");

  // State
  let activeJobId = null;
  let pollingIntervalId = null;
  let hasAutoSwitchedPreview = false;

  // Set default issue date to today
  const today = new Date().toISOString().split("T")[0];
  issueDateInput.value = today;

  // Helper: Create safe table cell with text
  function createSafeCell(text) {
    const td = document.createElement("td");
    td.textContent = text ?? "";
    return td;
  }

  function showFormError(msg) {
    formErrorBanner.textContent = msg;
    formErrorBanner.classList.remove("hidden");
  }

  function clearFormError() {
    formErrorBanner.textContent = "";
    formErrorBanner.classList.add("hidden");
  }

  // Recipient row management
  function updateRecipientCount() {
    const rows = recipientsTbody.querySelectorAll("tr");
    recipientCountSpan.textContent = rows.length;
    rows.forEach((row, idx) => {
      const idxCell = row.querySelector(".row-index");
      if (idxCell) idxCell.textContent = idx;
    });
  }

  function addRecipientRow(name = "", email = "") {
    clearFormError();
    const tr = document.createElement("tr");

    const tdIdx = document.createElement("td");
    tdIdx.className = "row-index";

    const tdName = document.createElement("td");
    const inputName = document.createElement("input");
    inputName.type = "text";
    inputName.placeholder = "Full Name";
    inputName.value = name;
    inputName.className = "input-rec-name";
    tdName.appendChild(inputName);

    const tdEmail = document.createElement("td");
    const inputEmail = document.createElement("input");
    inputEmail.type = "email";
    inputEmail.placeholder = "email@example.com";
    inputEmail.value = email;
    inputEmail.className = "input-rec-email";
    tdEmail.appendChild(inputEmail);

    const tdAction = document.createElement("td");
    tdAction.className = "text-center";
    const btnDel = document.createElement("button");
    btnDel.type = "button";
    btnDel.className = "btn-remove-row";
    btnDel.innerHTML = `
      <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
        <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.75.75 0 1 1 1.06 1.06L9.06 8l3.22 3.22a.75.75 0 1 1-1.06 1.06L8 9.06l-3.22 3.22a.75.75 0 0 1-1.06-1.06L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z"/>
      </svg>
    `;
    btnDel.title = "Remove recipient";
    btnDel.setAttribute("aria-label", "Remove recipient");
    btnDel.addEventListener("click", () => {
      tr.remove();
      updateRecipientCount();
    });
    tdAction.appendChild(btnDel);

    tr.appendChild(tdIdx);
    tr.appendChild(tdName);
    tr.appendChild(tdEmail);
    tr.appendChild(tdAction);

    recipientsTbody.appendChild(tr);
    updateRecipientCount();
  }

  function clearRecipients() {
    recipientsTbody.innerHTML = "";
    updateRecipientCount();
  }

  btnAddRecipient.addEventListener("click", () => addRecipientRow());

  // Sample batch presets
  btnSampleMixed.addEventListener("click", () => {
    eventNameInput.value = "Modern Cloud Architecture Symposium";
    issuerNameInput.value = "DevOps Institute of Technology";
    issueDateInput.value = today;
    clearRecipients();
    addRecipientRow("Aarav Sharma", "aarav@example.com");
    addRecipientRow("   ", "blank_name@example.com");
    addRecipientRow("Diya Rao", "diya@example.com");
    addRecipientRow("Carlos Mendoza", "invalid-email-format");
    addRecipientRow("Diya Rao Duplicate", "diya@example.com");
  });

  btnSampleValid.addEventListener("click", () => {
    eventNameInput.value = "Python Backend Development Workshop";
    issuerNameInput.value = "Example Learning Academy";
    issueDateInput.value = today;
    clearRecipients();
    addRecipientRow("Aarav Sharma", "aarav@example.com");
    addRecipientRow("Diya Rao", "diya@example.com");
    addRecipientRow("Marcus Vance", "marcus@example.com");
  });

  btnSampleUnicode.addEventListener("click", () => {
    eventNameInput.value = "International Distributed Systems Masterclass";
    issuerNameInput.value = "European Software Institute";
    issueDateInput.value = today;
    clearRecipients();
    addRecipientRow("Dr. Bartholomew Montgomery-Wellington III", "bart@example.com");
    addRecipientRow("José García Núñez", "jose.garcia@example.com");
    addRecipientRow("Åsa Lindgren-Müller", "asa.lindgren@example.com");
    addRecipientRow("François René de Chateaubriand", "francois@example.com");
  });

  // Load Mixed preset on first load
  btnSampleMixed.click();

  // Preview management
  function switchPreviewToCertificate(certId, recipientName) {
    const url = `/api/v1/certificates/${certId}/download#toolbar=0&navpanes=0&scrollbar=0`;
    certPreviewFrame.src = url;
    previewModeBadge.className = "badge-completed-preview";
    previewModeBadge.textContent = "Generated Certificate";
    previewDescription.textContent = `Displaying certificate for ${recipientName}.`;
    btnPreviewNewTab.href = `/api/v1/certificates/${certId}/download`;
    btnPreviewNewTab.textContent = "Download PDF ↗";
  }

  function resetPreviewToSample() {
    certPreviewFrame.src = "/api/v1/certificates/preview#toolbar=0&navpanes=0&scrollbar=0";
    previewModeBadge.className = "badge-sample";
    previewModeBadge.textContent = "Sample preview";
    previewDescription.textContent = "Official print-ready vector PDF template rendered with ReportLab.";
    btnPreviewNewTab.href = "/api/v1/certificates/preview";
    btnPreviewNewTab.textContent = "Open PDF ↗";
  }

  // Polling logic
  function stopPolling() {
    if (pollingIntervalId) {
      clearInterval(pollingIntervalId);
      pollingIntervalId = null;
    }
  }

  async function pollJobStatus() {
    if (!activeJobId) return;

    try {
      const resp = await fetch(`/api/v1/jobs/${activeJobId}`);
      if (!resp.ok) {
        stopPolling();
        return;
      }
      const data = await resp.json();

      // Update meta
      dispJobId.textContent = data.job_id.slice(0, 13) + "...";
      dispJobId.title = data.job_id;
      dispEventName.textContent = data.event_name;
      dispIssuerName.textContent = data.issuer_name;

      // Status pill badge
      jobStatusPill.className = `pill-badge pill-${data.status}`;
      jobStatusPill.textContent = data.status.replace(/_/g, " ").toUpperCase();

      // Progress bar & percent
      const pct = data.progress_percent || 0;
      dispProgressPercent.textContent = `${pct.toFixed(1)}%`;
      progressBarFill.style.width = `${pct}%`;

      // Metrics
      cntTotal.textContent = data.counts.total;
      cntCompleted.textContent = data.counts.completed;
      cntFailed.textContent = data.counts.failed;
      cntRemaining.textContent = data.counts.pending + data.counts.processing;

      // Recipient outcomes
      await fetchRecipientOutcomes();

      // Check terminal state
      const terminalStatuses = ["completed", "completed_with_errors", "failed"];
      if (terminalStatuses.includes(data.status)) {
        stopPolling();
        btnSubmitJob.disabled = false;
        btnSubmitText.textContent = "Generate Certificates";
        btnSubmitSpinner.classList.add("hidden");
      }
    } catch (err) {
      console.error("Polling error:", err);
    }
  }

  async function fetchRecipientOutcomes() {
    if (!activeJobId) return;

    const filterVal = outcomeFilter.value;
    let url = `/api/v1/jobs/${activeJobId}/recipients?page=1&page_size=100`;
    if (filterVal) url += `&status=${filterVal}`;

    try {
      const resp = await fetch(url);
      if (!resp.ok) return;
      const data = await resp.json();

      outcomesTbody.innerHTML = "";
      if (data.items.length === 0) {
        const tr = document.createElement("tr");
        const td = document.createElement("td");
        td.colSpan = 6;
        td.style.textAlign = "center";
        td.style.color = "var(--text-muted)";
        td.style.padding = "20px";
        td.textContent = "No recipients match the selected filter.";
        tr.appendChild(td);
        outcomesTbody.appendChild(tr);
        return;
      }

      data.items.forEach((item) => {
        const tr = document.createElement("tr");

        // Auto-switch preview to first completed certificate once
        if (!hasAutoSwitchedPreview && item.status === "completed" && item.certificate_id) {
          hasAutoSwitchedPreview = true;
          switchPreviewToCertificate(item.certificate_id, item.name || "Recipient");
        }

        // # Index
        const tdIdx = createSafeCell(item.input_index);
        tdIdx.className = "row-index";

        // Name
        const tdName = createSafeCell(item.name || "(missing)");

        // Email
        const tdEmail = createSafeCell(item.email || "(missing)");
        tdEmail.className = "font-mono";

        // Status Pill
        const tdStatus = document.createElement("td");
        const pill = document.createElement("span");
        pill.className = `status-badge status-${item.status}`;
        pill.textContent = item.status;
        tdStatus.appendChild(pill);

        // Outcome Details
        const tdDetails = document.createElement("td");
        if (item.status === "failed") {
          const diag = document.createElement("div");
          diag.className = "error-diagnostic";
          if (item.error_code) {
            const codeBadge = document.createElement("span");
            codeBadge.className = "error-code-badge";
            codeBadge.textContent = item.error_code;
            diag.appendChild(codeBadge);
          }
          const msgSpan = document.createElement("span");
          msgSpan.className = "error-msg-text";
          msgSpan.textContent = item.error_message || "Generation failed";
          diag.appendChild(msgSpan);
          tdDetails.appendChild(diag);
        } else if (item.status === "completed") {
          tdDetails.textContent = "Certificate ready";
          tdDetails.style.color = "var(--color-success)";
          tdDetails.style.fontWeight = "600";
        } else {
          tdDetails.textContent = "Queued for processing";
          tdDetails.style.color = "var(--text-muted)";
        }

        // Actions
        const tdActions = document.createElement("td");
        tdActions.className = "text-right";
        if (item.status === "completed" && item.download_url) {
          const group = document.createElement("div");
          group.className = "action-btn-group";

          // Preview Button
          const btnPreview = document.createElement("button");
          btnPreview.type = "button";
          btnPreview.className = "btn-preview-sm";
          btnPreview.textContent = "Preview";
          btnPreview.title = "Preview this certificate";
          btnPreview.addEventListener("click", () => {
            switchPreviewToCertificate(item.certificate_id, item.name || "Recipient");
          });

          // Download Link
          const aDl = document.createElement("a");
          aDl.href = item.download_url;
          aDl.className = "btn-download-sm";
          aDl.target = "_blank";
          aDl.innerHTML = "📥 PDF";
          aDl.title = "Download PDF certificate";

          group.appendChild(btnPreview);
          group.appendChild(aDl);
          tdActions.appendChild(group);
        } else {
          tdActions.textContent = "-";
          tdActions.style.color = "var(--text-light)";
        }

        tr.appendChild(tdIdx);
        tr.appendChild(tdName);
        tr.appendChild(tdEmail);
        tr.appendChild(tdStatus);
        tr.appendChild(tdDetails);
        tr.appendChild(tdActions);

        outcomesTbody.appendChild(tr);
      });
    } catch (err) {
      console.error("Error fetching outcomes:", err);
    }
  }

  outcomeFilter.addEventListener("change", fetchRecipientOutcomes);

  // Form Submission
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearFormError();

    const rows = recipientsTbody.querySelectorAll("tr");
    const recipients = [];

    rows.forEach((row) => {
      const nameInput = row.querySelector(".input-rec-name");
      const emailInput = row.querySelector(".input-rec-email");
      recipients.push({
        name: nameInput ? nameInput.value : "",
        email: emailInput ? emailInput.value : "",
      });
    });

    if (recipients.length === 0) {
      showFormError("Please add at least one recipient to generate certificates.");
      return;
    }

    const eventNameVal = eventNameInput.value.trim();
    const issuerNameVal = issuerNameInput.value.trim();
    const issueDateVal = issueDateInput.value.trim();

    if (!eventNameVal) {
      showFormError("Please enter an Event / Program Name.");
      eventNameInput.focus();
      return;
    }

    if (!issuerNameVal) {
      showFormError("Please enter an Issuing Organization.");
      issuerNameInput.focus();
      return;
    }

    if (!issueDateVal) {
      showFormError("Please select an Issue Date.");
      issueDateInput.focus();
      return;
    }

    const payload = {
      event_name: eventNameVal,
      issuer_name: issuerNameVal,
      issue_date: issueDateVal,
      recipients: recipients,
    };

    // UI Loading state
    btnSubmitJob.disabled = true;
    btnSubmitText.textContent = "Submitting Batch...";
    btnSubmitSpinner.classList.remove("hidden");

    stopPolling();
    hasAutoSwitchedPreview = false;

    try {
      const resp = await fetch("/api/v1/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const data = await resp.json();

      if (resp.status !== 202 && resp.status !== 201) {
        showFormError(`Submission Error (${resp.status}): ${JSON.stringify(data.detail || data)}`);
        btnSubmitJob.disabled = false;
        btnSubmitText.textContent = "Generate Certificates";
        btnSubmitSpinner.classList.add("hidden");
        return;
      }

      // Activate monitoring view
      monitorEmptyState.classList.add("hidden");
      monitorActiveWrapper.classList.remove("hidden");

      activeJobId = data.job_id;
      dispJobId.textContent = activeJobId.slice(0, 13) + "...";
      dispJobId.title = activeJobId;
      dispEventName.textContent = payload.event_name;
      dispIssuerName.textContent = payload.issuer_name;

      // Start polling
      await pollJobStatus();
      pollingIntervalId = setInterval(pollJobStatus, 800);

    } catch (err) {
      showFormError("Network communication error: " + err.message);
      btnSubmitJob.disabled = false;
      btnSubmitText.textContent = "Generate Certificates";
      btnSubmitSpinner.classList.add("hidden");
    }
  });
});
