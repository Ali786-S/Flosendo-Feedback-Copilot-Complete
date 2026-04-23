const allSubmissionsEl = document.getElementById("allSubmissions");
const submissionPanel = document.getElementById("submissionPanel");
const flagCheckbox = document.getElementById("flagCheckbox");
const teacherNote = document.getElementById("teacherNote");
const saveReviewBtn = document.getElementById("saveReviewBtn");
const reviewMsg = document.getElementById("reviewMsg");

// Track which submission is currently open
let selectedSubmissionId = null;

function escapeHtml(str) {
  return (str || "")
    .toString()
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadAllSubmissions() {
  allSubmissionsEl.innerHTML = "<li>Loading...</li>";
  const res = await fetch("/api/teacher/submissions");
  if (!res.ok) {
    allSubmissionsEl.innerHTML = "<li>Failed to load submissions</li>";
    return;
  }

  const data = await res.json();

  if (!data.submissions.length) {
    allSubmissionsEl.innerHTML = "<li>No submissions yet.</li>";
    return;
  }

  allSubmissionsEl.innerHTML = "";

// grouping submissions by student email
const grouped = {};
data.submissions.forEach(s => {
  if (!grouped[s.user_email]) grouped[s.user_email] = [];
  grouped[s.user_email].push(s);
});

// render each student group
Object.entries(grouped).forEach(([email, submissions]) => {
  const groupDiv = document.createElement("div");
  groupDiv.className = "submission-group";

  
  const toggle = document.createElement("div");
  toggle.className = "submission-group-toggle";
  toggle.textContent = `▶ ${email} (${submissions.length})`;

  
  const ul = document.createElement("ul");
  ul.classList.add("hidden");

  submissions.forEach(s => {
    const li = document.createElement("li");
    li.innerHTML = `
      <a href="#" data-id="${s.id}">
        #${s.id}
      </a> — ${escapeHtml(s.rubric_title)}
      <span class="text-muted text-small">(${escapeHtml(s.created_at)})</span>
    `;
    ul.appendChild(li);
  });

  
  toggle.addEventListener("click", () => {
    const isHidden = ul.classList.toggle("hidden");
    toggle.textContent = isHidden
      ? `▶ ${email} (${submissions.length})`
      : `▼ ${email} (${submissions.length})`;
  });


  ul.querySelectorAll("a[data-id]").forEach(a => {
    a.addEventListener("click", e => {
      e.preventDefault();
      loadSubmissionDetails(a.dataset.id);
    });
  });

  groupDiv.appendChild(toggle);
  groupDiv.appendChild(ul);
  allSubmissionsEl.appendChild(groupDiv);
});

}

function renderSubmission(details) {
  let html = `
    <p><strong>Submission #${details.id}</strong></p>
    <p class="text-muted">Student: ${escapeHtml(details.user_email)}</p>
    <p class="text-muted">Rubric: ${escapeHtml(details.rubric_title)}</p>

    <hr />
    <p><strong>Student work</strong></p>
    <pre style="white-space: pre-wrap;">${escapeHtml(details.submission_text || "")}</pre>
    <hr />
  `;

  const f = details.feedback;
  if (!f) {
    html += `<p>No feedback found.</p>`;
    submissionPanel.innerHTML = html;
    return;
  }

  html += `
    <p><strong>Overall summary</strong><br/>${escapeHtml(f.overall_summary || "")}</p>
    <p><strong>Next steps</strong></p>
    <ul>
      ${(f.next_steps || []).map(x => `<li>${escapeHtml(x)}</li>`).join("")}
    </ul>
    <hr />
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

  submissionPanel.innerHTML = html;
}

async function loadTeacherReview(id) {
  reviewMsg.textContent = "";
  flagCheckbox.checked = false;
  teacherNote.value = "";

  const res = await fetch(`/api/teacher/review/${id}`);
  if (!res.ok) return; // ok if none exists yet
  const data = await res.json();
  flagCheckbox.checked = !!data.flagged;
  teacherNote.value = data.note || "";
}

async function saveTeacherReview() {
  if (!selectedSubmissionId) {
    reviewMsg.textContent = "Select a submission first.";
    return;
  }

  reviewMsg.textContent = "Saving...";
  saveReviewBtn.disabled = true;

  const payload = {
    flagged: !!flagCheckbox.checked,
    note: teacherNote.value || ""
  };

  const res = await fetch(`/api/teacher/review/${selectedSubmissionId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    reviewMsg.textContent = data.detail || "Failed to save.";
    saveReviewBtn.disabled = false;
    return;
  }

  reviewMsg.textContent = "Saved";
  saveReviewBtn.disabled = false;
}

async function loadSubmissionDetails(id) {
  selectedSubmissionId = Number(id);

  submissionPanel.innerHTML = "<p>Loading submission...</p>";

  // Loads teacher review 
  loadTeacherReview(selectedSubmissionId);

  const res = await fetch(`/api/submissions/${selectedSubmissionId}`);
  if (!res.ok) {
    submissionPanel.innerHTML = "<p>Failed to load submission.</p>";
    return;
  }

  const details = await res.json();
  renderSubmission(details);
}

saveReviewBtn.addEventListener("click", saveTeacherReview);

loadAllSubmissions();
