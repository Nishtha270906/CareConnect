"""Create a clearly synthetic demonstration dataset for the CareConnect prototype.

Run from the project folder with: python seed_demo_data.py
Safe to run more than once: a marker prevents duplicate demo records.
"""
import random
import sqlite3
from datetime import date, timedelta

from app import DB_PATH, init_db

RNG = random.Random(20261101)

CHILD_NAMES = [
    "Aarav Mehta", "Anaya Sharma", "Vihaan Rao", "Ira Kapoor", "Kabir Verma",
    "Myra Singh", "Reyansh Patel", "Aadhya Nair", "Advait Joshi", "Saanvi Das",
    "Arjun Malhotra", "Kiara Gill", "Dhruv Khanna", "Tara Iyer", "Ishaan Roy",
    "Navya Bansal", "Rohan Sethi", "Meera Shah", "Atharv Jain", "Pari Menon",
    "Dev Arora", "Riya Bose", "Krish Anand", "Aanya Kulkarni", "Neil Thomas",
    "Zoya Khan", "Yuvaan Reddy", "Diya Chawla", "Samarth Mishra", "Avni Gupta",
]
GUARDIAN_NAMES = [
    "R. Mehta", "S. Sharma", "A. Rao", "P. Kapoor", "N. Verma", "M. Singh",
    "K. Patel", "V. Nair", "S. Joshi", "A. Das", "P. Malhotra", "G. Gill",
    "R. Khanna", "L. Iyer", "D. Roy", "A. Bansal", "M. Sethi", "N. Shah",
    "S. Jain", "R. Menon", "K. Arora", "T. Bose", "P. Anand", "S. Kulkarni",
    "J. Thomas", "F. Khan", "V. Reddy", "H. Chawla", "A. Mishra", "D. Gupta",
]
ACTIVITIES = [
    ("Story Circle", "Creative", "Group storytelling and turn-taking practice"),
    ("Number Games", "Learning", "Hands-on counting and number recognition"),
    ("Colour and Craft", "Creative", "Guided art and craft activity"),
    ("Movement and Music", "Physical", "Inclusive movement and rhythm activities"),
    ("Team Puzzle Challenge", "Social", "Small-group problem-solving activity"),
    ("Everyday Skills Practice", "Life skills", "Sequencing common daily routines"),
    ("Picture Reading", "Learning", "Picture-based reading and vocabulary"),
    ("Garden Explorers", "Physical", "Supervised nature observation activity"),
    ("Building Together", "Social", "Collaborative block-building activity"),
    ("Creative Expression", "Creative", "Choice-based drawing and creative work"),
]
SESSION_CATEGORIES = [
    "Learning support", "Communication support", "Social participation",
    "Daily living skills", "Other",
]


def main():
    init_db()  # Creates the normal app tables and default admin if needed.
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS demo_seed_log (
            seed_name TEXT PRIMARY KEY,
            seeded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        if db.execute("SELECT 1 FROM demo_seed_log WHERE seed_name='careconnect_demo_v1'").fetchone():
            print("Demo dataset is already installed. No changes were made.")
            return

        admin = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()
        admin_id = admin[0] if admin else None
        today = date.today()
        start = today - timedelta(days=89)

        # 30 entirely fictional profiles. No phone numbers or sensitive diagnoses are used.
        child_ids = []
        for index, (name, guardian) in enumerate(zip(CHILD_NAMES, GUARDIAN_NAMES), start=1):
            code = f"CC-DEMO-{index:03d}"
            db.execute("""INSERT OR IGNORE INTO children
                (child_code, full_name, age, guardian_name, guardian_contact, enrollment_date, status, notes)
                VALUES (?, ?, ?, ?, '', ?, 'Active', ?)""",
                (code, name, RNG.randint(6, 17), guardian,
                 (start + timedelta(days=RNG.randint(0, 25))).isoformat(),
                 "Synthetic demonstration profile; no real personal or health information."))
            row = db.execute("SELECT id FROM children WHERE child_code=?", (code,)).fetchone()
            child_ids.append(row[0])

        # Daily sample attendance over the previous 90 calendar days, including today.
        # Different attendance tendencies make reports and charts more illustrative.
        attendance_rates = [0.96, 0.91, 0.87, 0.82, 0.76, 0.68]
        for child_index, child_id in enumerate(child_ids):
            rate = attendance_rates[child_index % len(attendance_rates)]
            for day_offset in range(90):
                record_date = start + timedelta(days=day_offset)
                roll = RNG.random()
                if roll < rate:
                    status = "Present"
                elif roll < rate + 0.04:
                    status = "Leave"
                else:
                    status = "Absent"
                db.execute("""INSERT OR IGNORE INTO attendance
                    (child_id, attendance_date, status, marked_by) VALUES (?, ?, ?, ?)""",
                    (child_id, record_date.isoformat(), status, admin_id))

        # Ten dated activities distributed across the demonstration period.
        activity_ids = []
        for index, (title, category, description) in enumerate(ACTIVITIES):
            activity_date = start + timedelta(days=8 + index * 8)
            db.execute("INSERT INTO activities(title, category, activity_date, description) VALUES (?, ?, ?, ?)",
                       (title, category, activity_date.isoformat(), description + " (synthetic demo record)"))
            activity_ids.append(db.execute("SELECT last_insert_rowid()").fetchone()[0])

        # 12–20 participants per activity, with varied participation outcomes.
        participation_statuses = ["Participated", "Partially participated", "Observed"]
        for activity_id in activity_ids:
            selected = RNG.sample(child_ids, RNG.randint(12, 20))
            for child_id in selected:
                db.execute("""INSERT OR IGNORE INTO participation
                    (activity_id, child_id, status, observation) VALUES (?, ?, ?, ?)""",
                    (activity_id, child_id, RNG.choices(participation_statuses, weights=[7, 2, 1])[0],
                     "Synthetic example observation for dashboard demonstration."))

        # Fifty sample support-session records with neutral, non-clinical categories.
        for _ in range(50):
            child_id = RNG.choice(child_ids)
            session_date = start + timedelta(days=RNG.randint(0, 89))
            category = RNG.choice(SESSION_CATEGORIES)
            duration = RNG.choice([15, 20, 25, 30, 40, 45])
            db.execute("""INSERT INTO support_sessions
                (child_id, session_date, category, duration_minutes, staff_id, observation)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (child_id, session_date.isoformat(), category, duration, admin_id,
                 "Synthetic demonstration entry; replace with authorized records only."))

        db.execute("INSERT INTO demo_seed_log(seed_name) VALUES ('careconnect_demo_v1')")
        db.commit()
        print("CareConnect synthetic demo dataset added successfully.")
        print(f"Children: {len(child_ids)}")
        print("Attendance: up to 2,700 records across the last 90 days")
        print("Activities: 10")
        print("Participation: varies by activity (approximately 120–200 records)")
        print("Support sessions: 50")
        print("All generated records are fictional demonstration data.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
