from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
import json
from datetime import datetime
from fastapi import UploadFile, File
import os, re, secrets, sqlite3
import hashlib
import smtplib
from email.mime.text import MIMEText
from datetime import timedelta
import requests

# Load environment variables from .env before anything that reads them
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # dotenv is optional in production where env vars are set directly
    pass

from backend.db import init_db, get_conn
from backend.security import verify_password, hash_password
from backend.feedback_pipeline import generate_feedback
from backend.chat_pipeline import generate_chat_reply
# password reset rate limit to prevent abuse of passowrd resetting
RESET_RATE_LIMIT_SECONDS = 20

def _reset_rate_limit(request: Request):
    last = request.session.get("reset_last_ts")
    now = datetime.utcnow().timestamp()
    if last and (now - last) < RESET_RATE_LIMIT_SECONDS:
        raise HTTPException(status_code=429, detail="Too many requests. Try again shortly.")
    request.session["reset_last_ts"] = now

app = FastAPI()
init_db()
# --- Paths ---
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"

UPLOAD_DIR = Path(__file__).parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# Session secret is loaded from env so dev and prod can differ safely
SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-secret-change-me")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# --- Static files ---
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


# --- Pages ---
@app.get("/", response_class=HTMLResponse)
def home():
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        return "<h1>Error</h1><p>frontend/index.html not found.</p>"
    return index_file.read_text(encoding="utf-8")


@app.get("/login", response_class=HTMLResponse)
def login_page():
    login_file = FRONTEND_DIR / "login.html"
    if not login_file.exists():
        return "<h1>Error</h1><p>frontend/login.html not found.</p>"
    return login_file.read_text(encoding="utf-8")

@app.get("/reset", response_class=HTMLResponse)
def reset_page():
    reset_file = FRONTEND_DIR / "reset.html"
    if not reset_file.exists():
        return "<h1>Error</h1><p>frontend/reset.html not found.</p>"
    return reset_file.read_text(encoding="utf-8")

@app.get("/register", response_class=HTMLResponse)
def register_page():
    file = FRONTEND_DIR / "register.html"
    if not file.exists():
        return "<h1>Error</h1><p>frontend/register.html not found.</p>"
    return file.read_text(encoding="utf-8")



# --- Auth API ---
@app.post("/auth/login")
async def login(request: Request):
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT email, password_hash, role, email_verified, approval_status FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="No account exists with that email address.")
    if not verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect password.")

    if not row["email_verified"]:
        raise HTTPException(status_code=401, detail="Please verify your email before logging in. Check your inbox or ask an admin to verify your account.")

    if row["role"] == "school_admin":
        if row["approval_status"] == "pending":
            raise HTTPException(status_code=401, detail="Your account is pending verification by the Flosendo team. You will not currently be able to log in until verification has been completed. We will contact you for verification. For now, you can verify your email through the email verification link you will receive, but you must wait for further action once we have properly approved your account for use.")
        if row["approval_status"] == "rejected":
            raise HTTPException(status_code=401, detail="Your school admin application was not approved. Please contact Flosendo support.")

    request.session["user_email"] = row["email"]
    request.session["role"] = row["role"]

    return {"ok": True, "role": row["role"]}


@app.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.post("/auth/register")
async def register(request: Request):
    body = await request.json()

    full_name = (body.get("full_name") or "").strip()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    role = (body.get("role") or "").strip().lower()
    school = (body.get("school") or "").strip()
    class_name = (body.get("class_name") or "").strip()

    if len(full_name) < 2:
        raise HTTPException(status_code=400, detail="Please enter your full name")
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email is required")
    if len(password) < 12 or not re.search(r'[!@£$%^&*()\-_=+#~;:\'"<>?,./\\|\[\]{}]', password):
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters and include at least one special character")
    if role not in {"student", "teacher", "school_admin"}:
        raise HTTPException(status_code=400, detail="Invalid role")
    if not school:
        raise HTTPException(status_code=400, detail="School name is required")
    if role == "student" and not class_name:
        raise HTTPException(status_code=400, detail="Class is required for students")

    admin_proof = (body.get("admin_proof") or "").strip()
    if role == "school_admin" and not admin_proof:
        raise HTTPException(status_code=400, detail="Please provide verification information for your school admin request")

    approval_status = "pending" if role == "school_admin" else "none"
    pw_hash = hash_password(password)
    token = secrets.token_urlsafe(32)

    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (email, password_hash, role, email_verified, verification_token, full_name, school, class_name, approval_status, admin_proof) VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?)",
            (email, pw_hash, role, token, full_name, school, class_name or None, approval_status, admin_proof or None),
        )
        conn.commit()
        conn.close()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="An account with this email already exists")
    except Exception as e:
        print(f"[register] DB error: {e}")
        raise HTTPException(status_code=500, detail="Registration failed due to a server error. Please try again.")

    try:
        base_url = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        verify_url = f"{base_url}/auth/verify?token={token}"
        send_verification_email(email, verify_url)
    except Exception as e:
        print(f"[register] Verification email failed: {e}. Admin can verify manually.")

    return {"ok": True}

