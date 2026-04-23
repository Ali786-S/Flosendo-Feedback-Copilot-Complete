const form = document.getElementById("loginForm");
const msg = document.getElementById("message");
const resendSection = document.getElementById("resendSection");
const resendBtn = document.getElementById("resendBtn");
const resendMsg = document.getElementById("resendMsg");
const resendCountdown = document.getElementById("resendCountdown");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  msg.textContent = "Signing in...";
  if (resendSection) resendSection.style.display = "none";

  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;

  try {
    const res = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    const data = await res.json();

    if (!res.ok) {
      const detail = data.detail || "Login failed.";
      msg.textContent = detail;
      if (detail.toLowerCase().includes("verify your email") && resendSection) {
        resendSection.style.display = "";
        document.getElementById("resendEmail").value = email;
      }
      return;
    }

    msg.textContent = `Logged in as ${data.role}. Redirecting...`;

    if (data.role === "student") window.location.href = "/student";
    else if (data.role === "teacher") window.location.href = "/teacher";
    else if (data.role === "admin") window.location.href = "/admin";
    else if (data.role === "school_admin") window.location.href = "/admin";
    else window.location.href = "/";
  } catch (err) {
    msg.textContent = "Error connecting to server.";
  }
});

function startCooldown() {
  let seconds = 30;
  resendBtn.disabled = true;
  resendCountdown.textContent = `Try again in ${seconds}s`;
  const interval = setInterval(() => {
    seconds--;
    resendCountdown.textContent = seconds > 0 ? `Try again in ${seconds}s` : "";
    if (seconds <= 0) {
      clearInterval(interval);
      resendBtn.disabled = false;
    }
  }, 1000);
}

resendBtn?.addEventListener("click", async () => {
  const email = document.getElementById("resendEmail").value.trim();
  resendMsg.textContent = "Sending...";
  startCooldown();

  const res = await fetch("/auth/resend-verification", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email })
  });

  resendMsg.textContent = res.ok
    ? "Verification email sent. Check your inbox."
    : "Something went wrong. Please try again.";
});
