import os, csv, io, sqlite3
from datetime import date, datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, make_response, abort
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "instance", "ngo.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "local-demo-change-this-secret")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False  # Local HTTP demo only
csrf = CSRFProtect(app)

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('admin','staff')),
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS children (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      child_code TEXT UNIQUE NOT NULL,
      full_name TEXT NOT NULL,
      age INTEGER,
      guardian_name TEXT,
      guardian_contact TEXT,
      enrollment_date TEXT,
      status TEXT NOT NULL DEFAULT 'Active',
      notes TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS attendance (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      child_id INTEGER NOT NULL REFERENCES children(id) ON DELETE CASCADE,
      attendance_date TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('Present','Absent','Leave')),
      marked_by INTEGER REFERENCES users(id),
      UNIQUE(child_id, attendance_date)
    );
    CREATE TABLE IF NOT EXISTS activities (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      category TEXT NOT NULL,
      activity_date TEXT NOT NULL,
      description TEXT
    );
    CREATE TABLE IF NOT EXISTS participation (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
      child_id INTEGER NOT NULL REFERENCES children(id) ON DELETE CASCADE,
      status TEXT NOT NULL DEFAULT 'Participated',
      observation TEXT,
      UNIQUE(activity_id, child_id)
    );
    CREATE TABLE IF NOT EXISTS support_sessions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      child_id INTEGER NOT NULL REFERENCES children(id) ON DELETE CASCADE,
      session_date TEXT NOT NULL,
      category TEXT NOT NULL,
      duration_minutes INTEGER,
      staff_id INTEGER REFERENCES users(id),
      observation TEXT
    );
    """)
    existing = db.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if not existing:
        db.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                   ("admin", generate_password_hash("Admin@12345"), "admin"))
    db.commit()
    db.close()

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapper

@app.context_processor
def inject_globals():
    return {"today": date.today().isoformat()}

@app.route("/")
def home():
    return redirect(url_for("dashboard") if session.get("user_id") else url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    metrics = {
        "children": db.execute("SELECT COUNT(*) FROM children WHERE status='Active'").fetchone()[0],
        "present": db.execute("SELECT COUNT(*) FROM attendance WHERE attendance_date=? AND status='Present'", (date.today().isoformat(),)).fetchone()[0],
        "activities": db.execute("SELECT COUNT(*) FROM activities").fetchone()[0],
        "sessions": db.execute("SELECT COUNT(*) FROM support_sessions").fetchone()[0],
    }
    rows = db.execute("""SELECT attendance_date,
        SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) present,
        SUM(CASE WHEN status='Absent' THEN 1 ELSE 0 END) absent
        FROM attendance GROUP BY attendance_date ORDER BY attendance_date DESC LIMIT 7""").fetchall()
    rows = list(reversed(rows))
    return render_template("dashboard.html", metrics=metrics, chart_labels=[r["attendance_date"] for r in rows],
                           chart_present=[r["present"] for r in rows], chart_absent=[r["absent"] for r in rows])

@app.route("/children", methods=["GET", "POST"])
@login_required
def children():
    db = get_db()
    if request.method == "POST":
        if session.get("role") not in ("admin", "staff"): abort(403)
        try:
            db.execute("""INSERT INTO children(child_code,full_name,age,guardian_name,guardian_contact,enrollment_date,status,notes)
                          VALUES(?,?,?,?,?,?,?,?)""",
                       (request.form["child_code"].strip(), request.form["full_name"].strip(),
                        int(request.form.get("age") or 0) or None, request.form.get("guardian_name","").strip(),
                        request.form.get("guardian_contact","").strip(), request.form.get("enrollment_date") or None,
                        request.form.get("status","Active"), request.form.get("notes","").strip()))
            db.commit()
            flash("Child profile added.", "success")
        except sqlite3.IntegrityError:
            flash("Child ID already exists. Please use a unique ID.", "danger")
        return redirect(url_for("children"))
    q = request.args.get("q","").strip()
    rows = db.execute("SELECT * FROM children WHERE full_name LIKE ? OR child_code LIKE ? ORDER BY id DESC",
                      (f"%{q}%", f"%{q}%")).fetchall()
    return render_template("children.html", children=rows, q=q)

@app.route("/children/<int:child_id>/delete", methods=["POST"])
@admin_required
def delete_child(child_id):
    get_db().execute("DELETE FROM children WHERE id=?", (child_id,))
    get_db().commit()
    flash("Child record deleted.", "success")
    return redirect(url_for("children"))

@app.route("/attendance", methods=["GET", "POST"])
@login_required
def attendance():
    db = get_db()
    selected_date = request.values.get("date") or request.form.get("attendance_date") or date.today().isoformat()
    try:
        datetime.strptime(selected_date, "%Y-%m-%d")
    except ValueError:
        selected_date = date.today().isoformat()

    if request.method == "POST":
        kids_to_mark = db.execute(
            "SELECT id FROM children WHERE status='Active' ORDER BY full_name"
        ).fetchall()
        allowed = {"Present", "Absent", "Leave"}
        try:
            for child in kids_to_mark:
                child_id = child["id"]
                status = request.form.get(f"status_{child_id}")
                if status not in allowed:
                    continue
                db.execute("""
                    INSERT INTO attendance(child_id, attendance_date, status, marked_by)
                    VALUES(?,?,?,?)
                    ON CONFLICT(child_id, attendance_date)
                    DO UPDATE SET status=excluded.status, marked_by=excluded.marked_by
                """, (child_id, selected_date, status, session["user_id"]))
            db.commit()
            flash("Attendance saved successfully.", "success")
        except sqlite3.Error:
            db.rollback()
            flash("Could not save attendance. Please check the selected records.", "danger")
        return redirect(url_for("attendance", date=selected_date))

    kids = db.execute(
        "SELECT id,child_code,full_name FROM children WHERE status='Active' ORDER BY full_name"
    ).fetchall()
    rows = db.execute("""
        SELECT a.*, c.full_name, c.child_code
        FROM attendance a JOIN children c ON c.id=a.child_id
        ORDER BY a.attendance_date DESC, a.id DESC LIMIT 100
    """).fetchall()
    day_rows = db.execute(
        "SELECT child_id, status FROM attendance WHERE attendance_date=?",
        (selected_date,)
    ).fetchall()
    attendance_map = {row["child_id"]: row["status"] for row in day_rows}
    return render_template(
        "attendance.html", kids=kids, records=rows, today=date.today().isoformat(),
        selected_date=selected_date, attendance_map=attendance_map
    )

@app.route("/activities", methods=["GET", "POST"])
@login_required
def activities():
    db = get_db()
    if request.method == "POST":
        db.execute("INSERT INTO activities(title,category,activity_date,description) VALUES(?,?,?,?)",
                   (request.form["title"].strip(), request.form["category"], request.form["activity_date"],
                    request.form.get("description","").strip()))
        db.commit()
        flash("Activity added.", "success")
        return redirect(url_for("activities"))
    rows = db.execute("""SELECT a.*, COUNT(p.id) participants FROM activities a
                         LEFT JOIN participation p ON p.activity_id=a.id
                         GROUP BY a.id ORDER BY a.activity_date DESC""").fetchall()
    return render_template("activities.html", activities=rows)

@app.route("/activities/<int:activity_id>", methods=["GET", "POST"])
@login_required
def activity_detail(activity_id):
    db = get_db()
    activity = db.execute("SELECT * FROM activities WHERE id=?", (activity_id,)).fetchone()
    if not activity: abort(404)
    if request.method == "POST":
        try:
            db.execute("""INSERT INTO participation(activity_id,child_id,status,observation) VALUES(?,?,?,?)
                          ON CONFLICT(activity_id,child_id) DO UPDATE SET status=excluded.status, observation=excluded.observation""",
                       (activity_id, int(request.form["child_id"]), request.form["status"],
                        request.form.get("observation","").strip()))
            db.commit()
            flash("Participation saved.", "success")
        except sqlite3.IntegrityError:
            flash("Please select a valid child.", "danger")
        return redirect(url_for("activity_detail", activity_id=activity_id))
    kids = db.execute("SELECT id,child_code,full_name FROM children WHERE status='Active' ORDER BY full_name").fetchall()
    participants = db.execute("""SELECT p.*, c.full_name,c.child_code FROM participation p
                                  JOIN children c ON c.id=p.child_id WHERE p.activity_id=?""", (activity_id,)).fetchall()
    return render_template("activity_detail.html", activity=activity, kids=kids, participants=participants)

@app.route("/sessions", methods=["GET", "POST"])
@login_required
def sessions():
    db = get_db()
    if request.method == "POST":
        db.execute("""INSERT INTO support_sessions(child_id,session_date,category,duration_minutes,staff_id,observation)
                      VALUES(?,?,?,?,?,?)""",
                   (int(request.form["child_id"]), request.form["session_date"], request.form["category"],
                    int(request.form.get("duration_minutes") or 0) or None, session["user_id"],
                    request.form.get("observation","").strip()))
        db.commit()
        flash("Support session recorded.", "success")
        return redirect(url_for("sessions"))
    kids = db.execute("SELECT id,child_code,full_name FROM children WHERE status='Active' ORDER BY full_name").fetchall()
    rows = db.execute("""SELECT s.*, c.full_name,c.child_code,u.username FROM support_sessions s
                         JOIN children c ON c.id=s.child_id LEFT JOIN users u ON u.id=s.staff_id
                         ORDER BY s.session_date DESC, s.id DESC""").fetchall()
    return render_template("sessions.html", kids=kids, records=rows)

@app.route("/reports")
@login_required
def reports():
    db = get_db()
    today = date.today()
    default_start = (today - __import__("datetime").timedelta(days=29)).isoformat()
    start_date = request.args.get("start_date", default_start)
    end_date = request.args.get("end_date", today.isoformat())
    # Accept only ISO dates; fall back to the default period for invalid input.
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")
        if start_date > end_date:
            raise ValueError("start date is after end date")
    except ValueError:
        start_date, end_date = default_start, today.isoformat()

    attendance_totals = db.execute("""SELECT
        COUNT(*) total,
        SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) present,
        SUM(CASE WHEN status='Absent' THEN 1 ELSE 0 END) absent,
        SUM(CASE WHEN status='Leave' THEN 1 ELSE 0 END) leave_count
        FROM attendance WHERE attendance_date BETWEEN ? AND ?""",
        (start_date, end_date)).fetchone()
    present = attendance_totals["present"] or 0
    absent = attendance_totals["absent"] or 0
    leave_count = attendance_totals["leave_count"] or 0
    decided = present + absent
    attendance_rate = round((present / decided) * 100, 1) if decided else 0

    metrics = {
        "children": db.execute("SELECT COUNT(*) FROM children WHERE status='Active'").fetchone()[0],
        "attendance_records": attendance_totals["total"] or 0,
        "attendance_rate": attendance_rate,
        "present": present,
        "absent": absent,
        "leave": leave_count,
        "activities": db.execute("SELECT COUNT(*) FROM activities WHERE activity_date BETWEEN ? AND ?", (start_date, end_date)).fetchone()[0],
        "participation": db.execute("""SELECT COUNT(*) FROM participation p JOIN activities a ON a.id=p.activity_id
                                      WHERE a.activity_date BETWEEN ? AND ?""", (start_date, end_date)).fetchone()[0],
        "sessions": db.execute("SELECT COUNT(*) FROM support_sessions WHERE session_date BETWEEN ? AND ?", (start_date, end_date)).fetchone()[0],
    }

    daily_rows = db.execute("""SELECT attendance_date,
        SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) present,
        SUM(CASE WHEN status='Absent' THEN 1 ELSE 0 END) absent,
        SUM(CASE WHEN status='Leave' THEN 1 ELSE 0 END) leave_count
        FROM attendance WHERE attendance_date BETWEEN ? AND ?
        GROUP BY attendance_date ORDER BY attendance_date""", (start_date, end_date)).fetchall()

    activity_rows = db.execute("""SELECT a.title, a.category,
        COUNT(p.id) participants,
        SUM(CASE WHEN p.status='Participated' THEN 1 ELSE 0 END) completed,
        SUM(CASE WHEN p.status='Partially participated' THEN 1 ELSE 0 END) partial
        FROM activities a LEFT JOIN participation p ON p.activity_id=a.id
        WHERE a.activity_date BETWEEN ? AND ?
        GROUP BY a.id ORDER BY a.activity_date DESC""", (start_date, end_date)).fetchall()

    support_rows = db.execute("""SELECT category, COUNT(*) total, SUM(duration_minutes) minutes
        FROM support_sessions WHERE session_date BETWEEN ? AND ?
        GROUP BY category ORDER BY total DESC, category""", (start_date, end_date)).fetchall()

    engagement_rows = db.execute("""SELECT c.child_code, c.full_name,
        COALESCE(at.present, 0) present, COALESCE(at.absent, 0) absent,
        COALESCE(at.leave_count, 0) leave_count, COALESCE(part.activities, 0) activities
        FROM children c
        LEFT JOIN (
            SELECT child_id,
                SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) present,
                SUM(CASE WHEN status='Absent' THEN 1 ELSE 0 END) absent,
                SUM(CASE WHEN status='Leave' THEN 1 ELSE 0 END) leave_count
            FROM attendance WHERE attendance_date BETWEEN ? AND ? GROUP BY child_id
        ) at ON at.child_id=c.id
        LEFT JOIN (
            SELECT p.child_id, COUNT(*) activities
            FROM participation p JOIN activities a ON a.id=p.activity_id
            WHERE a.activity_date BETWEEN ? AND ? GROUP BY p.child_id
        ) part ON part.child_id=c.id
        WHERE c.status='Active'
        ORDER BY c.full_name""", (start_date, end_date, start_date, end_date)).fetchall()
    engagement = []
    for row in engagement_rows:
        attended = row["present"] or 0
        missed = row["absent"] or 0
        denom = attended + missed
        engagement.append({
            "child_code": row["child_code"], "full_name": row["full_name"],
            "present": attended, "absent": missed, "leave_count": row["leave_count"] or 0,
            "attendance_rate": round(attended / denom * 100, 1) if denom else 0,
            "activities": row["activities"] or 0,
        })

    recent_rows = db.execute("""SELECT at.attendance_date,c.child_code,c.full_name,at.status
        FROM attendance at JOIN children c ON c.id=at.child_id
        WHERE at.attendance_date BETWEEN ? AND ?
        ORDER BY at.attendance_date DESC, at.id DESC LIMIT 12""", (start_date, end_date)).fetchall()

    return render_template("reports.html", metrics=metrics, start_date=start_date, end_date=end_date,
        daily_rows=daily_rows, activity_rows=activity_rows, support_rows=support_rows,
        engagement=engagement, records=recent_rows,
        chart_labels=[r["attendance_date"] for r in daily_rows],
        chart_present=[r["present"] or 0 for r in daily_rows],
        chart_absent=[r["absent"] or 0 for r in daily_rows],
        chart_leave=[r["leave_count"] or 0 for r in daily_rows],
        activity_labels=[r["title"] for r in activity_rows],
        activity_values=[r["participants"] or 0 for r in activity_rows],
        support_labels=[r["category"] for r in support_rows],
        support_values=[r["total"] for r in support_rows])

@app.route("/reports/attendance.csv")
@login_required
def attendance_csv():
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    query = """SELECT a.attendance_date,c.child_code,c.full_name,a.status
               FROM attendance a JOIN children c ON c.id=a.child_id"""
    params = []
    if start_date and end_date:
        query += " WHERE a.attendance_date BETWEEN ? AND ?"
        params.extend([start_date, end_date])
    query += " ORDER BY a.attendance_date DESC, c.full_name"
    rows = get_db().execute(query, params).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Child ID", "Child Name", "Status"])
    writer.writerows([tuple(r) for r in rows])
    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=attendance_report.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response

@app.route("/reports/participation.csv")
@login_required
def participation_csv():
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    query = """SELECT a.activity_date,a.title,a.category,c.child_code,c.full_name,p.status,p.observation
               FROM participation p JOIN activities a ON a.id=p.activity_id
               JOIN children c ON c.id=p.child_id"""
    params = []
    if start_date and end_date:
        query += " WHERE a.activity_date BETWEEN ? AND ?"
        params.extend([start_date, end_date])
    query += " ORDER BY a.activity_date DESC,a.title,c.full_name"
    rows = get_db().execute(query, params).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Activity", "Category", "Child ID", "Child Name", "Participation", "Observation"])
    writer.writerows([tuple(r) for r in rows])
    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=participation_report.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response

@app.route("/reports/support.csv")
@login_required
def support_csv():
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    query = """SELECT s.session_date,c.child_code,c.full_name,s.category,s.duration_minutes,u.username,s.observation
               FROM support_sessions s JOIN children c ON c.id=s.child_id
               LEFT JOIN users u ON u.id=s.staff_id"""
    params = []
    if start_date and end_date:
        query += " WHERE s.session_date BETWEEN ? AND ?"
        params.extend([start_date, end_date])
    query += " ORDER BY s.session_date DESC,c.full_name"
    rows = get_db().execute(query, params).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Child ID", "Child Name", "Category", "Duration Minutes", "Staff", "Observation"])
    writer.writerows([tuple(r) for r in rows])
    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=support_sessions_report.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response


@app.route("/reports/summary.pdf")
@login_required
def summary_pdf():
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except ImportError:
        return "PDF library missing. Run: python -m pip install reportlab", 500

    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    today = date.today()
    if not start_date:
        start_date = (today - __import__("datetime").timedelta(days=29)).isoformat()
    if not end_date:
        end_date = today.isoformat()
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")
        if start_date > end_date:
            raise ValueError
    except ValueError:
        return "Invalid report date range.", 400

    db = get_db()
    active_children = db.execute(
        "SELECT COUNT(*) FROM children WHERE status='Active'"
    ).fetchone()[0]
    attendance_rows = db.execute("""
        SELECT status, COUNT(*) AS total FROM attendance
        WHERE attendance_date BETWEEN ? AND ? GROUP BY status
    """, (start_date, end_date)).fetchall()
    attendance_counts = {row["status"]: row["total"] for row in attendance_rows}
    activity_count = db.execute(
        "SELECT COUNT(*) FROM activities WHERE activity_date BETWEEN ? AND ?",
        (start_date, end_date)
    ).fetchone()[0]
    session_count = db.execute(
        "SELECT COUNT(*) FROM support_sessions WHERE session_date BETWEEN ? AND ?",
        (start_date, end_date)
    ).fetchone()[0]
    recent = db.execute("""
        SELECT a.attendance_date, c.child_code, c.full_name, a.status
        FROM attendance a JOIN children c ON c.id=a.child_id
        WHERE a.attendance_date BETWEEN ? AND ?
        ORDER BY a.attendance_date DESC, c.full_name LIMIT 30
    """, (start_date, end_date)).fetchall()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18*mm,
                            leftMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("CareConnect - Summary Report", styles["Title"]),
        Paragraph(f"Report period: {start_date} to {end_date}", styles["Normal"]),
        Spacer(1, 12),
        Paragraph("Overview", styles["Heading2"])
    ]
    summary_data = [
        ["Metric", "Total"],
        ["Active children", str(active_children)],
        ["Present records", str(attendance_counts.get("Present", 0))],
        ["Absent records", str(attendance_counts.get("Absent", 0))],
        ["Leave records", str(attendance_counts.get("Leave", 0))],
        ["Activities", str(activity_count)],
        ["Support sessions", str(session_count)]
    ]
    summary_table = Table(summary_data, colWidths=[105*mm, 45*mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#24476b")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("PADDING", (0,0), (-1,-1), 7),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f2f5f8")])
    ]))
    story.extend([summary_table, Spacer(1, 16), Paragraph("Recent Attendance Records", styles["Heading2"])])
    detail_data = [["Date", "Child ID", "Child Name", "Status"]]
    detail_data.extend([[r["attendance_date"], r["child_code"], r["full_name"], r["status"]] for r in recent])
    if not recent:
        detail_data.append(["-", "-", "No attendance records in this period", "-"])
    detail_table = Table(detail_data, repeatRows=1, colWidths=[32*mm, 28*mm, 75*mm, 25*mm])
    detail_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#24476b")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("GRID", (0,0), (-1,-1), 0.4, colors.grey),
        ("PADDING", (0,0), (-1,-1), 5),
        ("FONTSIZE", (0,0), (-1,-1), 8),
    ]))
    story.append(detail_table)
    doc.build(story)
    buffer.seek(0)
    response = make_response(buffer.getvalue())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = 'attachment; filename="careconnect_summary_report.pdf"'
    return response

@app.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    db = get_db()
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        role = request.form["role"]
        if len(password) < 10:
            flash("Password must contain at least 10 characters.", "danger")
        elif role not in ("admin","staff"):
            flash("Invalid role.", "danger")
        else:
            try:
                db.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                           (username, generate_password_hash(password), role))
                db.commit()
                flash("Account created.", "success")
            except sqlite3.IntegrityError:
                flash("Username already exists.", "danger")
        return redirect(url_for("users"))
    rows = db.execute("SELECT id,username,role,created_at FROM users ORDER BY id").fetchall()
    return render_template("users.html", users=rows)

@app.errorhandler(403)
def forbidden(_e):
    return render_template("error.html", code=403, message="You do not have permission to access this page."), 403

@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, message="The requested page was not found."), 404

if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=False)