def require_role(request: Request, allowed_roles: set[str]):
    role = request.session.get("role")
    if role is None:
        raise HTTPException(status_code=401, detail="Not logged in")
    if role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Forbidden")
    return role

@app.get("/auth/change-password", response_class=HTMLResponse)
def change_password_page(request: Request):
    require_role(request, {"student", "teacher", "admin", "school_admin"})
    file = FRONTEND_DIR / "change_password.html"
    if not file.exists():
        return "<h1>Error</h1><p>frontend/change_password.html not found.</p>"
    return file.read_text(encoding="utf-8")


@app.post("/auth/change-password")
async def change_password(request: Request):
    require_role(request, {"student", "teacher", "admin", "school_admin"})
    body = await request.json()

    current_password = body.get("current_password") or ""
    new_password = body.get("new_password") or ""

    if len(new_password) < 12 or not re.search(r'[!@£$%^&*()\-_=+#~;:\'"<>?,./\\|\[\]{}]', new_password):
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters and include at least one special character")

    email = request.session.get("user_email")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT password_hash FROM users WHERE email = ?", (email,))
    row = cur.fetchone()

    if not row or not verify_password(current_password, row["password_hash"]):
        conn.close()
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    cur.execute("UPDATE users SET password_hash = ? WHERE email = ?", (hash_password(new_password), email))
    conn.commit()
    conn.close()

    return {"ok": True}

ALLOWED_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  
    "application/msword",  
    "application/vnd.ms-powerpoint", 
    "text/plain",
    "image/jpeg",
    "image/jpg",
    "image/png",  
}

MAX_UPLOAD_MB = 15  

RESET_TOKEN_MINUTES = 30

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def send_email(to_email: str, subject: str, html_body: str):
    """
    Send email via SMTP. Works with Gmail, Outlook, or any free SMTP provider.
    Configure SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD in .env.
    Gmail: use an App Password (Google account > Security > 2-Step > App Passwords).
    """
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")

    if not all([smtp_host, smtp_user, smtp_password]):
        raise ValueError("SMTP not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env")

    msg = MIMEText(html_body, "html")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_email

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, to_email, msg.as_string())


def send_reset_email(to_email: str, reset_url: str):
    send_email(
        to_email,
        "Password Reset Request — Flosendo",
        f"<p>You requested a password reset.</p><p><a href='{reset_url}'>Reset Password</a></p><p>This link expires in 30 minutes.</p>",
    )


def send_verification_email(to_email: str, verify_url: str):
    send_email(
        to_email,
        "Verify your Flosendo account",
        f"<p>Welcome to Flosendo! Please verify your email to activate your account.</p><p><a href='{verify_url}'>Verify Email</a></p>",
    )


@app.post("/auth/forgot")
async def forgot_password(request: Request):
    _reset_rate_limit(request)
    body = await request.json()
    email = (body.get("email") or "").strip().lower()

    
    if not email or "@" not in email:
        return {"ok": True, "reset_url": None}

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT email FROM users WHERE email = ?", (email,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return {"ok": True, "reset_url": None}

    # Create token
    token = secrets.token_urlsafe(32)
    token_hash = sha256_hex(token)

    now = datetime.utcnow()
    expires_at = (now + timedelta(minutes=RESET_TOKEN_MINUTES)).isoformat()

    cur.execute("""
        INSERT INTO password_reset_tokens (user_email, token_hash, expires_at, used_at, created_at)
        VALUES (?, ?, ?, NULL, ?)
    """, (email, token_hash, expires_at, now.isoformat()))
    conn.commit()
    conn.close()

    # returns reset link via email
    base_url = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    reset_url = f"{base_url}/reset?token={token}"
    try:
     send_reset_email(email, reset_url)
    except Exception as e:
     print("EMAIL ERROR:", e)
    return {"ok": True}




