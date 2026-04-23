const analyticsEl = document.getElementById("analytics");
const rubricListEl = document.getElementById("rubricList");
const titleEl = document.getElementById("rubricTitle");
const criteriaEl = document.getElementById("rubricCriteria");
const msgEl = document.getElementById("msg");
const createBtn = document.getElementById("createRubricBtn");
console.log("admin_rubrics.js loaded");

function escapeHtml(str) {
  return str
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadAnalytics() {
  analyticsEl.innerHTML = "<li>Loading...</li>";
  const res = await fetch("/api/admin/analytics");
  if (!res.ok) {
    analyticsEl.innerHTML = "<li>Failed to load analytics</li>";
    return;
  }
  const a = await res.json();
  analyticsEl.innerHTML = `
    <li><strong>Total users:</strong> ${a.users_count}</li>
    <li><strong>Total submissions:</strong> ${a.submissions_count}</li>
    <li><strong>Top rubric:</strong> ${a.top_rubric ? escapeHtml(a.top_rubric.title) + " (" + a.top_rubric.count + ")" : "—"}</li>
  `;
}

async function loadRubrics() {
  rubricListEl.innerHTML = "<li>Loading...</li>";
  const res = await fetch("/api/admin/rubrics");
  if (!res.ok) {
    rubricListEl.innerHTML = "<li>Failed to load rubrics</li>";
    return;
  }
  const data = await res.json();
  rubricListEl.innerHTML = "";
  data.rubrics.forEach(r => {
    const li = document.createElement("li");
    li.style.marginBottom = "8px";
    li.innerHTML = `${escapeHtml(String(r.id))} — ${escapeHtml(r.title)}
      <button class="edit-rubric-btn" data-id="${r.id}" style="margin-left:10px; font-size:0.8em;">Edit</button>
      <button class="delete-rubric-btn" data-id="${r.id}" style="margin-left:6px; font-size:0.8em; color:red;">Delete</button>`;
    rubricListEl.appendChild(li);
  });
}

function parseCriteriaLines(raw) {
  const lines = raw.split("\n").map(x => x.trim()).filter(Boolean);
  return lines.map(line => {
    const parts = line.split("|").map(x => x.trim());
    return { name: parts[0] || "", description: parts.slice(1).join(" | ") || "" };
  });
}

async function createRubric() {
  msgEl.textContent = "Creating...";
  createBtn.disabled = true;

  const title = titleEl.value.trim();
  const criteria = parseCriteriaLines(criteriaEl.value);

  const res = await fetch("/api/admin/rubrics", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, criteria })
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    msgEl.textContent = data.detail || "Failed to create rubric";
    createBtn.disabled = false;
    return;
  }

  msgEl.textContent = "Rubric created successfully.";
  titleEl.value = "";
  criteriaEl.value = "";

  await loadRubrics();
  await loadAnalytics();

  createBtn.disabled = false;
}

createBtn.addEventListener("click", createRubric);

// Edit / Delete handlers
const editSection = document.getElementById("editSection");
const editIdEl = document.getElementById("editRubricId");
const editTitleEl = document.getElementById("editTitle");
const editCriteriaEl = document.getElementById("editCriteria");
const editMsgEl = document.getElementById("editMsg");
const saveEditBtn = document.getElementById("saveEditBtn");
const cancelEditBtn = document.getElementById("cancelEditBtn");

rubricListEl.addEventListener("click", async (e) => {
  const id = e.target.getAttribute("data-id");
  if (!id) return;

  if (e.target.classList.contains("edit-rubric-btn")) {
    const res = await fetch(`/api/admin/rubrics/${id}`);
    if (!res.ok) { msgEl.textContent = "Failed to load rubric."; return; }
    const r = await res.json();
    editIdEl.value = r.id;
    editTitleEl.value = r.title;
    editCriteriaEl.value = r.criteria.map(c => `${c.name} | ${c.description}`).join("\n");
    editMsgEl.textContent = "";
    editSection.style.display = "";
    editSection.scrollIntoView({ behavior: "smooth" });
  }

  if (e.target.classList.contains("delete-rubric-btn")) {
    if (!confirm("Delete this rubric? This cannot be undone. Rubrics with existing submissions cannot be deleted.")) return;
    e.target.disabled = true;
    const res = await fetch(`/api/admin/rubrics/${id}`, { method: "DELETE" });
    if (res.ok) {
      await loadRubrics();
      await loadAnalytics();
    } else {
      const data = await res.json().catch(() => ({}));
      msgEl.textContent = data.detail || "Failed to delete rubric.";
      e.target.disabled = false;
    }
  }
});

saveEditBtn.addEventListener("click", async () => {
  const id = editIdEl.value;
  const title = editTitleEl.value.trim();
  const criteria = parseCriteriaLines(editCriteriaEl.value);
  editMsgEl.textContent = "Saving...";
  saveEditBtn.disabled = true;
  const res = await fetch(`/api/admin/rubrics/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, criteria })
  });
  const data = await res.json().catch(() => ({}));
  if (res.ok) {
    editSection.style.display = "none";
    msgEl.textContent = "Rubric updated.";
    await loadRubrics();
  } else {
    editMsgEl.textContent = data.detail || "Failed to save.";
  }
  saveEditBtn.disabled = false;
});

cancelEditBtn.addEventListener("click", () => {
  editSection.style.display = "none";
  editMsgEl.textContent = "";
});

loadAnalytics();
loadRubrics();
