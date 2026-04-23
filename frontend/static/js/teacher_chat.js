console.log("teacher_chat.js loaded");

const teacherChatLog = document.getElementById("teacherChatLog");
const teacherChatInput = document.getElementById("teacherChatInput");
const teacherChatSendBtn = document.getElementById("teacherChatSendBtn");
const teacherChatMsg = document.getElementById("teacherChatMsg");

// NEW: upload elements
const teacherChatFiles = document.getElementById("teacherChatFiles");
const teacherChatFilesMsg = document.getElementById("teacherChatFilesMsg");

function escapeHtml(str) {
  return (str || "")
    .toString()
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function appendChat(who, text) {
  const div = document.createElement("div");
  div.className = "chat-msg";
  div.innerHTML = `<span class="${who === "You" ? "chat-user" : "chat-bot"}">${escapeHtml(who)}:</span> ${escapeHtml(text).replaceAll("\n", "<br/>")}`;
  teacherChatLog.appendChild(div);
  teacherChatLog.scrollTop = teacherChatLog.scrollHeight;
}

// show a typing indicator while waiting for the copilot reply
function showTyping() {
  const div = document.createElement("div");
  div.className = "chat-msg chat-typing-row";
  div.innerHTML = `<span class="chat-bot">Copilot:</span>
    <span class="chat-typing"><span></span><span></span><span></span></span>`;
  teacherChatLog.appendChild(div);
  teacherChatLog.scrollTop = teacherChatLog.scrollHeight;
  return div;
}

function removeTyping(el) {
  if (el && el.parentNode) el.parentNode.removeChild(el);
}

async function uploadFiles(fileInputEl, statusEl) {
  if (!fileInputEl || !fileInputEl.files || fileInputEl.files.length === 0) return [];

  const files = Array.from(fileInputEl.files);

  const allowedExt = [".pdf", ".docx", ".pptx", ".jpg", ".jpeg", ".png"];
  for (const f of files) {
    const name = (f.name || "").toLowerCase();
    if (!allowedExt.some(ext => name.endsWith(ext))) {
      throw new Error("Only PDF, DOCX, PPTX, JPG, JPEG, PNG files are allowed.");
    }
  }

  if (statusEl) statusEl.textContent = `Uploading ${files.length} file(s)...`;

  const uploadedIds = [];
  for (const f of files) {
    const fd = new FormData();
    fd.append("file", f);
    const res = await fetch("/api/uploads", { method: "POST", credentials: "same-origin", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (statusEl) statusEl.textContent = "";
      throw new Error(data.detail || `Upload failed (${res.status})`);
    }
    uploadedIds.push(data.upload_id);
  }

  if (statusEl) statusEl.textContent = `Uploaded: ${files.map(x => x.name).join(", ")}`;
  fileInputEl.value = "";
  return uploadedIds;
}

async function sendTeacherChat(message, fileIds = []) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ mode: "teacher", message, attachment_ids: fileIds })
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data.reply;
}

if (!teacherChatLog || !teacherChatInput || !teacherChatSendBtn || !teacherChatMsg) {
  console.error("❌ Teacher chat elements missing. Check IDs in teacher.html");
} else {
  teacherChatSendBtn.addEventListener("click", async (e) => {
    e.preventDefault();

    teacherChatMsg.textContent = "";
    if (teacherChatFilesMsg) teacherChatFilesMsg.textContent = "";

    const msg = (teacherChatInput.value || "").trim();
    if (!msg) return;

    appendChat("You", msg);
    teacherChatInput.value = "";
    teacherChatSendBtn.disabled = true;
    const typingEl = showTyping();

    try {
      const fileIds = await uploadFiles(teacherChatFiles, teacherChatFilesMsg);

      // send chat request with file ids
      const reply = await sendTeacherChat(msg, fileIds);
      removeTyping(typingEl);
      appendChat("Copilot", reply);
    } catch (err) {
      removeTyping(typingEl);
      console.error(err);
      teacherChatMsg.textContent = err.message || "Chat failed";
    } finally {
      teacherChatSendBtn.disabled = false;
    }
  });

  teacherChatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      teacherChatSendBtn.click();
    }
  });
}