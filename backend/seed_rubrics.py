import json
from db import init_db, get_conn

RUBRICS = [
    {
        "title": "Entrepreneurship Pitch Rubric",
        "criteria": [
            {"name": "Clarity of Idea", "description": "Is the idea explained clearly and logically?"},
            {"name": "Problem & Solution Fit", "description": "Does the solution address a real problem?"},
            {"name": "Evidence & Examples", "description": "Are there examples, data, or reasoning to support claims?"},
            {"name": "Communication", "description": "Is the writing easy to follow and age-appropriate?"},
        ],
    },
    {
        "title": "Financial Literacy Reflection Rubric",
        "criteria": [
            {"name": "Understanding", "description": "Shows understanding of key financial concepts."},
            {"name": "Application", "description": "Applies concepts to real-life examples or scenarios."},
            {"name": "Reasoning", "description": "Explains decisions with clear reasoning."},
            {"name": "Reflection", "description": "Identifies what was learned and what could improve."},
        ],
    },
]

def seed():
    init_db()
    conn = get_conn()
    cur = conn.cursor()

    
    cur.execute("SELECT COUNT(*) as c FROM rubrics")
    if cur.fetchone()["c"] > 0:
        print("Rubrics already exist — skipping seeding.")
        conn.close()
        return

    for r in RUBRICS:
        cur.execute(
            "INSERT INTO rubrics (title, criteria_json) VALUES (?, ?)",
            (r["title"], json.dumps(r["criteria"])),
        )

    conn.commit()
    conn.close()
    print("Rubrics seeded ")

if __name__ == "__main__":
    seed()
