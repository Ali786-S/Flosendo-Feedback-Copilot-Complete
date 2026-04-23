const form = document.getElementById("createUserForm");
const msg = document.getElementById("message");
const userList = document.getElementById("userList");
const pendingSection = document.getElementById("pendingSection");
const pendingList = document.getElementById("pendingList");

async function loadUsers() {
  userList.innerHTML = "<li>Loading...</li>";
  const res = await fetch("/api/admin/users");
  if (!res.ok) {
    userList.innerHTML = "<li>Failed to load users</li>";
    return;
  }
  const data = await res.json();
  const isPlatformAdmin = data.caller_role === "admin";
  const callerEmail = data.caller_email;

  // Split users into pending school admin requests vs everyone else
  const pending = data.users.filter(u => u.role === "school_admin" && u.approval_status === "pending");
  const others = data.users.filter(u => !(u.role === "school_admin" && u.approval_status === "pending"));

  // Pending school admin requests (platform admin only)
  if (isPlatformAdmin && pending.length > 0) {
    pendingSection.style.display = "";
    pendingList.innerHTML = "";
    pending.forEach(u => {
      const li = document.createElement("li");
      li.style.marginBottom = "12px";
      li.innerHTML = `
        <strong>${escapeHtml(u.full_name || u.email)}</strong> — ${escapeHtml(u.email)}<br/>
        <span class="text-muted text-small">School: ${escapeHtml(u.school || "—")}</span><br/>
        <span class="text-muted text-small">Proof: ${escapeHtml(u.admin_proof || "—")}</span><br/>
        <button class="approve-btn" data-email="${u.email}" style="margin-top:6px;">Approve</button>
        <button class="reject-btn" data-email="${u.email}" style="margin-left:8px; margin-top:6px;">Reject</button>
        <span class="review-msg text-small text-muted" style="margin-left:8px;"></span>
      `;
      pendingList.appendChild(li);
    });
  } else {
    pendingSection.style.display = "none";
  }

  // Regular user list
  userList.innerHTML = "";
  if (others.length === 0) {
    userList.innerHTML = "<li class='text-muted'>No users found.</li>";
    return;
  }
  others.forEach(u => {
    const li = document.createElement("li");
    const badge = u.email_verified
      ? '<span style="color:green; margin-left:8px; font-size:0.85em;">✓ verified</span>'
      : '<span style="color:#999; margin-left:8px; font-size:0.85em;">unverified</span>';
    const verifyBtn = !u.email_verified
      ? `<button class="verify-btn" data-email="${u.email}" style="margin-left:10px; font-size:0.8em;">Verify manually</button>`
      : "";
    const schoolInfo = u.school ? ` — ${escapeHtml(u.school)}` : "";
    const classInfo = u.class_name ? ` (${escapeHtml(u.class_name)})` : "";
    const deleteBtn = u.email !== callerEmail
      ? `<button class="delete-btn" data-email="${u.email}" style="margin-left:10px; font-size:0.8em; color:red;">Delete</button>`
      : "";
    const transferBtn = isPlatformAdmin && u.role === "school_admin" && u.approval_status === "approved"
      ? `<button class="transfer-btn" data-email="${u.email}" style="margin-left:10px; font-size:0.8em; color:purple;">Transfer Ownership</button>`
      : "";
    li.innerHTML = `${escapeHtml(u.email)} (${escapeHtml(u.role)})${schoolInfo}${classInfo}${badge}${verifyBtn}${deleteBtn}${transferBtn}`;
    userList.appendChild(li);
  });
}

function escapeHtml(str) {
  return String(str || "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

// Approve / reject school admin requests
pendingList.addEventListener("click", async (e) => {
  const btn = e.target;
  const email = btn.getAttribute("data-email");
  if (!email) return;

  let action = null;
  if (btn.classList.contains("approve-btn")) action = "approve";
  if (btn.classList.contains("reject-btn")) action = "reject";
  if (!action) return;

  btn.disabled = true;
  const statusEl = btn.parentElement.querySelector(".review-msg");
  if (statusEl) statusEl.textContent = "Saving...";

  const res = await fetch("/api/admin/school-admin/review", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, action })
  });

  if (res.ok) {
    await loadUsers();
  } else {
    btn.disabled = false;
    if (statusEl) statusEl.textContent = "Failed.";
  }
});

// Manually verify email
userList.addEventListener("click", async (e) => {
  if (!e.target.classList.contains("verify-btn")) return;
  const email = e.target.getAttribute("data-email");
  e.target.disabled = true;
  e.target.textContent = "Verifying...";
  const res = await fetch("/api/admin/users/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email })
  });
  if (res.ok) await loadUsers();
  else e.target.textContent = "Failed";
});

// Delete user
userList.addEventListener("click", async (e) => {
  if (!e.target.classList.contains("delete-btn")) return;
  const email = e.target.getAttribute("data-email");
  if (!confirm(`Delete ${email}? This will permanently remove their account and all associated data.`)) return;
  e.target.disabled = true;
  e.target.textContent = "Deleting...";
  const res = await fetch("/api/admin/users", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email })
  });
  if (res.ok) {
    await loadUsers();
  } else {
    const data = await res.json().catch(() => ({}));
    e.target.textContent = "Failed";
    e.target.disabled = false;
    msg.textContent = data.detail || "Failed to delete user.";
  }
});

// Transfer platform ownership
userList.addEventListener("click", async (e) => {
  if (!e.target.classList.contains("transfer-btn")) return;
  const email = e.target.getAttribute("data-email");
  if (!confirm(`Transfer platform ownership to ${email}?\n\nYou will be downgraded to school admin and logged out immediately. This cannot be undone without the new admin's cooperation.`)) return;
  e.target.disabled = true;
  e.target.textContent = "Transferring...";
  const res = await fetch("/api/admin/transfer-ownership", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email })
  });
  if (res.ok) {
    alert("Ownership transferred. You have been logged out.");
    window.location.href = "/login";
  } else {
    const data = await res.json().catch(() => ({}));
    msg.textContent = data.detail || "Transfer failed.";
    e.target.disabled = false;
    e.target.textContent = "Transfer Ownership";
  }
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  msg.textContent = "Creating user...";

  const email = document.getElementById("newEmail").value.trim();
  const role = document.getElementById("newRole").value;
  const password = document.getElementById("newPassword").value;

  const res = await fetch("/api/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, role, password })
  });

  const data = await res.json();
  if (!res.ok) {
    msg.textContent = data.detail || "Failed to create user.";
    return;
  }

  msg.textContent = "User created. A verification email has been sent (or verify manually below).";
  form.reset();
  await loadUsers();
});

loadUsers();