@app.post("/auth/reset")
async def reset_password(request: Request):
    body = await request.json()
    token = (body.get("token") or "").strip()
    new_password = body.get("new_password") or ""

    if not token:
        raise HTTPException(status_code=400, detail="Missing token")
    if len(new_password) < 12 or not re.search(r'[!@£$%^&*()\-_=+#~;:\'"<>?,./\\|\[\]{}]', new_password):
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters and include at least one special character")

    token_hash = sha256_hex(token)
    now = datetime.utcnow()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, user_email, expires_at, used_at
        FROM password_reset_tokens
        WHERE token_hash = ?
        ORDER BY id DESC
        LIMIT 1
    """, (token_hash,))
    t = cur.fetchone()

    if not t:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    if t["used_at"]:
        conn.close()
        raise HTTPException(status_code=400, detail="Token already used")

    expires_at = datetime.fromisoformat(t["expires_at"])
    if now > expires_at:
        conn.close()
        raise HTTPException(status_code=400, detail="Token expired")

    # Update password + mark token used
    pw_hash = hash_password(new_password)

    cur.execute("UPDATE users SET password_hash = ? WHERE email = ?", (pw_hash, t["user_email"]))
    cur.execute("UPDATE password_reset_tokens SET used_at = ? WHERE id = ?", (now.isoformat(), t["id"]))
    conn.commit()
    conn.close()

    return {"ok": True}

@app.post("/api/uploads")
async def upload_file(request: Request, file: UploadFile = File(...)):
    ALLOWED_EXT = {".pdf", ".docx", ".pptx", ".txt", ".png", ".jpg", ".jpeg"}

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"File extension not allowed: {ext}")

    # ...rest of your upload logic...

    role = require_role(request, {"student", "teacher", "admin"})
    email = request.session.get("user_email")

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"File type not allowed: {file.content_type}")

    contents = await file.read()
    size_bytes = len(contents)
    if size_bytes > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File too large (max {MAX_UPLOAD_MB}MB)")

    ext = Path(file.filename).suffix.lower()
    stored_name = f"{secrets.token_hex(16)}{ext}"
    save_path = UPLOAD_DIR / stored_name

    with open(save_path, "wb") as f:
        f.write(contents)

    now = datetime.utcnow().isoformat()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO uploads (user_email, role, original_name, stored_name, content_type, size_bytes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (email, role, file.filename, stored_name, file.content_type, size_bytes, now))
    upload_id = cur.lastrowid
    conn.commit()
    conn.close()

    return {
        "ok": True,
        "upload_id": upload_id,
        "filename": file.filename,
        "content_type": file.content_type,
        "size_bytes": size_bytes
    }




@app.get("/auth/me")
def me(request: Request):
    email = request.session.get("user_email")
    role = request.session.get("role")
    if not email or not role:
        raise HTTPException(status_code=401, detail="Not logged in")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT full_name, school, class_name FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()
    return {
        "email": email,
        "role": role,
        "full_name": row["full_name"] if row else None,
        "school": row["school"] if row else None,
        "class_name": row["class_name"] if row else None,
    }


@app.get("/my-details", response_class=HTMLResponse)
def my_details_page(request: Request):
    require_role(request, {"student", "teacher", "admin", "school_admin"})
    file = FRONTEND_DIR / "my_details.html"
    return file.read_text(encoding="utf-8")


@app.post("/api/me/details")
async def update_my_details(request: Request):
    require_role(request, {"student", "teacher", "admin", "school_admin"})
    email = request.session.get("user_email")
    role = request.session.get("role")
    body = await request.json()

    full_name = (body.get("full_name") or "").strip()
    school = (body.get("school") or "").strip()
    class_name = (body.get("class_name") or "").strip()

    if len(full_name) < 2:
        raise HTTPException(status_code=400, detail="Please enter your full name")
    if not school:
        raise HTTPException(status_code=400, detail="School name is required")
    if role == "student" and not class_name:
        raise HTTPException(status_code=400, detail="Class is required for students")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET full_name = ?, school = ?, class_name = ? WHERE email = ?",
        (full_name, school, class_name or None, email),
    )
    conn.commit()
    conn.close()
    return {"ok": True}
@app.get("/student", response_class=HTMLResponse)
def student_dashboard(request: Request):
    require_role(request, {"student"})
    file = FRONTEND_DIR / "student.html"
    return file.read_text(encoding="utf-8")


@app.get("/teacher", response_class=HTMLResponse)
def teacher_dashboard(request: Request):
    require_role(request, {"teacher"})
    file = FRONTEND_DIR / "teacher.html"
    return file.read_text(encoding="utf-8")


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    require_role(request, {"admin", "school_admin"})
    file = FRONTEND_DIR / "admin.html"
    return file.read_text(encoding="utf-8")

@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(request: Request):
    require_role(request, {"admin", "school_admin"})
    file = FRONTEND_DIR / "admin_users.html"
    return file.read_text(encoding="utf-8")


@app.get("/api/admin/users")
def list_users(request: Request):
    caller_role = require_role(request, {"admin", "school_admin"})
    caller_email = request.session.get("user_email")
    conn = get_conn()
    cur = conn.cursor()

    caller_school = None
    if caller_role == "school_admin":
        cur.execute("SELECT school FROM users WHERE email = ?", (caller_email,))
        me = cur.fetchone()
        caller_school = me["school"] if me else None
        cur.execute("""SELECT email, role, email_verified, full_name, school, class_name, approval_status, admin_proof
                       FROM users WHERE school = ? ORDER BY role, email ASC""", (caller_school,))
    else:
        cur.execute("""SELECT email, role, email_verified, full_name, school, class_name, approval_status, admin_proof
                       FROM users ORDER BY role, email ASC""")

    rows = cur.fetchall()
    conn.close()
    return {
        "caller_role": caller_role,
        "caller_school": caller_school,
        "caller_email": caller_email,
        "users": [dict(r) for r in rows],
    }


@app.post("/api/admin/users")
async def create_user(request: Request):
    caller_role = require_role(request, {"admin", "school_admin"})
    caller_email = request.session.get("user_email")
    body = await request.json()

    email = (body.get("email") or "").strip().lower()
    role = (body.get("role") or "").strip().lower()
    password = body.get("password") or ""

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email is required")
    if len(password) < 12 or not re.search(r'[!@£$%^&*()\-_=+#~;:\'"<>?,./\\|\[\]{}]', password):
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters and include at least one special character")

    # School admins can only create student/teacher, and only for their own school
    if caller_role == "school_admin":
        if role not in {"student", "teacher"}:
            raise HTTPException(status_code=403, detail="School admins can only create student or teacher accounts")
        conn2 = get_conn()
        cur2 = conn2.cursor()
        cur2.execute("SELECT school FROM users WHERE email = ?", (caller_email,))
        me = cur2.fetchone()
        conn2.close()
        forced_school = me["school"] if me else None
        if not forced_school:
            raise HTTPException(status_code=403, detail="Your account has no school assigned")
    else:
        if role not in {"student", "teacher", "school_admin", "admin"}:
            raise HTTPException(status_code=400, detail="Invalid role")
        forced_school = None

    school = forced_school or (body.get("school") or "").strip() or None
    full_name = (body.get("full_name") or "").strip() or None
    class_name = (body.get("class_name") or "").strip() or None
    approval_status = "approved" if role in {"school_admin", "admin"} else "none"
    pw_hash = hash_password(password)
    token = secrets.token_urlsafe(32)

    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (email, password_hash, role, email_verified, verification_token, full_name, school, class_name, approval_status) VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?)",
            (email, pw_hash, role, token, full_name, school, class_name, approval_status),
        )
        conn.commit()
        conn.close()
    except Exception:
        raise HTTPException(status_code=400, detail="User already exists or database error")

    # Send verification email — if SMTP not configured, admin can verify manually
    try:
        base_url = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        verify_url = f"{base_url}/auth/verify?token={token}"
        send_verification_email(email, verify_url)
    except Exception as e:
        print(f"[create_user] Verification email failed: {e}. Admin can verify manually.")

    return {"ok": True}

@app.post("/auth/resend-verification")
async def resend_verification(request: Request):
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return {"ok": True}  # silent — don't reveal whether email exists

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT email_verified FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    if not row or row["email_verified"]:
        conn.close()
        return {"ok": True}  # already verified or not found — stay silent

    token = secrets.token_urlsafe(32)
    cur.execute("UPDATE users SET verification_token = ? WHERE email = ?", (token, email))
    conn.commit()
    conn.close()

    try:
        base_url = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        verify_url = f"{base_url}/auth/verify?token={token}"
        send_verification_email(email, verify_url)
    except Exception as e:
        print(f"[resend_verification] Email failed: {e}")

    return {"ok": True}


@app.get("/auth/verify", response_class=HTMLResponse)
def verify_email(token: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT email FROM users WHERE verification_token = ?", (token,))
    row = cur.fetchone()
    if not row:
        conn.close()
        file = FRONTEND_DIR / "verify.html"
        content = file.read_text(encoding="utf-8").replace("__STATUS__", "error")
        return HTMLResponse(content)
    cur.execute("UPDATE users SET email_verified = 1, verification_token = NULL WHERE verification_token = ?", (token,))
    conn.commit()
    conn.close()
    file = FRONTEND_DIR / "verify.html"
    content = file.read_text(encoding="utf-8").replace("__STATUS__", "ok")
    return HTMLResponse(content)


@app.post("/api/admin/users/verify")
async def admin_verify_user(request: Request):
    caller_role = require_role(request, {"admin", "school_admin"})
    caller_email = request.session.get("user_email")
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email required")
    conn = get_conn()
    cur = conn.cursor()
    # School admins can only verify users from their own school
    if caller_role == "school_admin":
        cur.execute("SELECT school FROM users WHERE email = ?", (caller_email,))
        me = cur.fetchone()
        caller_school = me["school"] if me else None
        cur.execute("UPDATE users SET email_verified = 1, verification_token = NULL WHERE email = ? AND school = ?", (email, caller_school))
    else:
        cur.execute("UPDATE users SET email_verified = 1, verification_token = NULL WHERE email = ?", (email,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/admin/users")
async def delete_user(request: Request):
    caller_role = require_role(request, {"admin", "school_admin"})
    caller_email = request.session.get("user_email")
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email required")
    if email == caller_email:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT role, school FROM users WHERE email = ?", (email,))
    target = cur.fetchone()
    if not target:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    if caller_role == "school_admin":
        cur.execute("SELECT school FROM users WHERE email = ?", (caller_email,))
        me = cur.fetchone()
        caller_school = me["school"] if me else None
        if target["school"] != caller_school:
            conn.close()
            raise HTTPException(status_code=403, detail="You can only delete users from your own school")
        if target["role"] in {"admin", "school_admin"}:
            conn.close()
            raise HTTPException(status_code=403, detail="You cannot delete admin accounts")

    # Cascade delete linked data
    cur.execute("SELECT id FROM submissions WHERE user_email = ?", (email,))
    sub_ids = [r["id"] for r in cur.fetchall()]
    if sub_ids:
        ph = ",".join("?" * len(sub_ids))
        cur.execute(f"DELETE FROM teacher_reviews WHERE submission_id IN ({ph})", sub_ids)
        cur.execute(f"DELETE FROM feedback WHERE submission_id IN ({ph})", sub_ids)
        cur.execute(f"DELETE FROM uploads WHERE submission_id IN ({ph})", sub_ids)
    cur.execute("DELETE FROM submissions WHERE user_email = ?", (email,))
    cur.execute("DELETE FROM uploads WHERE user_email = ?", (email,))
    cur.execute("DELETE FROM password_reset_tokens WHERE user_email = ?", (email,))
    cur.execute("DELETE FROM users WHERE email = ?", (email,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/admin/school-admin/review")
async def review_school_admin(request: Request):
    require_role(request, {"admin"})  # platform admin only
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    action = (body.get("action") or "").strip()  # "approve" or "reject"

    if action not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Action must be approve or reject")
    if not email:
        raise HTTPException(status_code=400, detail="Email required")

    conn = get_conn()
    cur = conn.cursor()
    if action == "approve":
        cur.execute("UPDATE users SET approval_status = 'approved', email_verified = 1 WHERE email = ? AND role = 'school_admin'", (email,))
    else:
        cur.execute("UPDATE users SET approval_status = 'rejected' WHERE email = ? AND role = 'school_admin'", (email,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/admin/transfer-ownership")
async def transfer_ownership(request: Request):
    require_role(request, {"admin"})
    caller_email = request.session.get("user_email")
    body = await request.json()
    recipient_email = (body.get("email") or "").strip().lower()

    if not recipient_email:
        raise HTTPException(status_code=400, detail="Recipient email required")
    if recipient_email == caller_email:
        raise HTTPException(status_code=400, detail="You cannot transfer ownership to yourself")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT role, approval_status FROM users WHERE email = ?", (recipient_email,))
    recipient = cur.fetchone()
    if not recipient:
        conn.close()
        raise HTTPException(status_code=404, detail="Recipient account not found")
    if recipient["role"] not in {"school_admin"}:
        conn.close()
        raise HTTPException(status_code=400, detail="Recipient must be an approved school admin")
    if recipient["approval_status"] != "approved":
        conn.close()
        raise HTTPException(status_code=400, detail="Recipient must have an approved account")

    # Transfer: recipient → admin, old admin → school_admin
    cur.execute("UPDATE users SET role = 'admin', approval_status = 'approved' WHERE email = ?", (recipient_email,))
    cur.execute("UPDATE users SET role = 'school_admin', approval_status = 'approved' WHERE email = ?", (caller_email,))
    conn.commit()
    conn.close()

    # Force logout so new role takes effect on next login
    request.session.clear()
    return {"ok": True}


# Rubrics & Submissions

@app.get("/api/rubrics")
def get_rubrics(request: Request):
    role = require_role(request, {"student", "teacher", "admin", "school_admin"})
    email = request.session.get("user_email")
    conn = get_conn()
    cur = conn.cursor()
    if role == "admin":
        cur.execute("SELECT id, title FROM rubrics ORDER BY id DESC")
    else:
        cur.execute("SELECT school FROM users WHERE email = ?", (email,))
        me = cur.fetchone()
        school = me["school"] if me else None
        cur.execute("SELECT id, title FROM rubrics WHERE school = ? ORDER BY id DESC", (school,))
    rows = cur.fetchall()
    conn.close()
    return {"rubrics": [{"id": r["id"], "title": r["title"]} for r in rows]}




@app.post("/api/submissions")
async def create_submission(request: Request):
    require_role(request, {"student"})
    body = await request.json()

    rubric_id = body.get("rubric_id")
    submission_text = (body.get("submission_text") or "").strip()

    attachment_ids = body.get("attachment_ids") or []
    if not isinstance(attachment_ids, list):
        raise HTTPException(status_code=400, detail="attachment_ids must be a list")

    if not rubric_id:
        raise HTTPException(status_code=400, detail="rubric_id is required")
    has_attachments = bool(attachment_ids)
    if not has_attachments and len(submission_text) < 20:
        raise HTTPException(status_code=400, detail="Please either attach a file or write at least 20 characters of text")

    # Load rubric criteria
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT criteria_json FROM rubrics WHERE id = ?", (rubric_id,))
    r = cur.fetchone()
    if not r:
        conn.close()
        raise HTTPException(status_code=404, detail="Rubric not found")
    criteria = json.loads(r["criteria_json"])

    # Insert submission
    email = request.session.get("user_email")
    now = datetime.utcnow().isoformat()
    cur.execute(
        "INSERT INTO submissions (user_email, rubric_id, submission_text, created_at) VALUES (?, ?, ?, ?)",
        (email, rubric_id, submission_text, now),
    )
    submission_id = cur.lastrowid

    # Link attachments to this submission if any and links to same user
    attachment_info = []
    if attachment_ids:
        placeholders = ",".join(["?"] * len(attachment_ids))
        cur.execute(
            f"""
            UPDATE uploads
            SET submission_id = ?
            WHERE id IN ({placeholders})
              AND user_email = ?
            """,
            (submission_id, *attachment_ids, email),
        )

        if cur.rowcount != len(attachment_ids):
            raise HTTPException(status_code=403, detail="One or more attachments not found / not yours")

        # Pull stored file details so we can pass them to the feedback pipeline
        cur.execute(
            f"""
            SELECT stored_name, original_name, content_type
            FROM uploads
            WHERE id IN ({placeholders})
              AND user_email = ?
            """,
            (*attachment_ids, email),
        )
        for row in cur.fetchall():
            attachment_info.append({
                "path": str(UPLOAD_DIR / row["stored_name"]),
                "original_name": row["original_name"],
                "content_type": row["content_type"],
            })

    # Generate and store feedback - attachments (if any) are sent to Gemini for vision
    rubric_data = {"title": None, "criteria": criteria}
    # Pull the rubric title for a richer prompt
    cur.execute("SELECT title FROM rubrics WHERE id = ?", (rubric_id,))
    tr = cur.fetchone()
    if tr:
        rubric_data["title"] = tr["title"]

    feedback = generate_feedback(submission_text, rubric_data, attachments=attachment_info)
    cur.execute(
        "INSERT INTO feedback (submission_id, feedback_json, created_at) VALUES (?, ?, ?)",
        (submission_id, json.dumps(feedback), now),
    )

    conn.commit()
    conn.close()

    return {"ok": True, "submission_id": submission_id, "attachment_ids": attachment_ids}


@app.get("/api/submissions/me")
def my_submissions(request: Request):
    require_role(request, {"student"})
    email = request.session.get("user_email")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id, s.created_at, r.title as rubric_title
        FROM submissions s
        JOIN rubrics r ON r.id = s.rubric_id
        WHERE s.user_email = ?
        ORDER BY s.id DESC
    """, (email,))
    rows = cur.fetchall()
    conn.close()

    return {"submissions": [
        {"id": row["id"], "created_at": row["created_at"], "rubric_title": row["rubric_title"]}
        for row in rows
    ]}


