from db import init_db, get_conn
from security import hash_password

DEMO_USERS = [
    ("student@demo.com", "password123", "student"),
    ("teacher@demo.com", "password123", "teacher"),
    ("admin@demo.com", "password123", "admin"),
]

def seed():
    init_db()
    conn = get_conn()
    cur = conn.cursor()

    for email, pw, role in DEMO_USERS:
        pw_hash = hash_password(pw)
        cur.execute(
            "INSERT OR IGNORE INTO users (email, password_hash, role) VALUES (?, ?, ?)",
            (email.lower(), pw_hash, role),
        )

    conn.commit()
    conn.close()
    print("Seed complete ")

if __name__ == "__main__":
    seed()
