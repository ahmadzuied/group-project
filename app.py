from flask import Flask, request, render_template, redirect, session, jsonify, url_for
from flask_cors import CORS
from werkzeug.security import check_password_hash
import sqlite3
from datetime import datetime
import os
import json
from urllib.request import Request, urlopen
from sklearn.tree import DecisionTreeClassifier

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "attendance.db")

TOTAL_LECTURES = 15
HOLIDAY_API_URL = "https://tallyfy.com/national-holidays/api/PS/{year}.json"
HOLIDAY_CACHE = {}

risk_model = DecisionTreeClassifier(max_depth=3, random_state=7)
risk_model.fit(
    [
        [15, 0, 100],
        [14, 1, 93.33],
        [13, 2, 86.67],
        [12, 3, 80],
        [11, 4, 73.33],
        [10, 5, 66.67],
        [9, 6, 60],
        [8, 7, 53.33],
        [7, 8, 46.67],
        [6, 9, 40],
        [5, 10, 33.33],
        [3, 12, 20],
        [1, 14, 6.67],
        [0, 15, 0]
    ],
    [
        "منخفض",
        "منخفض",
        "منخفض",
        "منخفض",
        "متوسط",
        "متوسط",
        "متوسط",
        "متوسط",
        "مرتفع",
        "مرتفع",
        "مرتفع",
        "مرتفع",
        "مرتفع",
        "مرتفع"
    ]
)

app = Flask(__name__)
app.secret_key = "attendance-system-secret-key"
CORS(app)


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema():
    conn = get_db_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS teacher_settings (
            teacher_id TEXT PRIMARY KEY,
            attendance_open INTEGER DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS custom_days_off (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id TEXT,
            date TEXT,
            reason TEXT
        )
    """)

    default_setting = conn.execute(
        "SELECT attendance_open FROM settings ORDER BY id DESC LIMIT 1"
    ).fetchone()

    default_value = default_setting["attendance_open"] if default_setting else 0

    teachers = conn.execute(
        "SELECT id FROM students WHERE role='teacher'"
    ).fetchall()

    for teacher in teachers:
        conn.execute(
            """
            INSERT OR IGNORE INTO teacher_settings (teacher_id, attendance_open)
            VALUES (?, ?)
            """,
            (teacher["id"], default_value)
        )

    conn.commit()
    conn.close()


def get_teacher_day_off(teacher_id, date_text=None):
    if date_text is None:
        date_text = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    day_off = conn.execute(
        """
        SELECT id, date, reason
        FROM custom_days_off
        WHERE teacher_id=? AND date=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (teacher_id, date_text)
    ).fetchone()
    conn.close()

    if not day_off:
        return None

    return {
        "id": day_off["id"],
        "date": day_off["date"],
        "reason": day_off["reason"]
    }


ensure_schema()


def get_recommendation(percentage):
    if percentage >= 80:
        return "ممتاز", "✅ حضورك ممتاز، استمر بهذا المستوى."
    elif percentage >= 50:
        return "متوسط", "⚠️ حضورك متوسط، حاول الالتزام أكثر بالمحاضرات."
    else:
        return "ضعيف", "❌ حضورك ضعيف، يجب تحسين الالتزام بالحضور."


def predict_attendance_risk(attendance_count):
    missed_count = max(TOTAL_LECTURES - attendance_count, 0)
    percentage = round((attendance_count / TOTAL_LECTURES) * 100, 2)
    risk = risk_model.predict([[attendance_count, missed_count, percentage]])[0]

    messages = {
        "منخفض": "مستوى الخطر منخفض، ونمط الحضور الحالي مستقر.",
        "متوسط": "مستوى الخطر متوسط، ويُنصح بتحسين الالتزام بالمحاضرات القادمة.",
        "مرتفع": "مستوى الخطر مرتفع، ويحتاج الطالب إلى رفع نسبة الحضور بشكل واضح."
    }

    return risk, messages[risk]


def get_public_holidays(year):
    if year in HOLIDAY_CACHE:
        return HOLIDAY_CACHE[year]

    request_data = Request(
        HOLIDAY_API_URL.format(year=year),
        headers={"User-Agent": "StudentAttendanceSystem/1.0"}
    )

    with urlopen(request_data, timeout=6) as response:
        data = json.loads(response.read().decode("utf-8"))

    holidays = data.get("holidays", [])
    HOLIDAY_CACHE[year] = holidays
    return holidays