@app.get("/api/submissions/{submission_id}")
def get_submission(request: Request, submission_id: int):
    role = require_role(request, {"student", "teacher", "admin"})
    email = request.session.get("user_email")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id, s.user_email, s.submission_text, s.created_at, r.title as rubric_title
        FROM submissions s
        JOIN rubrics r ON r.id = s.rubric_id
        WHERE s.id = ?
    """, (submission_id,))
    s = cur.fetchone()

    if not s:
        conn.close()
        raise HTTPException(status_code=404, detail="Submission not found")

    # Students can only view their own
    if role == "student" and s["user_email"] != email:
        conn.close()
        raise HTTPException(status_code=403, detail="Forbidden")

    cur.execute("SELECT feedback_json FROM feedback WHERE submission_id = ?", (submission_id,))
    f = cur.fetchone()
    conn.close()

    feedback = json.loads(f["feedback_json"]) if f else None

    return {
        "id": s["id"],
        "user_email": s["user_email"],
        "rubric_title": s["rubric_title"],
        "created_at": s["created_at"],
        "submission_text": s["submission_text"],
        "feedback": feedback
    }


@app.get("/api/teacher/submissions")
def teacher_submissions(request: Request):
    require_role(request, {"teacher", "admin"})

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id, s.user_email, s.created_at, r.title as rubric_title
        FROM submissions s
        JOIN rubrics r ON r.id = s.rubric_id
        ORDER BY s.id DESC
    """)
    rows = cur.fetchall()
    conn.close()

    return {"submissions": [
        {"id": row["id"], "user_email": row["user_email"], "created_at": row["created_at"], "rubric_title": row["rubric_title"]}
        for row in rows
    ]}
