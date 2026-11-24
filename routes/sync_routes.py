from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from typing import Optional, List
import os
import io
import json
import shutil
import psycopg2
import random
from datetime import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from database import get_db, get_system_settings
from auth import get_current_user

router = APIRouter(prefix="/api/cbt/sync", tags=["Sync"])

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SIAK_UPLOADS_DIR = os.path.join(PROJECT_ROOT, "apiNextSiak", "static", "uploads")
CBT_UPLOADS_DIR = os.path.join(PROJECT_ROOT, "apiCbt", "uploads")

def sync_siak_asset_to_cbt(asset_path: str):
    """Menyalin file aset SIAK (logo, kop surat, scan ttd kepsek) ke folder uploads CBT agar selalu sinkron dan offline-ready."""
    if not asset_path or not isinstance(asset_path, str):
        return
    prefix = "/static/uploads/"
    if not asset_path.startswith(prefix):
        return
    rel_path = asset_path[len(prefix):].lstrip("/\\")
    if not rel_path or ".." in rel_path:
        return
    src = os.path.join(SIAK_UPLOADS_DIR, rel_path)
    dst = os.path.join(CBT_UPLOADS_DIR, rel_path)
    try:
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if (not os.path.isfile(dst)) or (os.path.getmtime(src) > os.path.getmtime(dst)) or (os.path.getsize(src) != os.path.getsize(dst)):
                shutil.copy2(src, dst)
    except Exception as e:
        print(f"Peringatan: Gagal menyalin aset SIAK '{asset_path}': {e}")

SPECIAL_CHARS = ['@', '#', '$', '%', '&', '*', '!', '?']

def generate_exam_password() -> str:
    """Menghasilkan password kartu login berupa 6 digit angka acak + 1 karakter unik"""
    digits = f"{random.randint(100000, 999999)}"
    special = random.choice(SPECIAL_CHARS)
    return f"{digits}{special}"

PG_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "postgres",
    "password": "root",
    "dbname": "db_sekolah"
}

def get_pg_connection():
    settings = get_system_settings(include_secrets=True)
    return psycopg2.connect(
        host=settings.get("siak_pg_host") or PG_CONFIG["host"],
        port=int(settings.get("siak_pg_port") or PG_CONFIG["port"]),
        user=settings.get("siak_pg_user") or PG_CONFIG["user"],
        password=settings.get("siak_pg_password") if settings.get("siak_pg_password") is not None else PG_CONFIG["password"],
        dbname=settings.get("siak_pg_dbname") or PG_CONFIG["dbname"],
        connect_timeout=4,
    )