def get_holiday_status():
    today = datetime.now().date()

    try:
        holidays = get_public_holidays(today.year)
    except Exception:
        return {
            "available": False,
            "is_holiday": False,
            "holiday": None,
            "next_holiday": None
        }

    today_holiday = None
    upcoming = []

    for holiday in holidays:
        holiday_date_text = holiday.get("observed_date") or holiday.get("date")

        try:
            holiday_date = datetime.strptime(holiday_date_text, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue

        item = {
            "name": holiday.get("local_name") or holiday.get("name") or "عطلة رسمية",
            "date": holiday_date_text
        }

        if holiday_date == today:
            today_holiday = item
        elif holiday_date > today:
            upcoming.append((holiday_date, item))

    upcoming.sort(key=lambda item: item[0])
    next_holiday = upcoming[0][1] if upcoming else None

    return {
        "available": True,
        "is_holiday": today_holiday is not None,
        "holiday": today_holiday,
        "next_holiday": next_holiday
    }


@app.route("/")
def home():
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login():
    user_id = request.form.get("student_id")
    password = request.form.get("password")

    conn = get_db_connection()

    user = conn.execute(
        "SELECT * FROM students WHERE id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    if not user:
        return "بيانات الدخول غير صحيحة", 401

    if not check_password_hash(user["password"], password):
        return "بيانات الدخول غير صحيحة", 401

    session["user_id"] = user["id"]
    session["name"] = user["name"]
    session["role"] = user["role"]

    if user["role"] == "teacher":
        return redirect(url_for("teacher_page"))

    return redirect(url_for("attendance_page"))


@app.route("/attendance_page")
def attendance_page():
    student_id = session.get("user_id")
    message = request.args.get("message", "")

    if not student_id or session.get("role") != "student":
        return redirect(url_for("home"))

    conn = get_db_connection()

    student = conn.execute(
        "SELECT * FROM students WHERE id=? AND role='student'",
        (student_id,)
    ).fetchone()

    courses = conn.execute(
        """
        SELECT courses.course_id, courses.course_name
        FROM courses
        JOIN student_courses ON courses.course_id = student_courses.course_id
        WHERE student_courses.student_id=?
        """,
        (student_id,)
    ).fetchall()

    conn.close()

    if not student:
        return redirect(url_for("home"))

    return render_template(
        "attendance.html",
        name=student["name"],
        student_id=student["id"],
        courses=courses,
        message=message
    )


@app.route("/attendance", methods=["POST"])
def attendance():
    if session.get("role") != "student":
        return redirect(url_for("home"))

    student_id = session.get("user_id")
    course_id = request.form.get("course_id")

    if not student_id:
        return redirect(url_for("home"))

    if not course_id:
        return redirect(url_for(
            "attendance_page",
            message="❌ يرجى اختيار المساق"
        ))

    conn = get_db_connection()

    allowed_course = conn.execute(
        """
        SELECT courses.course_id, courses.course_name, courses.teacher_id
        FROM courses
        JOIN student_courses ON courses.course_id = student_courses.course_id
        WHERE student_courses.student_id=? AND courses.course_id=?
        """,
        (student_id, course_id)
    ).fetchone()

    if not allowed_course:
        conn.close()
        return redirect(url_for(
            "attendance_page",
            message="❌ غير مسموح لك بالتسجيل في هذا المساق"
        ))

    day_off = conn.execute(
        """
        SELECT reason
        FROM custom_days_off
        WHERE teacher_id=? AND date=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (
            allowed_course["teacher_id"],
            datetime.now().strftime("%Y-%m-%d")
        )
    ).fetchone()

    if day_off:
        conn.close()
        return redirect(url_for(
            "attendance_page",
            message=f"❌ لا يوجد تسجيل حضور اليوم: {day_off['reason']}"
        ))

    setting = conn.execute(
        """
        SELECT attendance_open
        FROM teacher_settings
        WHERE teacher_id=?
        """,
        (allowed_course["teacher_id"],)
    ).fetchone()

    if not setting or setting["attendance_open"] != 1:
        conn.close()
        return redirect(url_for(
            "attendance_page",
            message="❌ تسجيل الحضور مغلق حالياً"
        ))

    current_date = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M:%S")

    existing = conn.execute(
        """
        SELECT * FROM attendance
        WHERE student_id=? AND course_id=? AND date=?
        """,
        (student_id, course_id, current_date)
    ).fetchone()

    if existing:
        conn.close()
        return redirect(url_for(
            "attendance_page",
            message="⚠️ تم تسجيل حضورك لهذا المساق اليوم مسبقاً"
        ))

    conn.execute(
        """
        INSERT INTO attendance (student_id, course_id, date, time)
        VALUES (?, ?, ?, ?)
        """,
        (student_id, course_id, current_date, current_time)
    )

    conn.commit()
    conn.close()

    return redirect(url_for(
        "attendance_page",
        message="✅ تم تسجيل الحضور بنجاح"
    ))


@app.route("/confirm", methods=["POST"])
def confirm_attendance():
    if session.get("role") != "student":
        return "❌ يجب تسجيل الدخول كطالب أولاً", 401

    student_id = session.get("user_id")

    current_date = datetime.now().strftime("%Y-%m-%d")
    current_time = datetime.now().strftime("%H:%M:%S")

    conn = get_db_connection()

    existing = conn.execute(
        """
        SELECT * FROM confirmations
        WHERE student_id=? AND date=?
        """,
        (student_id, current_date)
    ).fetchone()

    if existing:
        conn.close()
        return "⚠️ تم تأكيد حضورك اليوم مسبقاً"

    conn.execute(
        """
        INSERT INTO confirmations (student_id, date, time)
        VALUES (?, ?, ?)
        """,
        (student_id, current_date, current_time)
    )

    conn.commit()
    conn.close()

    return "✅ تم تأكيد الحضور بنجاح"


@app.route("/teacher_page")
def teacher_page():
    teacher_id = session.get("user_id")

    if not teacher_id or session.get("role") != "teacher":
        return redirect(url_for("home"))

    conn = get_db_connection()

    teacher = conn.execute(
        "SELECT * FROM students WHERE id=? AND role='teacher'",
        (teacher_id,)
    ).fetchone()

    conn.close()

    if not teacher:
        return redirect(url_for("home"))

    return render_template(
        "teacher.html",
        name=teacher["name"],
        teacher_id=teacher["id"]
    )


@app.route("/toggle_attendance", methods=["POST"])
def toggle_attendance():
    if session.get("role") != "teacher":
        return jsonify({"message": "❌ غير مصرح لك"}), 403

    teacher_id = session.get("user_id")
    data = request.get_json() or {}
    action = data.get("action")

    if action == "open":
        day_off = get_teacher_day_off(teacher_id)

        if day_off:
            return jsonify({
                "message": f"⚠️ لا يمكن فتح تسجيل الحضور اليوم: {day_off['reason']}",
                "open": False
            }), 409

        value = 1
        message = "✅ تسجيل الحضور مفتوح حالياً"
    elif action == "close":
        value = 0
        message = "❌ تسجيل الحضور مغلق حالياً"
    else:
        return jsonify({"message": "❌ أمر غير صحيح"}), 400

    conn = get_db_connection()

    conn.execute(
        """
        INSERT INTO teacher_settings (teacher_id, attendance_open)
        VALUES (?, ?)
        ON CONFLICT(teacher_id)
        DO UPDATE SET attendance_open=excluded.attendance_open
        """,
        (teacher_id, value)
    )

    conn.commit()
    conn.close()

    return jsonify({"message": message, "open": value == 1})

@app.route("/holiday_status")
def holiday_status():
    if session.get("role") != "teacher":
        return jsonify({"error": "غير مصرح لك"}), 403

    teacher_id = session.get("user_id")
    result = get_holiday_status()

    conn = get_db_connection()

    today_text = datetime.now().strftime("%Y-%m-%d")

    custom_day = conn.execute(
        """
        SELECT id, date, reason
        FROM custom_days_off
        WHERE teacher_id=? AND date=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (teacher_id, today_text)
    ).fetchone()

    next_custom_day = conn.execute(
        """
        SELECT id, date, reason
        FROM custom_days_off
        WHERE teacher_id=? AND date>?
        ORDER BY date ASC
        LIMIT 1
        """,
        (teacher_id, today_text)
    ).fetchone()

    conn.close()

    result["custom_day"] = dict(custom_day) if custom_day else None
    result["next_custom_day"] = dict(next_custom_day) if next_custom_day else None

    return jsonify(result)

@app.route("/attendance_status")
def attendance_status():
    if session.get("role") != "teacher":
        return jsonify({"error": "غير مصرح لك"}), 403

    teacher_id = session.get("user_id")
    day_off = get_teacher_day_off(teacher_id)

    if day_off:
        return jsonify({
            "open": False,
            "message": f"⛔ تسجيل الحضور متوقف اليوم: {day_off['reason']}"
        })

    conn = get_db_connection()

    setting = conn.execute(
        """
        SELECT attendance_open
        FROM teacher_settings
        WHERE teacher_id=?
        """,
        (teacher_id,)
    ).fetchone()

    conn.close()

    if setting and setting["attendance_open"] == 1:
        return jsonify({
            "open": True,
            "message": "✅ تسجيل الحضور مفتوح حالياً"
        })

    return jsonify({
        "open": False,
        "message": "❌ تسجيل الحضور مغلق حالياً"
    })

@app.route("/student_report_page")
def student_report_page():
    if session.get("role") != "student":
        return redirect(url_for("home"))

    student_id = session.get("user_id")

    return render_template(
        "report.html",
        student_id=student_id
    )


@app.route("/report/<student_id>")
def student_report(student_id):
    if not session.get("user_id"):
        return jsonify({"error": "يجب تسجيل الدخول"}), 401

    conn = get_db_connection()

    student = conn.execute(
        "SELECT * FROM students WHERE id=? AND role='student'",
        (student_id,)
    ).fetchone()

    if not student:
        conn.close()
        return jsonify({"error": "الطالب غير موجود"}), 404

    if session.get("role") == "student":
        if session.get("user_id") != student_id:
            conn.close()
            return jsonify({"error": "غير مصرح لك"}), 403

        records = conn.execute(
            """
            SELECT attendance.course_id, courses.course_name, attendance.date, attendance.time
            FROM attendance
            JOIN courses ON attendance.course_id = courses.course_id
            WHERE attendance.student_id=?
            ORDER BY attendance.date DESC, attendance.time DESC
            """,
            (student_id,)
        ).fetchall()

    elif session.get("role") == "teacher":
        teacher_id = session.get("user_id")

        allowed_student = conn.execute(
            """
            SELECT 1
            FROM student_courses
            JOIN courses ON student_courses.course_id = courses.course_id
            WHERE student_courses.student_id=? AND courses.teacher_id=?
            LIMIT 1
            """,
            (student_id, teacher_id)
        ).fetchone()

        if not allowed_student:
            conn.close()
            return jsonify({"error": "غير مصرح لك بعرض تقرير هذا الطالب"}), 403

        records = conn.execute(
            """
            SELECT attendance.course_id, courses.course_name, attendance.date, attendance.time
            FROM attendance
            JOIN courses ON attendance.course_id = courses.course_id
            WHERE attendance.student_id=? AND courses.teacher_id=?
            ORDER BY attendance.date DESC, attendance.time DESC
            """,
            (student_id, teacher_id)
        ).fetchall()

    else:
        conn.close()
        return jsonify({"error": "غير مصرح لك"}), 403

    attendance_count = len(records)
    percentage = round((attendance_count / TOTAL_LECTURES) * 100, 2)
    level, recommendation = get_recommendation(percentage)
    risk_level, risk_message = predict_attendance_risk(attendance_count)

    result_records = []

    for r in records:
        result_records.append({
            "course_id": r["course_name"],
            "date": r["date"],
            "time": r["time"]
        })

    conn.close()

    return jsonify({
        "student_id": student["id"],
        "name": student["name"],
        "college": student["college"],
        "major": student["major"],
        "year": student["year"],
        "attendance_count": attendance_count,
        "percentage": percentage,
        "level": level,
        "recommendation": recommendation,
        "risk_level": risk_level,
        "risk_message": risk_message,
        "records": result_records
    })


@app.route("/teacher_reports_page")
def teacher_reports_page():
    if session.get("role") != "teacher":
        return redirect(url_for("home"))

    return render_template("teacher_reports.html")


@app.route("/teacher_courses")
def teacher_courses():
    if session.get("role") != "teacher":
        return jsonify({"error": "غير مصرح لك"}), 403

    teacher_id = session.get("user_id")

    conn = get_db_connection()

    courses = conn.execute(
        """
        SELECT course_id, course_name
        FROM courses
        WHERE teacher_id=?
        ORDER BY course_name
        """,
        (teacher_id,)
    ).fetchall()

    conn.close()

    result = []

    for course in courses:
        result.append({
            "course_id": course["course_id"],
            "course_name": course["course_name"]
        })

    return jsonify({"courses": result})


@app.route("/all_reports")
def all_reports():
    if session.get("role") != "teacher":
        return jsonify({"error": "غير مصرح لك"}), 403

    teacher_id = session.get("user_id")
    course_id = request.args.get("course_id")

    if not course_id:
        return jsonify({
            "reports": [],
            "message": "يرجى اختيار المساق أولاً"
        })

    conn = get_db_connection()

    course = conn.execute(
        """
        SELECT *
        FROM courses
        WHERE course_id=? AND teacher_id=?
        """,
        (course_id, teacher_id)
    ).fetchone()

    if not course:
        conn.close()
        return jsonify({"error": "هذا المساق غير تابع لهذا المحاضر"}), 403

    students = conn.execute(
        """
        SELECT students.*
        FROM students
        JOIN student_courses ON students.id = student_courses.student_id
        WHERE students.role='student'
        AND student_courses.course_id=?
        ORDER BY students.name
        """,
        (course_id,)
    ).fetchall()

    reports = []

    for student in students:
        attendance_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM attendance
            WHERE student_id=? AND course_id=?
            """,
            (student["id"], course_id)
        ).fetchone()["count"]

        percentage = round((attendance_count / TOTAL_LECTURES) * 100, 2)
        level, recommendation = get_recommendation(percentage)
        risk_level, risk_message = predict_attendance_risk(attendance_count)

        reports.append({
            "id": student["id"],
            "name": student["name"],
            "college": student["college"],
            "major": student["major"],
            "year": student["year"],
            "course": course["course_name"],
            "attendance_count": attendance_count,
            "percentage": percentage,
            "recommendation": recommendation,
            "level": level,
            "risk_level": risk_level,
            "risk_message": risk_message
        })

    conn.close()

    return jsonify({"reports": reports})


@app.route("/manage_students_page")
def manage_students_page():
    if session.get("role") != "teacher":
        return redirect(url_for("home"))

    teacher_id = session.get("user_id")
    message = request.args.get("message", "")

    conn = get_db_connection()

    courses = conn.execute(
        """
        SELECT course_id, course_name
        FROM courses
        WHERE teacher_id=?
        ORDER BY course_name
        """,
        (teacher_id,)
    ).fetchall()

    students = conn.execute(
        """
        SELECT DISTINCT
            students.id,
            students.name,
            students.college,
            students.major,
            students.year
        FROM students
        JOIN student_courses ON students.id=student_courses.student_id
        JOIN courses ON student_courses.course_id=courses.course_id
        WHERE students.role='student'
        AND courses.teacher_id=?
        ORDER BY students.name
        """,
        (teacher_id,)
    ).fetchall()

    enrollments = conn.execute(
        """
        SELECT
            student_courses.student_id,
            courses.course_id,
            courses.course_name
        FROM student_courses
        JOIN courses ON student_courses.course_id=courses.course_id
        WHERE courses.teacher_id=?
        ORDER BY courses.course_name
        """,
        (teacher_id,)
    ).fetchall()

    available_students = conn.execute(
        """
        SELECT id, name, college, major, year
        FROM students
        WHERE role='student'
        ORDER BY name
        """
    ).fetchall()

    days_off = conn.execute(
        """
        SELECT id, date, reason
        FROM custom_days_off
        WHERE teacher_id=?
        ORDER BY date DESC
        """,
        (teacher_id,)
    ).fetchall()

    conn.close()

    enrollment_map = {}

    for item in enrollments:
        enrollment_map.setdefault(item["student_id"], []).append({
            "course_id": item["course_id"],
            "course_name": item["course_name"]
        })

    return render_template(
        "teacher_management.html",
        courses=courses,
        students=students,
        available_students=available_students,
        enrollment_map=enrollment_map,
        days_off=days_off,
        message=message
    )


@app.route("/assign_student_course", methods=["POST"])
def assign_student_course():
    if session.get("role") != "teacher":
        return redirect(url_for("home"))

    teacher_id = session.get("user_id")
    student_id = request.form.get("student_id", "").strip()
    course_id = request.form.get("course_id", "").strip()

    if not student_id or not course_id:
        return redirect(url_for(
            "manage_students_page",
            message="يرجى اختيار الطالب والمساق"
        ))

    conn = get_db_connection()

    student = conn.execute(
        "SELECT id FROM students WHERE id=? AND role='student'",
        (student_id,)
    ).fetchone()

    course = conn.execute(
        """
        SELECT course_id
        FROM courses
        WHERE course_id=? AND teacher_id=?
        """,
        (course_id, teacher_id)
    ).fetchone()

    if not student or not course:
        conn.close()
        return redirect(url_for(
            "manage_students_page",
            message="الطالب أو المساق المحدد غير متاح"
        ))

    existing = conn.execute(
        """
        SELECT 1
        FROM student_courses
        WHERE student_id=? AND course_id=?
        """,
        (student_id, course_id)
    ).fetchone()

    if existing:
        conn.close()
        return redirect(url_for(
            "manage_students_page",
            message="الطالب مرتبط بهذا المساق مسبقاً"
        ))

    conn.execute(
        """
        INSERT INTO student_courses (student_id, course_id)
        VALUES (?, ?)
        """,
        (student_id, course_id)
    )

    conn.commit()
    conn.close()

    return redirect(url_for(
        "manage_students_page",
        message="تم ربط الطالب بالمساق بنجاح"
    ))


@app.route("/remove_student_course", methods=["POST"])
def remove_student_course():
    if session.get("role") != "teacher":
        return redirect(url_for("home"))

    teacher_id = session.get("user_id")
    student_id = request.form.get("student_id")
    course_id = request.form.get("course_id")

    conn = get_db_connection()

    course = conn.execute(
        """
        SELECT course_id
        FROM courses
        WHERE course_id=? AND teacher_id=?
        """,
        (course_id, teacher_id)
    ).fetchone()

    if course:
        conn.execute(
            """
            DELETE FROM student_courses
            WHERE student_id=? AND course_id=?
            """,
            (student_id, course_id)
        )
        conn.commit()

    conn.close()

    return redirect(url_for(
        "manage_students_page",
        message="تم إزالة الطالب من المساق"
    ))


@app.route("/add_day_off", methods=["POST"])
def add_day_off():
    if session.get("role") != "teacher":
        return redirect(url_for("home"))

    teacher_id = session.get("user_id")
    date_text = request.form.get("date", "").strip()
    reason = request.form.get("reason", "").strip()

    if not date_text or not reason:
        return redirect(url_for(
            "manage_students_page",
            message="يرجى تحديد تاريخ التعطيل وسببه"
        ))

    conn = get_db_connection()

    existing = conn.execute(
        """
        SELECT id
        FROM custom_days_off
        WHERE teacher_id=? AND date=?
        LIMIT 1
        """,
        (teacher_id, date_text)
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE custom_days_off
            SET reason=?
            WHERE id=?
            """,
            (reason, existing["id"])
        )
    else:
        conn.execute(
            """
            INSERT INTO custom_days_off (teacher_id, date, reason)
            VALUES (?, ?, ?)
            """,
            (teacher_id, date_text, reason)
        )

    if date_text == datetime.now().strftime("%Y-%m-%d"):
        conn.execute(
            """
            INSERT INTO teacher_settings (teacher_id, attendance_open)
            VALUES (?, 0)
            ON CONFLICT(teacher_id)
            DO UPDATE SET attendance_open=0
            """,
            (teacher_id,)
        )

    conn.commit()
    conn.close()

    return redirect(url_for(
        "manage_students_page",
        message="تم حفظ يوم التعطيل"
    ))


@app.route("/delete_day_off/<int:day_id>", methods=["POST"])
def delete_day_off(day_id):
    if session.get("role") != "teacher":
        return redirect(url_for("home"))

    teacher_id = session.get("user_id")

    conn = get_db_connection()
    conn.execute(
        """
        DELETE FROM custom_days_off
        WHERE id=? AND teacher_id=?
        """,
        (day_id, teacher_id)
    )
    conn.commit()
    conn.close()

    return redirect(url_for(
        "manage_students_page",
        message="تم حذف يوم التعطيل"
    ))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)