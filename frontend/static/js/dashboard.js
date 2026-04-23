async function loadMe() {
  const who = document.getElementById("who");
  try {
    const res = await fetch("/auth/me");
    if (!res.ok) {
      console.warn("Not logged in:", res.status);
      return null;
    }
    const data = await res.json();
    if (who) {
      let html = `<span class="text-muted">Logged in as: ${data.email} (${data.role})</span>`;
      if (data.full_name) {
        html = `<strong>Hi ${data.full_name}</strong><br/>` +
               (data.school ? `${data.school}<br/>` : "") +
               (data.class_name ? `${data.class_name}<br/>` : "") +
               html;
      }
      who.innerHTML = html;
    }
    return data;
  } catch (e) {
    console.warn("loadMe error:", e);
    return null;
  }
}

async function logout(e) {
  if (e) e.preventDefault();
  await fetch("/auth/logout", { method: "POST" });
  window.location.href = "/login";
}

const logoutBtn = document.getElementById("logoutBtn");
if (logoutBtn) logoutBtn.addEventListener("click", logout);

loadMe();
