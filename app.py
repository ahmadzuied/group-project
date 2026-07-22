from flask import Flask, request, render_template, redirect, session, jsonify, url_for
from flask_cors import CORS
from werkzeug.security import check_password_hash
import sqlite3
from datetime import datetime
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "attendance.db")

TOTAL_LECTURES = 15

app = Flask(__name__)
app.secret_key = "attendance-system-secret-key"
CORS(app)


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_recommendation(percentage):
    if percentage >= 80:
        return "ممتاز", "✅ حضورك ممتاز، استمر بهذا المستوى."
    elif percentage >= 50:
        return "متوسط", "⚠️ حضورك متوسط، حاول الالتزام أكثر بالمحاضرات."
    else:
        return "ضعيف", "❌ حضورك ضعيف، يجب تحسين الالتزام بالحضور."


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

    setting = conn.execute(
        "SELECT attendance_open FROM settings ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if not setting or setting["attendance_open"] != 1:
        conn.close()
        return redirect(url_for(
            "attendance_page",
            message="❌ تسجيل الحضور مغلق حالياً"
        ))

    allowed_course = conn.execute(
        """
        SELECT courses.course_id, courses.course_name
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

    data = request.get_json()
    action = data.get("action")

    if action == "open":
        value = 1
        message = "✅ تسجيل الحضور مفتوح حالياً"
    elif action == "close":
        value = 0
        message = "❌ تسجيل الحضور مغلق حالياً"
    else:
        return jsonify({"message": "❌ أمر غير صحيح"}), 400

    conn = get_db_connection()

    row = conn.execute(
        "SELECT id FROM settings ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if row:
        conn.execute(
            "UPDATE settings SET attendance_open=? WHERE id=?",
            (value, row["id"])
        )
    else:
        conn.execute(
            "INSERT INTO settings (attendance_open) VALUES (?)",
            (value,)
        )

    conn.commit()
    conn.close()

    return jsonify({"message": message})


@app.route("/attendance_status")
def attendance_status():
    conn = get_db_connection()

    setting = conn.execute(
        "SELECT attendance_open FROM settings ORDER BY id DESC LIMIT 1"
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
            "level": level
        })

    conn.close()

    return jsonify({"reports": reports})


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)