@router.post("/pull-from-siak")
def pull_data_from_siak(current_user: dict = Depends(get_current_user)):
    """
    Menarik snapshot data Siswa, Kelas, Guru, dan Profil Sekolah dari database SIAK (PostgreSQL)
    sesuai kebijakan sinkronisasi yang diatur di Pengaturan Sistem CBT.
    """
    user_role = (current_user.get("role") or "").lower()
    is_admin = "admin" in user_role or "staff" in user_role or "superadmin" in user_role
    if not is_admin:
        raise HTTPException(
            status_code=403,
            detail="Akses ditolak: Hanya Administrator atau Panitia CBT yang dapat melakukan sinkronisasi data SIAK."
        )

    sys_settings = get_system_settings(include_secrets=False)
    include_classes = bool(sys_settings.get("sync_include_classes", 1))
    include_students = bool(sys_settings.get("sync_include_students", 1))
    include_teachers = bool(sys_settings.get("sync_include_teachers", 1))
    include_school = bool(sys_settings.get("sync_include_school_profile", 1))
    preserve_passwords = bool(sys_settings.get("sync_preserve_exam_passwords", 1))

    try:
        pg_conn = get_pg_connection()
        pg_cur = pg_conn.cursor()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal menghubungkan ke database SIAK: {str(e)}")

    db = get_db()
    cursor = db.cursor()

    try:
        total_classes = 0
        total_students = 0
        total_teachers = 0

        # 1. Sinkron Kelas (Deduplikasi unik per nama kelas)
        if include_classes:
            pg_cur.execute("""
                SELECT MIN(id) as id, class_name, MIN(grade) as grade, MAX(major_name) as major_name 
                FROM classes 
                WHERE class_name IS NOT NULL AND class_name != ''
                GROUP BY class_name
                ORDER BY MIN(grade), class_name
            """)
            pg_classes = pg_cur.fetchall()

            cursor.execute("DELETE FROM cbt_synced_classes")
            for cls in pg_classes:
                cursor.execute("""
                    INSERT INTO cbt_synced_classes (id, name, grade, major_code, synced_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (cls[0], cls[1], cls[2], cls[3]))
            total_classes = len(pg_classes)
        else:
            cursor.execute("SELECT COUNT(*) FROM cbt_synced_classes")
            total_classes = cursor.fetchone()[0]

        # 2. Sinkron Siswa (Beserta Nama Kelas & NIK)
        if include_students:
            pg_cur.execute("""
                SELECT s.id, s.nis, s.nisn, s.name, s.classid, c.class_name, s.grade, s.major_name, s.sex, s.photo, s.nik
                FROM students s
                LEFT JOIN classes c ON s.classid = c.id
                WHERE s.is_active = 1 OR s.status = 'aktif' OR s.status IS NULL
                ORDER BY c.class_name, s.name
            """)
            pg_students = pg_cur.fetchall()

            existing_passwords = {}
            if preserve_passwords:
                cursor.execute("SELECT id, exam_password FROM cbt_synced_students WHERE exam_password IS NOT NULL")
                existing_passwords = {r[0]: r[1] for r in cursor.fetchall()}

            cursor.execute("DELETE FROM cbt_synced_students")
            class_counts = {}
            for stu in pg_students:
                class_name = stu[5] or "-"
                class_counts[class_name] = class_counts.get(class_name, 0) + 1
                stu_id = stu[0]
                exam_pwd = existing_passwords.get(stu_id) or generate_exam_password()
                cursor.execute("""
                    INSERT INTO cbt_synced_students (id, nis, nisn, name, class_id, class_name, grade, major_code, gender, photo, nik, exam_password, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (stu[0], stu[1], stu[2], stu[3], stu[4], class_name, stu[6], stu[7], stu[8], stu[9], stu[10], exam_pwd))

            # Update student_count di tabel cbt_synced_classes
            for c_name, count in class_counts.items():
                cursor.execute("UPDATE cbt_synced_classes SET student_count = ? WHERE name = ?", (count, c_name))
            total_students = len(pg_students)
        else:
            cursor.execute("SELECT COUNT(*) FROM cbt_synced_students")
            total_students = cursor.fetchone()[0]

        # 3. Sinkron Guru
        if include_teachers:
            pg_cur.execute("""
                SELECT id, nip, name, email
                FROM teachers
                WHERE is_active = 1 OR is_active IS NULL
                ORDER BY name
            """)
            pg_teachers = pg_cur.fetchall()

            cursor.execute("DELETE FROM cbt_synced_teachers")
            for tch in pg_teachers:
                cursor.execute("""
                    INSERT INTO cbt_synced_teachers (id, nip, name, email, synced_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (tch[0], tch[1], tch[2], tch[3]))
            total_teachers = len(pg_teachers)

            # Sinkron Alokasi Mengajar Guru (Lesson & Subjects) Khusus Semester Aktif
            try:
                pg_cur.execute("""
                    SELECT t.id as teacher_id, t.name as teacher_name, t.nip,
                           s.id as subject_id, s.name as subject_name,
                           c.id as class_id, c.class_name, c.grade
                    FROM lesson l
                    JOIN teachers t ON l.teacher_id = t.id
                    JOIN subjects s ON l.subject_id = s.id
                    JOIN classes c ON l.classid = c.id
                    LEFT JOIN academic_years ay ON l.academic_year_id = ay.id
                    WHERE (t.is_active = 1 OR t.is_active IS NULL)
                      AND (
                          l.academic_year_id = (SELECT id FROM academic_years WHERE is_active = 1 LIMIT 1)
                          OR NOT EXISTS (SELECT 1 FROM lesson l2 JOIN academic_years ay2 ON l2.academic_year_id = ay2.id WHERE ay2.is_active = 1)
                      )
                    ORDER BY t.name, s.name, c.class_name
                """)
                pg_lessons = pg_cur.fetchall()
                cursor.execute("DELETE FROM cbt_synced_teacher_classes")
                for les in pg_lessons:
                    cursor.execute("""
                        INSERT INTO cbt_synced_teacher_classes
                        (teacher_id, teacher_name, nip, subject_id, subject_name, class_id, class_name, grade, synced_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (les[0], les[1], les[2], les[3], les[4], les[5], les[6], les[7]))
            except Exception as e_les:
                print("Peringatan: Gagal sinkron alokasi mengajar guru:", e_les)
        else:
            cursor.execute("SELECT COUNT(*) FROM cbt_synced_teachers")
            total_teachers = cursor.fetchone()[0]

        # 4. Sinkron Profil & Kop Sekolah dari SIAK
        if include_school:
            try:
                pg_cur.execute("""
                    SELECT id, school_name, npsn, logo, address, phone, email, district, regency, province,
                           postal_code, accreditation, headmaster_name, headmaster_nip, letterhead,
                           headmaster_signature, school_type
                    FROM school_profile ORDER BY id ASC LIMIT 1
                """)
                sch = pg_cur.fetchone()
                if sch:
                    cursor.execute("DELETE FROM cbt_synced_school_profile")
                    cursor.execute("""
                        INSERT INTO cbt_synced_school_profile (
                            id, school_name, npsn, logo, address, phone, email, district, regency, province,
                            postal_code, accreditation, headmaster_name, headmaster_nip, letterhead,
                            headmaster_signature, school_type, synced_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, sch)
                    sync_siak_asset_to_cbt(sch[3])   # logo
                    sync_siak_asset_to_cbt(sch[14])  # letterhead (kop surat)
                    sync_siak_asset_to_cbt(sch[15])  # headmaster_signature (scan ttd kepsek)
            except Exception as e_sch:
                print("Peringatan: Gagal sinkron profil sekolah:", e_sch)

        # 5. Sinkronkan Tahun Ajaran & Semester Aktif dari SIAK ke Pengaturan Sistem CBT
        active_academic_year = None
        active_semester = None
        try:
            pg_cur.execute("SELECT year, semester FROM academic_years WHERE is_active = 1 LIMIT 1")
            act_ay = pg_cur.fetchone()
            if act_ay:
                active_academic_year = act_ay[0]
                active_semester = act_ay[1]
                cursor.execute("""
                    UPDATE cbt_system_settings 
                    SET academic_year = ?, semester = ?, updated_at = CURRENT_TIMESTAMP
                """, (active_academic_year, active_semester))
        except Exception as e_ay:
            print("Peringatan: Gagal sinkron tahun ajaran aktif:", e_ay)

        db.commit()

        return {
            "success": True,
            "message": "Sinkronisasi data dari SIAK berhasil!",
            "summary": {
                "total_classes": total_classes,
                "total_students": total_students,
                "total_teachers": total_teachers,
                "academic_year": active_academic_year,
                "semester": active_semester,
                "synced_at": datetime.now().isoformat()
            }
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Terjadi kesalahan saat memproses data: {str(e)}")
    finally:
        pg_conn.close()
        db.close()

@router.get("/status")
def get_sync_status():
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT COUNT(*) FROM cbt_synced_classes")
    total_classes = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM cbt_synced_students")
    total_students = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM cbt_synced_teachers")
    total_teachers = cursor.fetchone()[0]

    cursor.execute("SELECT synced_at FROM cbt_synced_students ORDER BY synced_at DESC LIMIT 1")
    last_row = cursor.fetchone()
    last_synced = last_row[0] if last_row else None

    cursor.execute("SELECT academic_year, semester FROM cbt_system_settings LIMIT 1")
    ay_row = cursor.fetchone()
    academic_year = ay_row[0] if ay_row else None
    semester = ay_row[1] if ay_row else None

    db.close()

    return {
        "success": True,
        "total_classes": total_classes,
        "total_students": total_students,
        "total_teachers": total_teachers,
        "last_synced": last_synced,
        "academic_year": academic_year,
        "semester": semester
    }

@router.get("/classes")
def get_synced_classes():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT MIN(id) as id, name, MIN(grade) as grade, MAX(major_code) as major_code, SUM(student_count) as student_count
        FROM cbt_synced_classes
        GROUP BY name
        ORDER BY MIN(grade), name
    """)
    classes = [dict(row) for row in cursor.fetchall()]
    db.close()
    return {"success": True, "classes": classes}

@router.get("/teachers")
def get_synced_teachers():
    """Mengambil seluruh daftar guru yang tersinkron dari SIAKAD untuk penugasan pembuat soal / pengawas"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT id, name, nip, email
        FROM cbt_synced_teachers
        ORDER BY name ASC
    """)
    teachers = [dict(row) for row in cursor.fetchall()]
    db.close()
    return {"success": True, "teachers": teachers}

@router.get("/my-teaching-classes")
def get_my_teaching_classes(
    teacher_name: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Mengambil daftar mata pelajaran dan kelas yang HANYA diajar oleh guru yang bersangkutan.
    Jika diakses oleh Administrator, mengembalikan seluruh kelas dan seluruh mata pelajaran,
    atau guru tertentu jika menyertakan parameter `teacher_name`.
    """
    db = get_db()
    cursor = db.cursor()

    role = (current_user.get("role") or "").lower()
    is_admin = "admin" in role or "staff" in role or "superadmin" in role

    target_name = (current_user.get("name") or "").strip()
    if teacher_name and teacher_name.strip() and is_admin:
        target_name = teacher_name.strip()

    if is_admin and not (teacher_name and teacher_name.strip()):
        # Administrator: Tampilkan seluruh kelas dan seluruh mata pelajaran
        cursor.execute("""
            SELECT MIN(id) as id, name, MIN(grade) as grade, MAX(major_code) as major_code, SUM(student_count) as student_count
            FROM cbt_synced_classes
            GROUP BY name
            ORDER BY MIN(grade), name
        """)
        all_classes = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT DISTINCT subject_name FROM cbt_synced_teacher_classes WHERE subject_name IS NOT NULL AND subject_name != '' ORDER BY subject_name ASC")
        subjects = [r[0] for r in cursor.fetchall()]
        if not subjects:
            cursor.execute("SELECT DISTINCT subject_name FROM cbt_question_banks WHERE subject_name IS NOT NULL AND subject_name != '' ORDER BY subject_name ASC")
            subjects = [r[0] for r in cursor.fetchall()]

        cursor.execute("SELECT id, title, subject_name, grade, total_questions FROM cbt_question_banks ORDER BY title ASC")
        banks = [dict(r) for r in cursor.fetchall()]

        db.close()
        return {
            "success": True,
            "is_admin": True,
            "teacher": {"name": current_user.get("name") or "Administrator", "nip": "-"},
            "subjects": subjects,
            "classes": all_classes,
            "classes_by_subject": {s: all_classes for s in subjects},
            "banks": banks
        }

    # Guru: Ambil alokasi mengajar guru tersebut dari cbt_synced_teacher_classes
    int_id = None
    try:
        cand_id = current_user.get("teacher_id") if str(current_user.get("teacher_id")).isdigit() else current_user.get("id")
        if cand_id is not None and str(cand_id).isdigit():
            int_id = int(cand_id)
    except Exception:
        int_id = None

    target_nip = (current_user.get("nip") or current_user.get("username") or "").strip()
    target_name = (current_user.get("name") or "").strip()

    cursor.execute("""
        SELECT DISTINCT subject_name, class_name, grade, class_id
        FROM cbt_synced_teacher_classes
        WHERE (%s::int IS NOT NULL AND teacher_id = %s::int)
           OR (%s != '' AND nip = %s)
           OR LOWER(TRIM(%s)) LIKE CONCAT('%%', LOWER(TRIM(teacher_name)), '%%')
           OR LOWER(TRIM(teacher_name)) LIKE CONCAT('%%', LOWER(TRIM(%s)), '%%')
        ORDER BY subject_name ASC, grade ASC, class_name ASC
    """, (int_id, int_id, target_nip, target_nip, target_name, target_name))
    assignments = [dict(r) for r in cursor.fetchall()]

    # Cari profil guru
    cursor.execute("""
        SELECT id, name, nip, email FROM cbt_synced_teachers
        WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s))
           OR LOWER(TRIM(name)) LIKE LOWER(TRIM(%s))
        LIMIT 1
    """, (target_name, f"%{target_name}%"))
    row_t = cursor.fetchone()
    teacher_profile = dict(row_t) if row_t else {
        "id": current_user.get("teacher_id") or current_user.get("id"),
        "name": target_name,
        "nip": current_user.get("nip") or "-"
    }

    # Format struktur data
    subjects_set = set()
    classes_by_subject = {}
    classes_map = {}

    for item in assignments:
        s_name = item["subject_name"]
        c_name = item["class_name"]
        grade = item.get("grade") or 10
        c_id = item.get("class_id") or 0

        subjects_set.add(s_name)
        if s_name not in classes_by_subject:
            classes_by_subject[s_name] = []

        cls_obj = {"id": c_id, "name": c_name, "grade": grade}
        if not any(c["name"] == c_name for c in classes_by_subject[s_name]):
            classes_by_subject[s_name].append(cls_obj)

        if c_name not in classes_map:
            classes_map[c_name] = cls_obj

    # Ambil bank soal milik guru (atau bank soal dengan mapel yang diampu guru)
    user_teacher_id = int_id or 0
    cursor.execute("""
        SELECT id, title, subject_name, grade, total_questions, teacher_name
        FROM cbt_question_banks
        WHERE LOWER(TRIM(teacher_name)) = LOWER(TRIM(%s))
           OR teacher_id = %s
           OR subject_name = ANY(%s)
        ORDER BY title ASC
    """, (target_name, user_teacher_id, list(subjects_set) if subjects_set else ['']))
    banks = [dict(r) for r in cursor.fetchall()]

    # Fallback: jika guru belum memiliki entri di cbt_synced_teacher_classes,
    # gunakan mapel dari bank soal miliknya
    for b in banks:
        if b.get("subject_name") and b["subject_name"] not in subjects_set:
            subjects_set.add(b["subject_name"])
            if b["subject_name"] not in classes_by_subject:
                classes_by_subject[b["subject_name"]] = list(classes_map.values())

    unique_subjects = sorted(list(subjects_set))
    unique_classes = sorted(list(classes_map.values()), key=lambda x: (x.get("grade", 0), x["name"]))

    db.close()
    return {
        "success": True,
        "is_admin": False,
        "teacher": teacher_profile,
        "subjects": unique_subjects,
        "classes": unique_classes,
        "classes_by_subject": classes_by_subject,
        "banks": banks
    }

def _resolve_user_student_access(cursor, current_user: Optional[dict]):
    role = (current_user.get("role") or "").lower() if current_user else "admin"
    is_admin = role in ("admin", "superadmin", "administrator", "staff")
    is_teacher = role in ("teacher", "guru")

    teacher_classes = []
    if is_teacher and current_user:
        int_id = None
        try:
            cand_id = current_user.get("teacher_id") if str(current_user.get("teacher_id")).isdigit() else current_user.get("id")
            if cand_id is not None and str(cand_id).isdigit():
                int_id = int(cand_id)
        except Exception:
            int_id = None

        target_nip = (current_user.get("nip") or current_user.get("username") or "").strip()
        target_name = (current_user.get("name") or "").strip()

        cursor.execute("""
            SELECT DISTINCT class_name
            FROM cbt_synced_teacher_classes
            WHERE (%s::int IS NOT NULL AND teacher_id = %s::int)
               OR (%s != '' AND nip = %s)
               OR LOWER(TRIM(%s)) LIKE CONCAT('%%', LOWER(TRIM(teacher_name)), '%%')
               OR LOWER(TRIM(teacher_name)) LIKE CONCAT('%%', LOWER(TRIM(%s)), '%%')
            ORDER BY class_name ASC
        """, (int_id, int_id, target_nip, target_nip, target_name, target_name))
        for row in cursor.fetchall():
            if row[0] and row[0] not in teacher_classes:
                teacher_classes.append(row[0])

        # Fallback 1: Bank Soal yang diampu guru
        if not teacher_classes:
            cursor.execute("""
                SELECT DISTINCT subject_name FROM cbt_question_banks
                WHERE LOWER(TRIM(teacher_name)) = LOWER(TRIM(%s)) OR teacher_id = %s
            """, (target_name, int_id or 0))
            sub_names = [r[0] for r in cursor.fetchall() if r[0]]
            if sub_names:
                cursor.execute("""
                    SELECT DISTINCT class_name FROM cbt_synced_teacher_classes
                    WHERE subject_name = ANY(%s)
                """, (sub_names,))
                for row in cursor.fetchall():
                    if row[0] and row[0] not in teacher_classes:
                        teacher_classes.append(row[0])

        # Fallback 2: cbt_exams target_classes
        if not teacher_classes:
            cursor.execute("SELECT target_classes FROM cbt_exams WHERE created_by = %s", (current_user.get("id"),))
            for row in cursor.fetchall():
                try:
                    tc = json.loads(row[0] or "[]")
                    for c in tc:
                        if c and c != "all" and c not in teacher_classes:
                            teacher_classes.append(c)
                except Exception:
                    pass

        # Fallback 3: cbt_exam_subjects
        if not teacher_classes:
            cursor.execute("""
                SELECT target_classes FROM cbt_exam_subjects 
                WHERE teacher_id = %s OR LOWER(TRIM(teacher_name)) = LOWER(TRIM(%s))
            """, (int_id, target_name))
            for row in cursor.fetchall():
                try:
                    tc = json.loads(row[0] or "[]")
                    for c in tc:
                        if c and c != "all" and c not in teacher_classes:
                            teacher_classes.append(c)
                except Exception:
                    pass

    return {
        "role": role,
        "is_admin": is_admin,
        "is_teacher": is_teacher,
        "teacher_classes": teacher_classes
    }


def _query_students_data(cursor, access: dict, class_name: Optional[str] = None, grade: Optional[int] = None, search: Optional[str] = None):
    is_teacher = access["is_teacher"]
    teacher_classes = access["teacher_classes"]

    if is_teacher and not teacher_classes:
        return [], []

    where_clauses = ["1=1"]
    params = []

    if is_teacher:
        if class_name and class_name != "all" and class_name in teacher_classes:
            where_clauses.append("s.class_name = %s")
            params.append(class_name)
        else:
            where_clauses.append("s.class_name = ANY(%s)")
            params.append(teacher_classes)
    else:
        if class_name and class_name != "all":
            where_clauses.append("s.class_name = %s")
            params.append(class_name)
        if grade is not None:
            where_clauses.append("s.grade = %s")
            params.append(grade)

    if search and search.strip():
        s_term = f"%{search.strip().lower()}%"
        where_clauses.append("(LOWER(s.name) LIKE %s OR LOWER(s.nis) LIKE %s OR LOWER(s.nisn) LIKE %s OR LOWER(s.class_name) LIKE %s)")
        params.extend([s_term, s_term, s_term, s_term])

    where_sql = " AND ".join(where_clauses)
    cursor.execute(f"""
        SELECT s.id, s.nis, s.nisn, s.nik, s.name, s.class_id, s.class_name, s.grade, s.major_code,
               s.gender, s.photo, s.exam_password, s.synced_at,
               a.room_name, a.session_name, a.seat_number
        FROM cbt_synced_students s
        LEFT JOIN cbt_student_allocations a ON s.id = a.student_id
        WHERE {where_sql}
        ORDER BY s.grade ASC, s.class_name ASC, s.name ASC
    """, params)
    students = [dict(row) for row in cursor.fetchall()]

    # Available classes
    if is_teacher:
        cursor.execute("""
            SELECT DISTINCT name, grade FROM cbt_synced_classes
            WHERE name = ANY(%s)
            ORDER BY grade ASC, name ASC
        """, (teacher_classes,))
        classes_rows = [dict(r) for r in cursor.fetchall()]
        if not classes_rows:
            classes_rows = [{"name": c, "grade": 10} for c in teacher_classes]
    else:
        cursor.execute("SELECT DISTINCT name, grade FROM cbt_synced_classes ORDER BY grade ASC, name ASC")
        classes_rows = [dict(r) for r in cursor.fetchall()]
        if not classes_rows:
            cursor.execute("SELECT DISTINCT class_name as name, grade FROM cbt_synced_students WHERE class_name IS NOT NULL ORDER BY grade ASC, class_name ASC")
            classes_rows = [dict(r) for r in cursor.fetchall()]

    return students, classes_rows


@router.get("/students")
def get_synced_students(
    class_name: Optional[str] = None,
    grade: Optional[int] = None,
    search: Optional[str] = None,
    current_user: Optional[dict] = Depends(get_current_user)
):
    """
    Mengambil data siswa tersinkron CBT.
    - Role Admin / Staff: Menampilkan seluruh siswa dengan filter rombel/tingkat/pencarian bebas.
    - Role Guru: KHUSUS menampilkan siswa pada kelas/rombel yang diajar oleh guru yang bersangkutan.
    """
    db = get_db()
    cursor = db.cursor()
    try:
        access = _resolve_user_student_access(cursor, current_user)
        students, classes_rows = _query_students_data(cursor, access, class_name, grade, search)

        total_students = len(students)
        total_male = sum(1 for s in students if str(s.get("gender") or "").lower() in ("male", "l", "laki-laki"))
        total_female = sum(1 for s in students if str(s.get("gender") or "").lower() in ("female", "p", "perempuan"))
        total_allocated = sum(1 for s in students if s.get("room_name"))
        total_classes = len(set(s.get("class_name") for s in students if s.get("class_name")))

        return {
            "success": True,
            "role": access["role"],
            "is_teacher": access["is_teacher"],
            "is_admin": access["is_admin"],
            "teacher_classes": access["teacher_classes"] if access["is_teacher"] else None,
            "classes": classes_rows,
            "students": students,
            "summary": {
                "total_students": total_students,
                "total_male": total_male,
                "total_female": total_female,
                "total_allocated": total_allocated,
                "total_classes": total_classes,
            }
        }
    finally:
        db.close()


@router.get("/students/export-excel")
def export_students_excel(
    class_name: Optional[str] = None,
    grade: Optional[int] = None,
    search: Optional[str] = None,
    current_user: Optional[dict] = Depends(get_current_user)
):
    """
    Export daftar siswa dalam format Microsoft Excel (.xlsx).
    Menerapkan hak akses role: Guru hanya dapat mengekspor siswa dari kelas yang diajar.
    """
    db = get_db()
    cursor = db.cursor()
    try:
        access = _resolve_user_student_access(cursor, current_user)
        students, _ = _query_students_data(cursor, access, class_name, grade, search)

        cursor.execute("SELECT * FROM cbt_synced_school_profile ORDER BY id ASC LIMIT 1")
        sch_row = cursor.fetchone()
        school_name = sch_row["school_name"] if sch_row and sch_row.get("school_name") else "SISTEM CBT SEKOLAH"
    finally:
        db.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data Siswa"
    ws.views.sheetView[0].showGridLines = True

    # Styling
    font_title = Font(name="Calibri", size=14, bold=True, color="1E293B")
    font_sub = Font(name="Calibri", size=10, italic=True, color="64748B")
    font_header = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    font_body = Font(name="Calibri", size=10, color="0F172A")
    font_mono = Font(name="Consolas", size=10, bold=True, color="1E293B")

    fill_header = PatternFill(start_color="312E81", end_color="312E81", fill_type="solid")
    fill_zebra = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1")
    )

    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")

    # Banner Header
    ws.merge_cells("A1:K1")
    ws["A1"] = school_name.upper()
    ws["A1"].font = font_title
    ws["A1"].alignment = align_center

    scope_title = f"DAFTAR DATA PESERTA DIDIK CBT — {class_name if class_name and class_name != 'all' else 'SEMUA KELAS'}"
    if access["is_teacher"]:
        teacher_display_name = current_user.get("name") if current_user else "-"
        scope_title += f" (GURU: {teacher_display_name})"

    ws.merge_cells("A2:K2")
    ws["A2"] = scope_title
    ws["A2"].font = Font(name="Calibri", size=11, bold=True, color="334155")
    ws["A2"].alignment = align_center

    ws.merge_cells("A3:K3")
    ws["A3"] = f"Dicetak pada: {datetime.now().strftime('%d/%m/%Y %H:%M')} | Total: {len(students)} Siswa"
    ws["A3"].font = font_sub
    ws["A3"].alignment = align_center

    # Header Columns
    headers = [
        "No", "NIS", "NISN", "Nama Peserta Didik", "Kelas / Rombel",
        "Tingkat", "Gender", "Ruang Ujian", "Sesi", "No. Meja", "Password CBT"
    ]

    header_row = 5
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_center
        cell.border = thin_border
    ws.row_dimensions[header_row].height = 26

    # Rows
    for idx, s in enumerate(students, 1):
        row_num = header_row + idx
        gender_code = "L" if str(s.get("gender") or "").lower() in ("male", "l", "laki-laki") else ("P" if str(s.get("gender") or "").lower() in ("female", "p", "perempuan") else "-")

        row_values = [
            idx,
            s.get("nis") or "-",
            s.get("nisn") or "-",
            s.get("name") or "-",
            s.get("class_name") or "-",
            s.get("grade") or "-",
            gender_code,
            s.get("room_name") or "-",
            s.get("session_name") or "-",
            s.get("seat_number") or "-",
            s.get("exam_password") or "-",
        ]

        is_even = (idx % 2 == 0)
        for col_idx, val in enumerate(row_values, 1):
            cell = ws.cell(row=row_num, column=col_idx, value=val)
            cell.font = font_mono if col_idx in (2, 3, 10, 11) else font_body
            cell.alignment = align_left if col_idx == 4 else align_center
            cell.border = thin_border
            if is_even:
                cell.fill = fill_zebra

        ws.row_dimensions[row_num].height = 20

    # Auto fit column width
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = max(len(str(cell.value or "")) for cell in col if cell.row >= header_row)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 10)
    ws.column_dimensions["D"].width = 28

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)

    filename_safe = (class_name or "semua_kelas").replace(" ", "_")
    filename = f"Data_Siswa_{filename_safe}_{datetime.now().strftime('%Y%m%d')}.xlsx"

    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@router.get("/school-profile")
def get_synced_school_profile():
    # 1. Utamakan ambil langsung dari database SIAK (PostgreSQL) agar kop surat & scan TTD kepsek selalu 100% sesuai SIAK terbaru
    try:
        pg_conn = get_pg_connection()
        pg_cur = pg_conn.cursor()
        pg_cur.execute("""
            SELECT id, school_name, npsn, logo, address, phone, email, district, regency, province,
                   postal_code, accreditation, headmaster_name, headmaster_nip, letterhead,
                   headmaster_signature, school_type
            FROM school_profile ORDER BY id ASC LIMIT 1
        """)
        sch = pg_cur.fetchone()
        pg_cur.close()
        pg_conn.close()
        if sch:
            sync_siak_asset_to_cbt(sch[3])   # logo
            sync_siak_asset_to_cbt(sch[14])  # letterhead (kop surat)
            sync_siak_asset_to_cbt(sch[15])  # headmaster_signature (scan ttd kepsek)

            # Perbarui cache SQLite lokal agar tetap tersedia saat SIAK offline
            try:
                db = get_db()
                cursor = db.cursor()
                cursor.execute("DELETE FROM cbt_synced_school_profile")
                cursor.execute("""
                    INSERT INTO cbt_synced_school_profile (
                        id, school_name, npsn, logo, address, phone, email, district, regency, province,
                        postal_code, accreditation, headmaster_name, headmaster_nip, letterhead,
                        headmaster_signature, school_type, synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, sch)
                db.commit()
                db.close()
            except Exception as e_cache:
                print("Peringatan: Gagal update cache profil sekolah:", e_cache)

            data = {
                "id": sch[0],
                "school_name": sch[1],
                "npsn": sch[2],
                "logo": sch[3],
                "address": sch[4],
                "phone": sch[5],
                "email": sch[6],
                "district": sch[7],
                "regency": sch[8],
                "province": sch[9],
                "postal_code": sch[10],
                "accreditation": sch[11],
                "headmaster_name": sch[12],
                "headmaster_nip": sch[13],
                "letterhead": sch[14],
                "headmaster_signature": sch[15],
                "school_type": sch[16]
            }
            return {"success": True, "school": data}
    except Exception as e:
        print("Info: Menggunakan cache SQLite untuk profil sekolah (SIAK offline):", e)

    # 2. Fallback ke cache SQLite jika PostgreSQL SIAK sedang offline
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM cbt_synced_school_profile ORDER BY id ASC LIMIT 1")
    row = cursor.fetchone()
    db.close()
    if row:
        row_dict = dict(row)
        sync_siak_asset_to_cbt(row_dict.get("logo"))
        sync_siak_asset_to_cbt(row_dict.get("letterhead"))
        sync_siak_asset_to_cbt(row_dict.get("headmaster_signature"))
        return {"success": True, "school": row_dict}

    return {
        "success": True,
        "school": {
            "school_name": "SMA Negeri 4 Singaraja",
            "headmaster_name": "Putu Gede Wartawan, S.Pd., M.Pd.",
            "headmaster_nip": "197002241995031003",
            "address": "Jl. Melati, Kelurahan Banjar Jawa",
            "district": "Buleleng",
            "regency": "Buleleng",
            "province": "Bali",
            "letterhead": "/static/uploads/school_letterhead_1791255670_0bd00d.png",
            "logo": "/static/uploads/school_logo_1790832844.png",
            "headmaster_signature": "/static/uploads/headmaster_sig_1791257072_4fd983.png"
        }
    }

@router.post("/generate-exam-passwords")
def generate_all_exam_passwords(req: dict = None, current_user: dict = Depends(get_current_user)):
    """
    Menghasilkan password acak baru (6 digit angka acak + 1 karakter unik)
    untuk seluruh siswa yang tersinkron atau per kelas.
    """
    req = req or {}
    class_name = req.get("class_name")
    
    db = get_db()
    cursor = db.cursor()
    
    query = "SELECT id FROM cbt_synced_students WHERE 1=1"
    params = []
    if class_name and class_name != "all":
        query += " AND class_name = ?"
        params.append(class_name)
        
    cursor.execute(query, tuple(params))
    students = cursor.fetchall()
    
    updated_count = 0
    for s in students:
        new_pwd = generate_exam_password()
        cursor.execute("UPDATE cbt_synced_students SET exam_password = ? WHERE id = ?", (new_pwd, s[0]))
        updated_count += 1
        
    db.commit()
    db.close()
    
    return {
        "success": True,
        "message": f"Berhasil mengacak {updated_count} password ujian siswa (Format: 6 digit angka + 1 karakter unik).",
        "total_updated": updated_count
    }
