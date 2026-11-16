"""Launch a local CampusShare demo with persistent, fictional data."""
import os
from pathlib import Path

import uvicorn

from backend import database, initialize, log, password_hash

# Title, subject, course, semester, category, tags, original study prompt.
MATERIALS = [
    ("CMOS inverter worksheet", "Digital IC Design", "ENTC", 4, "Lecture notes", "CMOS, inverter",
     "Draw a PMOS pull-up and an NMOS pull-down. Complete a truth table for input levels 0 and 1."),
    ("Round-robin scheduling lab", "Operating Systems", "Computer Engineering", 4, "Lab manuals", "RTOS, scheduling",
     "Three jobs arrive together with bursts of 4, 3 and 2 ticks. Use a two-tick quantum. Draw the timeline and compute each waiting time."),
    ("Fourier series practice paper", "Signals and Systems", "ENTC", 3, "Question papers", "Fourier, signals",
     "Sketch an odd periodic square wave. Decide which Fourier coefficients vanish by symmetry and explain why."),
    ("I2C sensor bus checklist", "Embedded Systems", "ENTC", 5, "References", "I2C, sensors",
     "Label SDA, SCL and the common ground on a two-device bus. Explain the role of pull-up resistors."),
    ("Library database design", "Database Systems", "Computer Engineering", 4, "Lab manuals", "SQL, keys",
     "Design tables for books, borrowers and loans. Choose keys and write a query listing all overdue books."),
    ("Agile sprint review outline", "Software Engineering", "Computer Engineering", 5, "Presentations", "Agile, testing",
     "Slide 1: Sprint goal. Slide 2: Demonstrate one accepted story. Slide 3: Show a failed test and the change that fixed it."),
    ("Feedback control revision", "Control Systems", "ENTC", 4, "Lecture notes", "feedback, stability",
     "Sketch a negative-feedback loop with unity feedback. Derive the closed-loop transfer function from its block diagram."),
    ("Logic gates practice set", "Digital Logic", "ENTC", 2, "Question papers", "NAND, logic",
     "Implement an inverter with a NAND gate. Then build a two-input OR gate using only NAND gates."),
    ("Network trace exercises", "Computer Networks", "Computer Engineering", 5, "Lab manuals", "latency, packets",
     "Use example round-trip times of 12, 18, 15 and 19 ms. Compute the mean and discuss why packet delays vary."),
    ("Sampling theory revision draft", "Signals and Systems", "ENTC", 3, "Lecture notes", "sampling, draft",
     "Draft exercise: determine the minimum sampling rate for a band-limited signal. The signal bandwidth is missing from this version."),
]


def seed():
    initialize()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS demo_seed(version INTEGER PRIMARY KEY)")
        if db.execute("SELECT 1 FROM demo_seed WHERE version=1").fetchone():
            return
        if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise RuntimeError("The selected database already contains accounts and is not a seeded demo.")
        accounts = [
            ("admin", "Demo Moderator", "CampusAdmin42!", 1),
            ("student", "Asha Demo", "CampusStudent42!", 0),
            ("owner", "Ravi Demo", "CampusOwner42!", 0),
        ]
        ids = {}
        for role, name, password, admin in accounts:
            ids[role] = db.execute("INSERT INTO users(email,name,password,admin) VALUES(?,?,?,?)",
                                   (role+"@campus.example", name, password_hash(password), admin)).lastrowid
        categories = {row["name"]: row["id"] for row in db.execute("SELECT * FROM categories")}
        resources = []
        for i, (title, subject, course, semester, category, tags, prompt) in enumerate(MATERIALS):
            author = ids["student"] if i in (3, 6) else ids["owner"]
            rid = db.execute("""INSERT INTO resources(owner,title,subject,course,semester,category,
                description,tags,kind,restricted,downloads) VALUES(?,?,?,?,?,?,?,?,'TXT',?,?)""",
                (author,title,subject,course,semester,categories[category],prompt,tags,i==1,i%4)).lastrowid
            resources.append(rid)
            content = f"{title}\n{subject} | Semester {semester}\n\n{prompt}\n"
            db.execute("INSERT INTO files VALUES(?,?)",(rid,content.encode()))
            log(db,author,"Uploaded",rid)
        for rid in (resources[0],resources[2]):
            db.execute("INSERT INTO bookmarks VALUES(?,?)",(ids["student"],rid))
        db.execute("INSERT INTO reviews VALUES(?,?,?,?)",(ids["student"],resources[0],5,"The truth-table exercise helped me revise."))
        db.execute("INSERT INTO requests(user,resource) VALUES(?,?)",(ids["student"],resources[1]))
        reported = resources[-1]
        db.execute("INSERT INTO reports(user,resource,reason) VALUES(?,?,?)",
                   (ids["student"],reported,"The sampling question omits the signal bandwidth."))
        db.execute("UPDATE resources SET status='Under Review' WHERE id=?",(reported,))
        log(db,ids["student"],"Reported",reported)
        db.execute("INSERT INTO demo_seed VALUES(1)")


if __name__ == "__main__":
    os.environ["CAMPUS_DB"] = str(Path(__file__).resolve().parent / "data" / "local-demo.sqlite3")
    seed()
    print("Administrator: http://127.0.0.1:8000/admin/login  admin@campus.example  CampusAdmin42!")
    print("Student: http://127.0.0.1:8000/login  student@campus.example  CampusStudent42!")
    uvicorn.run("app:app", host="127.0.0.1", port=8000)
