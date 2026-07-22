import sqlite3
import os
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "attendance.db")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# حذف الجداول القديمة
c.execute("DROP TABLE IF EXISTS student_courses")
c.execute("DROP TABLE IF EXISTS students")
c.execute("DROP TABLE IF EXISTS courses")
c.execute("DROP TABLE IF EXISTS attendance")
c.execute("DROP TABLE IF EXISTS confirmations")
c.execute("DROP TABLE IF EXISTS assignments")
c.execute("DROP TABLE IF EXISTS settings")
c.execute("DROP TABLE IF EXISTS teacher_settings")
c.execute("DROP TABLE IF EXISTS custom_days_off")

# جدول الطلاب والمحاضرين
c.execute("""
CREATE TABLE students (
    id TEXT PRIMARY KEY,
    name TEXT,
    college TEXT,
    major TEXT,
    year TEXT,
    role TEXT,
    password TEXT
)
""")

# جدول المساقات
# teacher_id يحدد المحاضر المسؤول عن المساق
c.execute("""
CREATE TABLE courses (
    course_id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_name TEXT,
    teacher_id TEXT
)
""")

# جدول ربط الطلاب بالمساقات
c.execute("""
CREATE TABLE student_courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT,
    course_id INTEGER
)
""")

# جدول الحضور
c.execute("""
CREATE TABLE attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT,
    course_id INTEGER,
    date TEXT,
    time TEXT
)
""")

# جدول تأكيد الحضور
c.execute("""
CREATE TABLE confirmations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT,
    date TEXT,
    time TEXT
)
""")

# جدول الواجبات
c.execute("""
CREATE TABLE assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT,
    course_id INTEGER,
    title TEXT,
    deadline TEXT,
    date_added TEXT
)
""")

# جدول الإعدادات: فتح أو إغلاق تسجيل الحضور
c.execute("""
CREATE TABLE settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attendance_open INTEGER DEFAULT 0
)
""")

c.execute("""
CREATE TABLE teacher_settings (
    teacher_id TEXT PRIMARY KEY,
    attendance_open INTEGER DEFAULT 0
)
""")

c.execute("""
CREATE TABLE custom_days_off (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id TEXT,
    date TEXT,
    reason TEXT
)
""")

# فتح تسجيل الحضور مبدئياً
c.execute("INSERT INTO settings (attendance_open) VALUES (1)")

# الطلاب والمحاضرون
# كلمات المرور هنا تتحول إلى Hash قبل التخزين في قاعدة البيانات
users = [
    (
        "20221136",
        "إيناس جودت أحمد الدويك",
        "الهندسة وتكنولوجيا المعلومات",
        "ذكاء اصطناعي",
        "الرابعة",
        "student",
        generate_password_hash("1234")
    ),
    (
        "20221135",
        "جنان جودت أحمد الدويك",
        "الهندسة وتكنولوجيا المعلومات",
        "ذكاء اصطناعي",
        "الرابعة",
        "student",
        generate_password_hash("1234")
    ),
    (
        "20221110",
        "أحمد أيمن فرج زويد",
        "الهندسة وتكنولوجيا المعلومات",
        "الحوسبة النقالة",
        "الثالثة",
        "student",
        generate_password_hash("1234")
    ),
    (
        "20221124",
        "محمد محمود زكي النجار",
        "العلوم والاقتصاد",
        "المحاسبة وإدارة الأعمال",
        "الثانية",
        "student",
        generate_password_hash("1234")
    ),
    (
        "T001",
        "د. أحمد يوسف",
        "الهندسة وتكنولوجيا المعلومات",
        "ذكاء اصطناعي / الحوسبة النقالة",
        "2026",
        "teacher",
        generate_password_hash("teacher123")
    ),
    (
        "T002",
        "د. سارة محمود",
        "العلوم والاقتصاد",
        "المحاسبة وإدارة الأعمال",
        "2026",
        "teacher",
        generate_password_hash("teacher456")
    )
]

c.executemany(
    "INSERT INTO students VALUES (?,?,?,?,?,?,?)",
    users
)

c.executemany(
    "INSERT INTO teacher_settings (teacher_id, attendance_open) VALUES (?, ?)",
    [
        ("T001", 1),
        ("T002", 1)
    ]
)

# المساقات وربطها بالمحاضرين
courses = [
    ("ذكاء اصطناعي", "T001"),
    ("الحوسبة النقالة", "T001"),
    ("المحاسبة وإدارة الأعمال", "T002")
]

c.executemany(
    "INSERT INTO courses (course_name, teacher_id) VALUES (?, ?)",
    courses
)

# ربط الطلاب بالمساقات
student_courses = [
    ("20221136", 1),  # إيناس - ذكاء اصطناعي
    ("20221135", 1),  # جنان - ذكاء اصطناعي
    ("20221110", 2),  # أحمد - الحوسبة النقالة
    ("20221124", 3)   # محمد - المحاسبة وإدارة الأعمال
]

c.executemany(
    "INSERT INTO student_courses (student_id, course_id) VALUES (?, ?)",
    student_courses
)

conn.commit()
conn.close()

print("✅ قاعدة البيانات جاهزة مع تشفير كلمات المرور وربط الطلاب بالمساقات")