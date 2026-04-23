import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "app.db"

def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        email_verified INTEGER NOT NULL DEFAULT 0,
        verification_token TEXT,
        full_name TEXT,
        school TEXT,
        class_name TEXT,
        approval_status TEXT NOT NULL DEFAULT 'none',
        admin_proof TEXT
    )
    """)

    # Migration: recreate table if approval_status column doesn't exist yet
    try:
        cur.execute("SELECT approval_status FROM users LIMIT 1")
    except Exception:
        cur.execute("""
            CREATE TABLE users_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                email_verified INTEGER NOT NULL DEFAULT 0,
                verification_token TEXT,
                full_name TEXT,
                school TEXT,
                class_name TEXT,
                approval_status TEXT NOT NULL DEFAULT 'none',
                admin_proof TEXT
            )
        """)
        cur.execute("""
            INSERT INTO users_v2 (id, email, password_hash, role, email_verified, verification_token, full_name, school, class_name, approval_status)
            SELECT id, email, password_hash, role, email_verified, verification_token, full_name, school, class_name,
                   CASE WHEN role = 'admin' THEN 'approved' ELSE 'none' END
            FROM users
        """)
        cur.execute("DROP TABLE users")
        cur.execute("ALTER TABLE users_v2 RENAME TO users")
        # Re-verify existing users so they aren't locked out
        cur.execute("UPDATE users SET email_verified = 1 WHERE email_verified = 0 AND verification_token IS NULL")


    cur.execute("""
    CREATE TABLE IF NOT EXISTS password_reset_tokens (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_email TEXT NOT NULL,
      token_hash TEXT NOT NULL,
      expires_at TEXT NOT NULL,
      used_at TEXT,
      created_at TEXT NOT NULL,
      FOREIGN KEY (user_email) REFERENCES users(email)
    )
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_hash
    ON password_reset_tokens(token_hash)
    """)
    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user
    ON password_reset_tokens(user_email)
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS rubrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        criteria_json TEXT NOT NULL,
        school TEXT
    )
    """)

    # Migration: add school column to rubrics if missing
    try:
        cur.execute("SELECT school FROM rubrics LIMIT 1")
    except Exception:
        cur.execute("ALTER TABLE rubrics ADD COLUMN school TEXT")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT NOT NULL,
        rubric_id INTEGER NOT NULL,
        submission_text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (rubric_id) REFERENCES rubrics(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        submission_id INTEGER NOT NULL,
        feedback_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (submission_id) REFERENCES submissions(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS teacher_reviews (
        submission_id INTEGER PRIMARY KEY,
        flagged INTEGER DEFAULT 0,
        note TEXT DEFAULT '',
        updated_at TEXT,
        FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS uploads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT NOT NULL,
        role TEXT NOT NULL,
        submission_id INTEGER,
        original_name TEXT NOT NULL,
        stored_name TEXT NOT NULL,
        content_type TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (submission_id) REFERENCES submissions(id)
    )
    """)

    conn.commit()
    conn.close()
