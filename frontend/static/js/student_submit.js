const rubricSelect = document.getElementById("rubricSelect");
const submissionText = document.getElementById("submissionText");
const submitBtn = document.getElementById("submitBtn");
const messageEl = document.getElementById("message");
const mySubmissionsEl = document.getElementById("mySubmissions");
const feedbackPanel = document.getElementById("feedbackPanel");
const submissionFiles = document.getElementById("submissionFiles");
const submissionFilesMsg = document.getElementById("submissionFilesMsg");
const mySubmissionsToggle = document.getElementById("mySubmissionsToggle");
const submissionCountEl = document.getElementById("submissionCount");

mySubmissionsToggle.addEventListener("click", () => {
  const isHidden = mySubmissionsEl.classList.toggle("hidden");
  mySubmissionsToggle.firstChild.textContent = isHidden
    ? "▶ My submissions "
    : "▼ My submissions ";
});

function escapeHtml(str) {
  return str
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadRubrics() {
  rubricSelect.innerHTML = "<option>Loading...</option>";
  const res = await fetch("/api/rubrics");
  if (!res.ok) {
    rubricSelect.innerHTML = "<option>Error loading rubrics</option>";
    return;
  }
  const data = await res.json();
  rubricSelect.innerHTML = "";
  data.rubrics.forEach(r => {
    const opt = document.createElement("option");
    opt.value = r.id;
    opt.textContent = r.title;
    rubricSelect.appendChild(opt);
  });
}

async function loadMySubmissions() {
  mySubmissionsEl.innerHTML = "<li>Loading...</li>";
  const res = await fetch("/api/submissions/me");
  if (!res.ok) {
    mySubmissionsEl.innerHTML = "<li>Failed to load submissions</li>";
    return;
  }
  const data = await res.json();

  if (!data.submissions.length) {
    mySubmissionsEl.innerHTML = "<li>No submissions yet.</li>";
    submissionCountEl.textContent = "(0)";
    return;
}


  mySubmissionsEl.innerHTML = "";
  submissionCountEl.textContent = `(${data.submissions.length})`;
  data.submissions.forEach(s => {
    const li = document.createElement("li");
    li.innerHTML = `<a href="#" data-id="${s.id}">#${s.id}</a> — ${escapeHtml(s.rubric_title)} <span class="text-muted text-small">(${escapeHtml(s.created_at)})</span>`;
    mySubmissionsEl.appendChild(li);
  });

  // Click handler for viewing feedback
  mySubmissionsEl.querySelectorAll("a[data-id]").forEach(a => {
    a.addEventListener("click", async (e) => {
      e.preventDefault();
      const id = a.getAttribute("data-id");
      await loadSubmissionDetails(id);
    });
  });
}

function renderFeedback(details) {
  const f = details.feedback;
  if (!f) {
    feedbackPanel.innerHTML = "<p>No feedback found for this submission.</p>";
    return;
  }

  let html = `
    <p><strong>Submission #${details.id}</strong></p>
    <p class="text-muted">Rubric: ${escapeHtml(details.rubric_title)}</p>
    <p><strong>Overall summary</strong><br/>${escapeHtml(f.overall_summary || "")}</p>
    <hr/>
    <p><strong>Rubric breakdown</strong></p>
  `;

  (f.rubric_breakdown || []).forEach(item => {
    html += `
      <div class="mt-12"></div>
      <p><strong>${escapeHtml(item.criterion)}</strong> (Score: ${escapeHtml(String(item.score))})</p>
      <p><em>Strengths:</em> ${escapeHtml(item.strengths || "")}</p>
      <p><em>Improvements:</em> ${escapeHtml(item.improvements || "")}</p>
      <p class="text-muted text-small"><em>Evidence:</em> ${escapeHtml(item.evidence || "")}</p>
    `;
  });

  html += `<hr/><p><strong>Next steps</strong></p><ul>`;
  (f.next_steps || []).forEach(step => {
    html += `<li>${escapeHtml(step)}</li>`;
  });
  html += `</ul>`;

  feedbackPanel.innerHTML = html;
}

async function loadSubmissionDetails(id) {
  window.selectedSubmissionId = Number(id);

  feedbackPanel.innerHTML = "<p>Loading feedback...</p>";
  const res = await fetch(`/api/submissions/${id}`);
  if (!res.ok) {
    feedbackPanel.innerHTML = "<p>Failed to load submission.</p>";
    return;
  }
  const details = await res.json();
  renderFeedback(details);
}


async function submitWork() {
  messageEl.textContent = "";
  submitBtn.disabled = true;
  submitBtn.textContent = "Generating feedback...";
  if (submissionFilesMsg) submissionFilesMsg.textContent = "";

  try {
    // upload attachments first (optional)
    const attachmentIds = await uploadSubmissionFiles();

    // submit work with attachment IDs
    const payload = {
      rubric_id: Number(rubricSelect.value),
      submission_text: submissionText.value,
      attachment_ids: attachmentIds
    };

    const res = await fetch("/api/submissions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      credentials: "include"
    });

    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      messageEl.textContent = data.detail || "Submission failed.";
      return;
    }

    messageEl.textContent = `Submitted, Good Job (ID: ${data.submission_id})`;
    submissionText.value = "";
    await loadMySubmissions();
    mySubmissionsEl.classList.remove("hidden");
    mySubmissionsToggle.firstChild.textContent = "▼ My submissions ";
    await loadSubmissionDetails(data.submission_id);
  } catch (e) {
    messageEl.textContent = e.message || "Submission failed.";
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Submit for feedback";
  }
}


async function uploadSubmissionFiles() {
  if (!submissionFiles || !submissionFiles.files || submissionFiles.files.length === 0) return [];

  const files = Array.from(submissionFiles.files);

  const allowedExt = [".pdf", ".docx", ".pptx", ".jpg", ".jpeg", ".png"];
  for (const f of files) {
    const name = (f.name || "").toLowerCase();
    if (!allowedExt.some(ext => name.endsWith(ext))) {
      throw new Error("Only PDF, DOCX, PPTX, JPG, JPEG, PNG files are allowed.");
    }
  }

  if (submissionFilesMsg) submissionFilesMsg.textContent = `Uploading ${files.length} file(s)...`;

  const uploadedIds = [];

  for (const f of files) {
    const fd = new FormData();
    fd.append("file", f); 

    const res = await fetch("/api/uploads", {
      method: "POST",
      body: fd,
      credentials: "include"
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Upload failed");

    uploadedIds.push(data.upload_id);
  }

  if (submissionFilesMsg) submissionFilesMsg.textContent = `Uploaded: ${files.map(f => f.name).join(", ")}`;
  submissionFiles.value = "";
  return uploadedIds;
}


submitBtn.addEventListener("click", submitWork);

loadRubrics();
loadMySubmissions();