@app.get("/api/teacher/review/{submission_id}")
def get_teacher_review(request: Request, submission_id: int):
    require_role(request, {"teacher", "admin"})
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT submission_id, flagged, note, updated_at FROM teacher_reviews WHERE submission_id = ?",
        (submission_id,),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return {"submission_id": submission_id, "flagged": 0, "note": "", "updated_at": None}

    return {
        "submission_id": row["submission_id"],
        "flagged": int(row["flagged"] or 0),
        "note": row["note"] or "",
        "updated_at": row["updated_at"],
    }


@app.post("/api/teacher/review/{submission_id}")
async def save_teacher_review(request: Request, submission_id: int):
    require_role(request, {"teacher", "admin"})
    body = await request.json()

    flagged = 1 if body.get("flagged") else 0
    note = (body.get("note") or "").strip()
    if len(note) > 2000:
        raise HTTPException(status_code=400, detail="Note too long (max 2000 chars)")

    now = datetime.utcnow().isoformat()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO teacher_reviews (submission_id, flagged, note, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(submission_id) DO UPDATE SET
          flagged=excluded.flagged,
          note=excluded.note,
          updated_at=excluded.updated_at
    """, (submission_id, flagged, note, now))
    conn.commit()
    conn.close()

    return {"ok": True}



# Admin: Rubrics + Analytics

@app.get("/api/admin/analytics")
def admin_analytics(request: Request):
    role = require_role(request, {"admin", "school_admin"})
    email = request.session.get("user_email")
    conn = get_conn()
    cur = conn.cursor()

    if role == "school_admin":
        cur.execute("SELECT school FROM users WHERE email = ?", (email,))
        me = cur.fetchone()
        school = me["school"] if me else None
        cur.execute("SELECT COUNT(*) as c FROM users WHERE school = ?", (school,))
        users_count = cur.fetchone()["c"]
        cur.execute("""
            SELECT COUNT(*) as c FROM submissions s
            JOIN users u ON u.email = s.user_email WHERE u.school = ?
        """, (school,))
        submissions_count = cur.fetchone()["c"]
        cur.execute("""
            SELECT r.title, COUNT(*) as c
            FROM submissions s
            JOIN users u ON u.email = s.user_email
            JOIN rubrics r ON r.id = s.rubric_id
            WHERE u.school = ?
            GROUP BY r.title ORDER BY c DESC LIMIT 1
        """, (school,))
    else:
        cur.execute("SELECT COUNT(*) as c FROM users")
        users_count = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) as c FROM submissions")
        submissions_count = cur.fetchone()["c"]
        cur.execute("""
            SELECT r.title, COUNT(*) as c
            FROM submissions s
            JOIN rubrics r ON r.id = s.rubric_id
            GROUP BY r.title ORDER BY c DESC LIMIT 1
        """)

    top = cur.fetchone()
    top_rubric = {"title": top["title"], "count": top["c"]} if top else None
    conn.close()

    return {
        "users_count": users_count,
        "submissions_count": submissions_count,
        "top_rubric": top_rubric
    }


@app.get("/api/admin/rubrics")
def admin_list_rubrics(request: Request):
    role = require_role(request, {"admin", "school_admin"})
    email = request.session.get("user_email")
    conn = get_conn()
    cur = conn.cursor()
    if role == "admin":
        cur.execute("SELECT id, title, school FROM rubrics ORDER BY id DESC")
    else:
        cur.execute("SELECT school FROM users WHERE email = ?", (email,))
        me = cur.fetchone()
        school = me["school"] if me else None
        cur.execute("SELECT id, title, school FROM rubrics WHERE school = ? ORDER BY id DESC", (school,))
    rows = cur.fetchall()
    conn.close()
    return {"rubrics": [{"id": r["id"], "title": r["title"], "school": r["school"]} for r in rows]}


@app.post("/api/admin/rubrics")
async def admin_create_rubric(request: Request):
    role = require_role(request, {"admin", "school_admin"})
    email = request.session.get("user_email")
    body = await request.json()

    title = (body.get("title") or "").strip()
    criteria = body.get("criteria")  # expects array of objects

    if len(title) < 3:
        raise HTTPException(status_code=400, detail="Title must be at least 3 characters")
    if not isinstance(criteria, list) or len(criteria) < 1:
        raise HTTPException(status_code=400, detail="Criteria must be a non-empty list")

    # basic validation
    cleaned = []
    for c in criteria:
        name = (c.get("name") or "").strip()
        desc = (c.get("description") or "").strip()
        if len(name) < 2 or len(desc) < 3:
            raise HTTPException(status_code=400, detail="Each criterion needs name + description")
        cleaned.append({"name": name, "description": desc})

    conn = get_conn()
    cur = conn.cursor()
    if role == "admin":
        rubric_school = None
    else:
        cur.execute("SELECT school FROM users WHERE email = ?", (email,))
        me = cur.fetchone()
        rubric_school = me["school"] if me else None
    cur.execute(
        "INSERT INTO rubrics (title, criteria_json, school) VALUES (?, ?, ?)",
        (title, json.dumps(cleaned), rubric_school),
    )
    conn.commit()
    conn.close()

    return {"ok": True}


def _get_caller_school(cur, email: str):
    cur.execute("SELECT school FROM users WHERE email = ?", (email,))
    me = cur.fetchone()
    return me["school"] if me else None


def _check_rubric_access(cur, rubric_id: int, role: str, caller_school: str):
    """Return rubric row or raise 404/403."""
    cur.execute("SELECT id, title, criteria_json, school FROM rubrics WHERE id = ?", (rubric_id,))
    r = cur.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Rubric not found")
    if role == "school_admin" and r["school"] != caller_school:
        raise HTTPException(status_code=403, detail="You can only modify rubrics belonging to your school")
    return r


@app.get("/api/admin/rubrics/{rubric_id}")
def admin_get_rubric(request: Request, rubric_id: int):
    role = require_role(request, {"admin", "school_admin"})
    email = request.session.get("user_email")
    conn = get_conn()
    cur = conn.cursor()
    caller_school = None if role == "admin" else _get_caller_school(cur, email)
    r = _check_rubric_access(cur, rubric_id, role, caller_school)
    conn.close()
    return {"id": r["id"], "title": r["title"], "criteria": json.loads(r["criteria_json"])}


@app.put("/api/admin/rubrics/{rubric_id}")
async def admin_update_rubric(request: Request, rubric_id: int):
    role = require_role(request, {"admin", "school_admin"})
    email = request.session.get("user_email")
    body = await request.json()
    title = (body.get("title") or "").strip()
    criteria = body.get("criteria")
    if len(title) < 3:
        raise HTTPException(status_code=400, detail="Title must be at least 3 characters")
    if not isinstance(criteria, list) or len(criteria) < 1:
        raise HTTPException(status_code=400, detail="Criteria must be a non-empty list")
    cleaned = []
    for c in criteria:
        name = (c.get("name") or "").strip()
        desc = (c.get("description") or "").strip()
        if len(name) < 2 or len(desc) < 3:
            raise HTTPException(status_code=400, detail="Each criterion needs name + description")
        cleaned.append({"name": name, "description": desc})
    conn = get_conn()
    cur = conn.cursor()
    caller_school = None if role == "admin" else _get_caller_school(cur, email)
    _check_rubric_access(cur, rubric_id, role, caller_school)
    cur.execute("UPDATE rubrics SET title = ?, criteria_json = ? WHERE id = ?",
                (title, json.dumps(cleaned), rubric_id))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/admin/rubrics/{rubric_id}")
async def admin_delete_rubric(request: Request, rubric_id: int):
    role = require_role(request, {"admin", "school_admin"})
    email = request.session.get("user_email")
    conn = get_conn()
    cur = conn.cursor()
    caller_school = None if role == "admin" else _get_caller_school(cur, email)
    _check_rubric_access(cur, rubric_id, role, caller_school)
    cur.execute("SELECT COUNT(*) as c FROM submissions WHERE rubric_id = ?", (rubric_id,))
    if cur.fetchone()["c"] > 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Cannot delete a rubric that has existing submissions linked to it")
    cur.execute("DELETE FROM rubrics WHERE id = ?", (rubric_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/admin/rubrics", response_class=HTMLResponse)
def admin_rubrics_page(request: Request):
    require_role(request, {"admin", "school_admin"})
    file = FRONTEND_DIR / "admin_rubrics.html"
    return file.read_text(encoding="utf-8")


# Chat CoPilot - guardrails here, reply generation handled in chat_pipeline.py

def basic_guardrails(message: str) -> str:
    """
    First-pass input guardrail. Blocks obviously unsafe topics and keeps
    messages within a sensible length before they reach the LLM.
    """
    msg = (message or "").strip()
    if len(msg) == 0:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if len(msg) > 800:
        raise HTTPException(status_code=400, detail="Message too long (max 800 characters)")

    banned = ["suicide", "self harm", "kill myself", "porn", "nudes"]
    lowered = msg.lower()
    if any(b in lowered for b in banned):
        return "I can’t help with that. Please talk to a trusted adult or teacher. If you are in danger, contact emergency services."

    return msg



@app.post("/api/chat")
async def chat(request: Request):
    role = require_role(request, {"student", "teacher", "admin"})
    body = await request.json()

    attachment_ids = body.get("attachment_ids") or []
    if not isinstance(attachment_ids, list):
        raise HTTPException(status_code=400, detail="attachment_ids must be a list")

    rows = []
    if attachment_ids:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(f"""
            SELECT id, original_name, content_type, stored_name
            FROM uploads
            WHERE id IN ({",".join(["?"]*len(attachment_ids))})
              AND user_email = ?
        """, (*attachment_ids, request.session.get("user_email")))
        rows = cur.fetchall()
        conn.close()

        if len(rows) != len(attachment_ids):
            raise HTTPException(status_code=403, detail="One or more attachments not found / not yours")

    # context always exists now
    context = {}
    if rows:
        context["attachments"] = [
            {
                "id": r["id"],
                "name": r["original_name"],
                "original_name": r["original_name"],
                "type": r["content_type"],
                "content_type": r["content_type"],
                "stored": r["stored_name"],
                "path": str(UPLOAD_DIR / r["stored_name"]),
            }
            for r in rows
        ]

    mode = (body.get("mode") or "").strip().lower()
    message = basic_guardrails(body.get("message") or "")

    if mode not in {"general", "feedback", "teacher"}:
        raise HTTPException(status_code=400, detail="Invalid mode")

    if mode == "teacher" and role == "student":
        raise HTTPException(status_code=403, detail="Teacher chat is not available for students")

    if mode == "feedback":
        submission_id = body.get("submission_id")
        if not submission_id:
            raise HTTPException(status_code=400, detail="submission_id is required for feedback mode")
        if role != "student":
            raise HTTPException(status_code=403, detail="Feedback mode chat is only available for students")

        email = request.session.get("user_email")
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT s.id, s.user_email, s.submission_text, s.created_at, r.title as rubric_title
            FROM submissions s
            JOIN rubrics r ON r.id = s.rubric_id
            WHERE s.id = ?
        """, (submission_id,))
        s = cur.fetchone()
        if not s:
            conn.close()
            raise HTTPException(status_code=404, detail="Submission not found")
        if s["user_email"] != email:
            conn.close()
            raise HTTPException(status_code=403, detail="Forbidden")

        cur.execute("SELECT feedback_json FROM feedback WHERE submission_id = ?", (submission_id,))
        f = cur.fetchone()
        conn.close()

        feedback = json.loads(f["feedback_json"]) if f else None

        # feedback merged into context for more informed responses
        context.update({
            "rubric_title": s["rubric_title"],
            "submission_text": s["submission_text"],
            "feedback": feedback,
        })

    reply = generate_chat_reply(mode, message, context)
    return {"ok": True, "reply": reply}