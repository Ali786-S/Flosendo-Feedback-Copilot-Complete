// Chat elements
const feedbackChatLog = document.getElementById("feedbackChatLog");
const feedbackChatInput = document.getElementById("feedbackChatInput");
const feedbackChatSendBtn = document.getElementById("feedbackChatSendBtn");
const feedbackChatMsg = document.getElementById("feedbackChatMsg");
const feedbackChatFiles = document.getElementById("feedbackChatFiles");
const feedbackChatFilesMsg = document.getElementById("feedbackChatFilesMsg");
const generalChatLog = document.getElementById("generalChatLog");
const generalChatInput = document.getElementById("generalChatInput");
const generalChatSendBtn = document.getElementById("generalChatSendBtn");
const generalChatMsg = document.getElementById("generalChatMsg");

// <input id="generalChatFiles" type="file" multiple />
// <p id="generalChatFilesMsg" ...></p>
const generalChatFiles = document.getElementById("generalChatFiles");
const generalChatFilesMsg = document.getElementById("generalChatFilesMsg");

// store currently selected submission id 
window.selectedSubmissionId = window.selectedSubmissionId || null;

function escapeHtml(str) {
  return String(str || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function appendChat(logEl, who, text) {
  const div = document.createElement("div");
  div.className = "chat-msg";
  const labelClass = who === "You" ? "chat-user" : "chat-bot";
  div.innerHTML = `<span class="${labelClass}">${escapeHtml(who)}:</span> ${escapeHtml(text).replaceAll("\n", "<br/>")}`;
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
}

// show a typing indicator while waiting for the copilot reply
function showTyping(logEl) {
  const div = document.createElement("div");
  div.className = "chat-msg chat-typing-row";
  div.innerHTML = `<span class="chat-bot">Copilot:</span>
    <span class="chat-typing"><span></span><span></span><span></span></span>`;
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
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

    const res = await fetch("/api/uploads", { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (statusEl) statusEl.textContent = "";
      throw new Error(data.detail || "Upload failed");
    }
    uploadedIds.push(data.upload_id);
  }

  if (statusEl) statusEl.textContent = `Uploaded: ${files.map(x => x.name).join(", ")}`;
  fileInputEl.value = "";
  return uploadedIds;
}

async function sendChat(mode, message, submissionId, fileIds = []) {
  const payload = { mode, message };

  if (mode === "feedback") payload.submission_id = submissionId;

  payload.attachment_ids = fileIds;

  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || "Chat request failed");
  }
  return data.reply;
}

// Feedback chat
feedbackChatSendBtn?.addEventListener("click", async () => {
  feedbackChatMsg.textContent = "";
  if (feedbackChatFilesMsg) feedbackChatFilesMsg.textContent = "";

  const msg = (feedbackChatInput.value || "").trim();
  if (!msg) return;

  const sid = window.selectedSubmissionId;
  if (!sid) {
    feedbackChatMsg.textContent = "Select a submission first (from 'My submissions').";
    return;
  }

  appendChat(feedbackChatLog, "You", msg);
  feedbackChatInput.value = "";
  feedbackChatSendBtn.disabled = true;
  const typingEl = showTyping(feedbackChatLog);

  try {
    const fileIds = await uploadFiles(feedbackChatFiles, feedbackChatFilesMsg);
    const reply = await sendChat("feedback", msg, sid, fileIds);
    removeTyping(typingEl);
    appendChat(feedbackChatLog, "Copilot", reply);
  } catch (e) {
    removeTyping(typingEl);
    feedbackChatMsg.textContent = e.message || "Error";
  } finally {
    feedbackChatSendBtn.disabled = false;
  }
});

// General chat
generalChatSendBtn?.addEventListener("click", async () => {
  generalChatMsg.textContent = "";
  if (generalChatFilesMsg) generalChatFilesMsg.textContent = "";

  const msg = (generalChatInput.value || "").trim();
  if (!msg) return;

  appendChat(generalChatLog, "You", msg);
  generalChatInput.value = "";
  generalChatSendBtn.disabled = true;
  const typingEl = showTyping(generalChatLog);

  try {
    const fileIds = await uploadFiles(generalChatFiles, generalChatFilesMsg);

    const reply = await sendChat("general", msg, null, fileIds);
    removeTyping(typingEl);
    appendChat(generalChatLog, "Copilot", reply);
  } catch (e) {
    removeTyping(typingEl);
    generalChatMsg.textContent = e.message || "Error";
  } finally {
    generalChatSendBtn.disabled = false;
  }
});