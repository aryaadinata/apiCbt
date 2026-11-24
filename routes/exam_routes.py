import random
import string
import json
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from database import get_db
from auth import get_current_user

router = APIRouter(prefix="/api/cbt/exams", tags=["Exams"])

def generate_random_token(length=5):
    """Membuat token acak mudah dibaca (tanpa angka 0/O atau 1/I yang membingungkan)"""
    chars = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    return "".join(random.choice(chars) for _ in range(length))

class ExamSubjectInput(BaseModel):
    subject_name: str
    grade: int = 10
    teacher_name: Optional[str] = None
    teacher_id: Optional[int] = None
    target_classes: Optional[List[str]] = [] # Target rombel khusus untuk mapel ini (misal: ["XI MIPA 1", "XI MIPA 2"] untuk mapel peminatan)
    duration_minutes: int = 90
    total_questions: int = 0
    passing_score: float = 75.0
    max_score: float = 100.0
    bank_id: Optional[int] = None
    exam_date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None

class UpdateExamSubjectRequest(BaseModel):
    subject_name: Optional[str] = None
    grade: Optional[int] = None
    teacher_name: Optional[str] = None
    teacher_id: Optional[int] = None
    target_classes: Optional[List[str]] = None
    duration_minutes: Optional[int] = None
    total_questions: Optional[int] = None
    passing_score: Optional[float] = None
    max_score: Optional[float] = None
    bank_id: Optional[int] = None
    exam_date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    randomize_questions: Optional[bool] = None
    randomize_options: Optional[bool] = None
    show_score: Optional[bool] = None
    show_explanation: Optional[bool] = None
    max_violations: Optional[int] = None

class CreateExamRequest(BaseModel):
    title: str
    exam_type: str = "sas" # 'daily' (Ulangan Harian) | 'sas' (Ujian Sekolah / SAS)
    bank_id: Optional[int] = None # Tidak wajib di awal! Diisi belakangan oleh guru yang ditunjuk
    subject_name: Optional[str] = None # Opsional jika paket ujian multi-mapel
    grade: Optional[int] = 10
    target_classes: List[str] = [] # ["X RPL 1"] or ["all"]
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    duration_minutes: Optional[int] = None # Ditentukan spesifik per mata pelajaran
    token: Optional[str] = None
    token_refresh_interval: Optional[int] = 15 # dalam menit (0 = manual, 15 = standar)
    randomize_questions: bool = True
    randomize_options: bool = True
    show_results: bool = True
    max_violations: int = 3
    subjects: Optional[List[ExamSubjectInput]] = [] # Daftar mapel yang diujikan

class UpdateExamRequest(BaseModel):
    title: str

class UpdateExamStatusRequest(BaseModel):
    status: str # 'draft', 'active', 'completed', 'archived'

class UpdateExamAntiCheatRequest(BaseModel):
    randomize_questions: Optional[bool] = None
    randomize_options: Optional[bool] = None
    show_results: Optional[bool] = None
    max_violations: Optional[int] = None

class UnlockStudentRequest(BaseModel):
    session_id: Optional[int] = None
    session_ids: Optional[List[int]] = None
    reason: Optional[str] = "Dibuka oleh Pengawas / Guru"

class ResetDeviceRequest(BaseModel):
    session_id: int

class ForceSubmitStudentRequest(BaseModel):
    session_id: int

class TokenConfigRequest(BaseModel):
    token_refresh_interval: Optional[int] = None # dalam menit (0 = manual, 15, 30, dll)
    is_token_active: Optional[bool] = None
    token: Optional[str] = None

class SessionActionRequest(BaseModel):
    subject_id: Optional[int] = None
    subject_ids: Optional[List[int]] = None
    action: Optional[str] = "active" # "active", "completed", "idle"

class ScheduleSubjectsRequest(BaseModel):
    exam_date: str # "YYYY-MM-DD"
    start_time: str # "07:30"
    end_time: str # "09:00"
    subject_ids: List[int]

class AssignTeacherRequest(BaseModel):
    teacher_id: Optional[int] = None
    teacher_name: str
    create_bank_if_missing: bool = True

@router.get("")
def list_exams(exam_type: Optional[str] = None, status: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()

    query = """
        SELECT e.*, b.title as bank_title, b.total_questions as total_bank_questions,
               (SELECT COUNT(*) FROM cbt_exam_subjects es WHERE es.exam_id = e.id) as total_subjects,
               (SELECT COUNT(*) FROM cbt_exam_subjects es WHERE es.exam_id = e.id AND es.status = 'ready') as ready_subjects,
               (SELECT COUNT(*) FROM cbt_exam_sessions s WHERE s.exam_id = e.id) as total_participants,
               (SELECT COUNT(*) FROM cbt_exam_sessions s WHERE s.exam_id = e.id AND s.status = 'submitted') as total_submitted,
               (SELECT COUNT(*) FROM cbt_exam_sessions s WHERE s.exam_id = e.id AND s.status = 'locked') as total_locked
        FROM cbt_exams e
        LEFT JOIN cbt_question_banks b ON e.bank_id = b.id
        WHERE 1=1
    """
    params = []

    if exam_type:
        query += " AND e.exam_type = ?"
        params.append(exam_type)

    if status:
        query += " AND e.status = ?"
        params.append(status)

    user_role = (current_user.get("role") or "").lower()
    is_admin = "admin" in user_role or "staff" in user_role or "superadmin" in user_role

    if is_admin:
        # Admin / Panitia: mengatur ujian global untuk 1 sekolah (SAS / PTS / Asesmen Bersama)
        if exam_type:
            if exam_type != "all":
                query += " AND e.exam_type = ?"
                params.append(exam_type)
        else:
            # Default admin hanya menampilkan ujian sekolah (SAS / Global)
            query += " AND e.exam_type = 'sas'"
    else:
        # Akun Guru:
        # Ulangan harian hanya menampilkan ulangan buatan guru tersebut sendiri.
        user_id = current_user.get("id")
        teacher_name = (current_user.get("name") or "").strip()
        int_id = None
        try:
            cand_id = current_user.get("teacher_id") if str(current_user.get("teacher_id")).isdigit() else current_user.get("id")
            if cand_id is not None and str(cand_id).isdigit():
                int_id = int(cand_id)
        except Exception:
            int_id = None

        if exam_type == "daily":
            query += " AND e.exam_type = 'daily' AND (e.created_by = ? OR e.created_by_name = ? OR e.created_by = ?)"
            params.extend([user_id, teacher_name, int_id])
        elif exam_type == "sas":
            query += " AND e.exam_type = 'sas'"
        else:
            # Default guru: ulangan harian miliknya sendiri ATAU ujian sekolah SAS
            query += " AND ((e.exam_type = 'daily' AND (e.created_by = ? OR e.created_by_name = ? OR e.created_by = ?)) OR e.exam_type = 'sas')"
            params.extend([user_id, teacher_name, int_id])

    query += " ORDER BY e.id DESC"
    cursor.execute(query, tuple(params))
    
    exams = []
    for row in cursor.fetchall():
        item = dict(row)
        try:
            item["target_classes"] = json.loads(item["target_classes"])
        except Exception:
            item["target_classes"] = []

        # Ambil daftar mapel dalam ujian jika ada
        cursor.execute("""
            SELECT s.*,
                   COALESCE(s.randomize_questions, b.randomize_questions, 1) as randomize_questions,
                   COALESCE(s.randomize_options, b.randomize_options, 1) as randomize_options,
                   COALESCE(s.show_score, b.show_score, 1) as show_score,
                   COALESCE(s.show_explanation, b.show_explanation, 0) as show_explanation,
                   COALESCE(s.duration_minutes, b.duration_minutes, 90) as duration_minutes,
                   COALESCE(s.passing_score, b.passing_score, 75.0) as passing_score,
                   COALESCE(b.max_violations, 3) as max_violations,
                   b.title as bank_title, b.total_questions as actual_questions
            FROM cbt_exam_subjects s
            LEFT JOIN cbt_question_banks b ON s.bank_id = b.id
            WHERE s.exam_id = ?
            ORDER BY s.id ASC
        """, (item["id"],))
        raw_subjects = [dict(r) for r in cursor.fetchall()]
        for s_row in raw_subjects:
            try:
                s_row["target_classes"] = json.loads(s_row.get("target_classes") or "[]")
            except Exception:
                s_row["target_classes"] = []
        item["subjects"] = raw_subjects

        exams.append(item)

    db.close()
    return {"success": True, "exams": exams}

@router.get("/teacher/my-assignments")
def get_teacher_exam_assignments(current_user: dict = Depends(get_current_user)):
    """Mengambil daftar tugas penulisan soal ujian untuk guru yang sedang login"""
    teacher_name = (current_user.get("name") or "").strip()
    int_id = None
    try:
        cand = current_user.get("teacher_id") if str(current_user.get("teacher_id")).isdigit() else current_user.get("id")
        if cand is not None and str(cand).isdigit():
            int_id = int(cand)
    except Exception:
        int_id = None

    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT s.*,
               COALESCE(s.randomize_questions, b.randomize_questions, 1) as randomize_questions,
               COALESCE(s.randomize_options, b.randomize_options, 1) as randomize_options,
               COALESCE(s.show_score, b.show_score, 1) as show_score,
               COALESCE(s.show_explanation, b.show_explanation, 0) as show_explanation,
               COALESCE(s.duration_minutes, b.duration_minutes, 90) as duration_minutes,
               COALESCE(s.passing_score, b.passing_score, 75.0) as passing_score,
               COALESCE(b.max_violations, 3) as max_violations,
               e.title as exam_title, e.exam_type, e.token, e.target_classes,
               b.title as bank_title, b.total_questions as actual_questions
        FROM cbt_exam_subjects s
        JOIN cbt_exams e ON s.exam_id = e.id
        LEFT JOIN cbt_question_banks b ON s.bank_id = b.id
        WHERE ((%s::int IS NOT NULL AND s.teacher_id = %s::int)
           OR (s.teacher_name IS NOT NULL AND s.teacher_name = %s)
           OR (%s != '' AND s.teacher_name ILIKE CONCAT('%%', %s, '%%')))
           AND (e.exam_type IS NULL OR e.exam_type != 'daily')
        ORDER BY s.id DESC
    """, (int_id, int_id, teacher_name, teacher_name, teacher_name))
    assignments = [dict(r) for r in cursor.fetchall()]
    db.close()
    return {"success": True, "assignments": assignments}

@router.post("")
def create_exam(req: CreateExamRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()

    # Periksa ketersediaan bank soal jika diinput di awal (opsional)
    if req.bank_id:
        cursor.execute("SELECT id, total_questions FROM cbt_question_banks WHERE id = ?", (req.bank_id,))
        bank_row = cursor.fetchone()
        if not bank_row:
            db.close()
            raise HTTPException(status_code=404, detail="Bank soal terpilih tidak ditemukan.")

    user_role = (current_user.get("role") or "").lower()
    is_admin = "admin" in user_role or "staff" in user_role or "superadmin" in user_role

    final_exam_type = req.exam_type if is_admin else "daily"

    # Validasi Hak Mengajar Guru: Hanya untuk kelas & mata pelajaran yang diajar
    if not is_admin:
        teacher_name = (current_user.get("name") or "").strip()
        int_id = None
        try:
            cand_id = current_user.get("teacher_id") if str(current_user.get("teacher_id")).isdigit() else current_user.get("id")
            if cand_id is not None and str(cand_id).isdigit():
                int_id = int(cand_id)
        except Exception:
            int_id = None

        target_nip = (current_user.get("nip") or current_user.get("username") or "").strip()
        cursor.execute("""
            SELECT DISTINCT LOWER(TRIM(subject_name)), LOWER(TRIM(class_name))
            FROM cbt_synced_teacher_classes
            WHERE (%s::int IS NOT NULL AND teacher_id = %s::int)
               OR (%s != '' AND nip = %s)
               OR LOWER(TRIM(%s)) LIKE CONCAT('%%', LOWER(TRIM(teacher_name)), '%%')
               OR LOWER(TRIM(teacher_name)) LIKE CONCAT('%%', LOWER(TRIM(%s)), '%%')
        """, (int_id, int_id, target_nip, target_nip, teacher_name, teacher_name))
        valid_rows = cursor.fetchall()
        if valid_rows:
            valid_subjects = set([r[0] for r in valid_rows if r[0]])
            valid_classes = set([r[1] for r in valid_rows if r[1]])

            # Validasi mata pelajaran
            check_subjs = []
            if req.subject_name:
                check_subjs.append(req.subject_name.strip().lower())
            if req.subjects:
                for s in req.subjects:
                    if s.subject_name:
                        check_subjs.append(s.subject_name.strip().lower())

            for s_check in check_subjs:
                if s_check and not any(s_check in vs or vs in s_check for vs in valid_subjects):
                    db.close()
                    raise HTTPException(
                        status_code=403,
                        detail=f"Mata pelajaran '{s_check}' bukan mata pelajaran yang Anda ampu."
                    )

            # Validasi kelas
            for c_check in req.target_classes:
                if c_check and c_check.strip().lower() not in valid_classes:
                    db.close()
                    raise HTTPException(
                        status_code=403,
                        detail=f"Kelas '{c_check}' bukan kelas yang Anda ajar."
                    )

    token = req.token.strip().upper() if req.token else (
        str(random.randint(1000, 9999)) if final_exam_type == "daily" else generate_random_token(5)
    )

    classes_json = json.dumps(req.target_classes, ensure_ascii=False)
    created_by = current_user.get("id")
    created_by_name = current_user.get("name") or ("Panitia Ujian Sekolah" if is_admin else "Guru")

    # Nama mapel ringkasan
    subject_name = req.subject_name
    if not subject_name:
        if req.subjects and len(req.subjects) > 0:
            names = [s.subject_name for s in req.subjects]
            subject_name = ", ".join(names[:3]) + ("..." if len(names) > 3 else "")
        else:
            subject_name = "Multi-Mapel"

    # Status awal: active jika soal sudah ada, draft/pending jika soal akan diisi belakangan
    is_ready = bool(req.bank_id) or (req.subjects and any(s.bank_id for s in req.subjects))
    initial_status = "active" if is_ready else "draft"

    cursor.execute("""
        INSERT INTO cbt_exams (
            title, exam_type, bank_id, subject_name, grade, target_classes,
            start_date, end_date, duration_minutes, token, is_token_active,
            randomize_questions, randomize_options, show_results, max_violations,
            status, created_by, created_by_name, token_refresh_interval
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        req.title.strip(), final_exam_type, req.bank_id, subject_name, req.grade or 10,
        classes_json, req.start_date, req.end_date, req.duration_minutes or 0, token,
        1 if req.randomize_questions else 0, 1 if req.randomize_options else 0,
        1 if req.show_results else 0, req.max_violations, initial_status,
        created_by, created_by_name,
        req.token_refresh_interval if req.token_refresh_interval is not None else 15
    ))

    exam_id = cursor.fetchone()[0]

    # Simpan daftar mata pelajaran yang diujikan (setiap mapel punya durasi, skor, dan guru yang ditunjuk)
    if req.subjects:
        for s in req.subjects:
            subj_status = "ready" if (s.bank_id and s.bank_id > 0) else "pending_questions"
            s_target_classes = json.dumps(s.target_classes or [], ensure_ascii=False)
            cursor.execute("""
                INSERT INTO cbt_exam_subjects (
                    exam_id, subject_name, grade, teacher_id, teacher_name,
                    duration_minutes, total_questions, passing_score, max_score,
                    bank_id, exam_date, start_time, end_time, target_classes, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                exam_id, s.subject_name.strip(), s.grade, s.teacher_id, s.teacher_name,
                s.duration_minutes or 90, s.total_questions or 0, s.passing_score or 75.0,
                s.max_score or 100.0, s.bank_id, s.exam_date, s.start_time, s.end_time,
                s_target_classes, subj_status
            ))

    db.commit()
    db.close()

    return {
        "success": True,
        "message": f"Paket Ujian '{req.title}' berhasil dibuat!",
        "exam_id": exam_id,
        "token": token,
        "total_subjects": len(req.subjects or [])
    }

@router.get("/{exam_id}")
def get_exam_detail(exam_id: int, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        SELECT e.*, b.title as bank_title, b.total_questions as total_bank_questions
        FROM cbt_exams e
        LEFT JOIN cbt_question_banks b ON e.bank_id = b.id
        WHERE e.id = ?
    """, (exam_id,))
    row = cursor.fetchone()
    if not row:
        db.close()
        raise HTTPException(status_code=404, detail="Ujian tidak ditemukan.")

    exam = dict(row)
    try:
        exam["target_classes"] = json.loads(exam["target_classes"])
    except Exception:
        exam["target_classes"] = []

    # Ambil rincian mata pelajaran dalam ujian
    cursor.execute("""
        SELECT s.*,
               COALESCE(s.randomize_questions, b.randomize_questions, 1) as randomize_questions,
               COALESCE(s.randomize_options, b.randomize_options, 1) as randomize_options,
               COALESCE(s.show_score, b.show_score, 1) as show_score,
               COALESCE(s.show_explanation, b.show_explanation, 0) as show_explanation,
               COALESCE(s.duration_minutes, b.duration_minutes, 90) as duration_minutes,
               COALESCE(s.passing_score, b.passing_score, 75.0) as passing_score,
               COALESCE(b.max_violations, 3) as max_violations,
               b.title as bank_title, b.total_questions as actual_questions
        FROM cbt_exam_subjects s
        LEFT JOIN cbt_question_banks b ON s.bank_id = b.id
        WHERE s.exam_id = ?
        ORDER BY s.id ASC
    """, (exam_id,))
    raw_subjects = [dict(r) for r in cursor.fetchall()]
    for s in raw_subjects:
        try:
            s["target_classes"] = json.loads(s.get("target_classes") or "[]")
        except Exception:
            s["target_classes"] = []
    exam["subjects"] = raw_subjects

    db.close()
    return {"success": True, "exam": exam}

@router.put("/{exam_id}")
def update_exam(exam_id: int, req: UpdateExamRequest, current_user: dict = Depends(get_current_user)):
    """Mengubah nama paket ujian"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id FROM cbt_exams WHERE id = ?", (exam_id,))
    if not cursor.fetchone():
        db.close()
        raise HTTPException(status_code=404, detail="Paket ujian tidak ditemukan.")
    
    cursor.execute("UPDATE cbt_exams SET title = ? WHERE id = ?", (req.title.strip(), exam_id))
    db.commit()
    db.close()
    return {"success": True, "message": "Nama paket ujian berhasil diperbarui."}

@router.delete("/{exam_id}")
def delete_exam(exam_id: int, current_user: dict = Depends(get_current_user)):
    """Menghapus paket ujian beserta data terkait"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id FROM cbt_exams WHERE id = ?", (exam_id,))
    if not cursor.fetchone():
        db.close()
        raise HTTPException(status_code=404, detail="Paket ujian tidak ditemukan.")
    
    # Hapus sesi, jawaban siswa, mapel ujian, dan ujian
    cursor.execute("DELETE FROM cbt_exam_sessions WHERE exam_id = ?", (exam_id,))
    cursor.execute("DELETE FROM cbt_exam_subjects WHERE exam_id = ?", (exam_id,))
    cursor.execute("DELETE FROM cbt_exams WHERE id = ?", (exam_id,))
    db.commit()
    db.close()
    return {"success": True, "message": "Paket ujian berhasil dihapus."}

def _sync_exam_summary_metadata(cursor, exam_id: int):
    """Sinkronkan ringkasan nama mapel dan gabungan rombel target_classes pada tabel cbt_exams."""
    try:
        cursor.execute("SELECT subject_name, target_classes FROM cbt_exam_subjects WHERE exam_id = ? ORDER BY id ASC", (exam_id,))
        rows = cursor.fetchall()
        if rows:
            mapped_names = [r[0] for r in rows if r[0]]
            summary_name = ", ".join(mapped_names[:3]) + ("..." if len(mapped_names) > 3 else "")
            all_cls = []
            for r in rows:
                try:
                    tc = json.loads(r[1] or "[]")
                    if isinstance(tc, list):
                        all_cls.extend(tc)
                except Exception:
                    pass
            unique_cls = list(dict.fromkeys(all_cls))
            cursor.execute("UPDATE cbt_exams SET subject_name = ?, target_classes = ? WHERE id = ?", (
                summary_name, json.dumps(unique_cls, ensure_ascii=False), exam_id
            ))
        else:
            cursor.execute("UPDATE cbt_exams SET subject_name = 'Belum Ada Mapel', target_classes = '[]' WHERE id = ?", (exam_id,))
    except Exception as e:
        print(f"[SYNC EXAM METADATA] Error: {e}")

@router.post("/{exam_id}/subjects")
def add_exam_subject(exam_id: int, req: ExamSubjectInput, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    status = "ready" if (req.bank_id and req.bank_id > 0) else "pending_questions"
    classes_json = json.dumps(req.target_classes or [], ensure_ascii=False)
    cursor.execute("""
        INSERT INTO cbt_exam_subjects (
            exam_id, subject_name, grade, teacher_id, teacher_name,
            duration_minutes, total_questions, passing_score, max_score,
            bank_id, exam_date, start_time, end_time, target_classes, status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        exam_id, req.subject_name.strip(), req.grade, req.teacher_id, req.teacher_name,
        req.duration_minutes or 90, req.total_questions or 0, req.passing_score or 75.0,
        req.max_score or 100.0, req.bank_id, req.exam_date, req.start_time, req.end_time,
        classes_json, status
    ))
    subject_id = cursor.fetchone()[0]
    
    # Otomatis aktifkan status paket ujian jika sebelumnya masih draft
    cursor.execute("UPDATE cbt_exams SET status = 'active' WHERE id = ? AND status = 'draft'", (exam_id,))
    _sync_exam_summary_metadata(cursor, exam_id)

    db.commit()
    db.close()
    return {"success": True, "message": f"Mata pelajaran '{req.subject_name}' berhasil ditambahkan ke ujian.", "subject_id": subject_id}

@router.put("/{exam_id}/subjects/{subject_id}")
def update_exam_subject(exam_id: int, subject_id: int, req: UpdateExamSubjectRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM cbt_exam_subjects WHERE id = ? AND exam_id = ?", (subject_id, exam_id))
    row = cursor.fetchone()
    if not row:
        db.close()
        raise HTTPException(status_code=404, detail="Mata pelajaran tidak ditemukan.")
    
    current = dict(row)
    new_bank_id = req.bank_id if req.bank_id is not None else current["bank_id"]
    new_status = "ready" if (new_bank_id and new_bank_id > 0) else current["status"]

    classes_json = json.dumps(req.target_classes, ensure_ascii=False) if req.target_classes is not None else current.get("target_classes") or "[]"

    rand_q_val = 1 if req.randomize_questions is True else (0 if req.randomize_questions is False else current.get("randomize_questions"))
    rand_opt_val = 1 if req.randomize_options is True else (0 if req.randomize_options is False else current.get("randomize_options"))
    show_score_val = 1 if req.show_score is True else (0 if req.show_score is False else current.get("show_score"))
    show_exp_val = 1 if req.show_explanation is True else (0 if req.show_explanation is False else current.get("show_explanation"))

    cursor.execute("""
        UPDATE cbt_exam_subjects
        SET subject_name = COALESCE(?, subject_name),
            grade = COALESCE(?, grade),
            teacher_name = COALESCE(?, teacher_name),
            teacher_id = COALESCE(?, teacher_id),
            duration_minutes = COALESCE(?, duration_minutes),
            total_questions = COALESCE(?, total_questions),
            passing_score = COALESCE(?, passing_score),
            max_score = COALESCE(?, max_score),
            bank_id = ?,
            exam_date = COALESCE(?, exam_date),
            start_time = COALESCE(?, start_time),
            end_time = COALESCE(?, end_time),
            randomize_questions = COALESCE(?, randomize_questions),
            randomize_options = COALESCE(?, randomize_options),
            show_score = COALESCE(?, show_score),
            show_explanation = COALESCE(?, show_explanation),
            target_classes = ?,
            status = ?
        WHERE id = ? AND exam_id = ?
    """, (
        req.subject_name, req.grade, req.teacher_name, req.teacher_id,
        req.duration_minutes, req.total_questions, req.passing_score, req.max_score,
        new_bank_id, req.exam_date, req.start_time, req.end_time,
        rand_q_val, rand_opt_val, show_score_val, show_exp_val,
        classes_json, new_status, subject_id, exam_id
    ))

    # Jika mapel ini sudah terhubung ke wadah bank soal, sinkronkan juga aturan ke bank soal
    if new_bank_id:
        cursor.execute("""
            UPDATE cbt_question_banks
            SET randomize_questions = COALESCE(?, randomize_questions),
                randomize_options = COALESCE(?, randomize_options),
                show_score = COALESCE(?, show_score),
                show_explanation = COALESCE(?, show_explanation),
                duration_minutes = COALESCE(?, duration_minutes),
                passing_score = COALESCE(?, passing_score),
                max_violations = COALESCE(?, max_violations),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            rand_q_val, rand_opt_val, show_score_val, show_exp_val,
            req.duration_minutes, req.passing_score, req.max_violations,
            new_bank_id
        ))
    _sync_exam_summary_metadata(cursor, exam_id)
    db.commit()
    db.close()
    return {"success": True, "message": "Pengaturan mata pelajaran berhasil diperbarui!"}

@router.delete("/{exam_id}/subjects/{subject_id}")
def delete_exam_subject(exam_id: int, subject_id: int, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM cbt_exam_subjects WHERE id = ? AND exam_id = ?", (subject_id, exam_id))
    _sync_exam_summary_metadata(cursor, exam_id)
    db.commit()
    db.close()
    return {"success": True, "message": "Mata pelajaran berhasil dihapus dari paket ujian."}

@router.put("/{exam_id}/subjects/{subject_id}/assign-teacher")
def assign_subject_teacher(exam_id: int, subject_id: int, req: AssignTeacherRequest, current_user: dict = Depends(get_current_user)):
    """Menugaskan guru sebagai pembuat soal untuk mata pelajaran ujian tertentu"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT s.*, e.title as exam_title FROM cbt_exam_subjects s JOIN cbt_exams e ON s.exam_id = e.id WHERE s.id = ? AND s.exam_id = ?", (subject_id, exam_id))
    subj_row = cursor.fetchone()
    if not subj_row:
        db.close()
        raise HTTPException(status_code=404, detail="Mata pelajaran tidak ditemukan.")

    subj = dict(subj_row)
    t_name = req.teacher_name.strip()
    t_id = req.teacher_id

    bank_id = subj.get("bank_id")
    # Jika belum ada bank_id dan create_bank_if_missing aktif, buatkan wadah bank soal otomatis
    if not bank_id and req.create_bank_if_missing:
        bank_title = f"{subj.get('exam_title', 'Ujian')} - {subj['subject_name']} (Kelas {subj.get('grade', 10)})"
        cursor.execute("""
            INSERT INTO cbt_question_banks (title, subject_name, grade, teacher_id, teacher_name, total_questions, origin)
            VALUES (%s, %s, %s, %s, %s, 0, 'official')
            RETURNING id
        """, (bank_title, subj["subject_name"], subj.get("grade", 10), t_id, t_name))
        bank_id = cursor.fetchone()[0]

    # Update cbt_exam_subjects
    cursor.execute("""
        UPDATE cbt_exam_subjects
        SET teacher_id = ?, teacher_name = ?, bank_id = COALESCE(?, bank_id)
        WHERE id = ? AND exam_id = ?
    """, (t_id, t_name, bank_id, subject_id, exam_id))

    # Jika bank_id ada, update juga pemilik bank soal di cbt_question_banks
    if bank_id:
        cursor.execute("""
            UPDATE cbt_question_banks
            SET teacher_id = ?, teacher_name = ?, origin = 'official'
            WHERE id = ?
        """, (t_id, t_name, bank_id))

    # Kirim notifikasi penugasan ke tabel cbt_notifications hanya untuk ujian resmi sekolah (bukan ulangan harian)
    if subj.get("exam_type") != "daily":
        try:
            cursor.execute("""
                INSERT INTO cbt_notifications (teacher_id, teacher_name, title, message, type, link, is_read, created_at)
                VALUES (%s, %s, %s, %s, 'assignment', '/bank-soal', 0, CURRENT_TIMESTAMP)
            """, (
                t_id,
                t_name,
                f"Penugasan Naskah: {subj['subject_name']}",
                f"Panitia Ujian menugaskan Anda untuk menyusun butir soal mata pelajaran '{subj['subject_name']}' (Kelas {subj.get('grade', 10)}) pada paket ujian '{subj.get('exam_title', 'Ujian Sekolah')}'. Silakan buka menu Bank Soal untuk menginput atau mengimpor naskah soal."
            ))
        except Exception as e_notif:
            print("Gagal menyimpan notifikasi penugasan:", e_notif)

    db.commit()
    db.close()
    return {
        "success": True,
        "message": f"Guru '{t_name}' berhasil ditugaskan sebagai pembuat soal mata pelajaran '{subj['subject_name']}'.",
        "bank_id": bank_id,
        "teacher_name": t_name
    }

@router.post("/{exam_id}/schedule")
def set_exam_schedule(exam_id: int, req: ScheduleSubjectsRequest, current_user: dict = Depends(get_current_user)):
    """Mengatur tanggal dan jam pengerjaan untuk beberapa mata pelajaran sekaligus"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id FROM cbt_exams WHERE id = ?", (exam_id,))
    if not cursor.fetchone():
        db.close()
        raise HTTPException(status_code=404, detail="Paket ujian tidak ditemukan.")
    
    if not req.subject_ids:
        db.close()
        raise HTTPException(status_code=400, detail="Pilih minimal satu mata pelajaran.")
    
    for sid in req.subject_ids:
        cursor.execute("""
            UPDATE cbt_exam_subjects
            SET exam_date = ?, start_time = ?, end_time = ?
            WHERE id = ? AND exam_id = ?
        """, (req.exam_date, req.start_time, req.end_time, sid, exam_id))
    
    # Perbarui start_date dan end_date pada paket ujian
    cursor.execute("""
        SELECT MIN(exam_date), MAX(exam_date)
        FROM cbt_exam_subjects
        WHERE exam_id = ? AND exam_date IS NOT NULL AND exam_date != ''
    """, (exam_id,))
    min_date, max_date = cursor.fetchone()
    if min_date:
        cursor.execute("UPDATE cbt_exams SET start_date = ?, end_date = ? WHERE id = ?", (min_date, max_date, exam_id))
    
    db.commit()
    db.close()
    return {
        "success": True,
        "message": f"{len(req.subject_ids)} mata pelajaran berhasil dijadwalkan pada {req.exam_date} ({req.start_time} - {req.end_time})!"
    }

@router.delete("/{exam_id}/schedule/{subject_id}")
def clear_subject_schedule(exam_id: int, subject_id: int, current_user: dict = Depends(get_current_user)):
    """Menghapus tanggal dan jam dari mata pelajaran terpilih"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE cbt_exam_subjects
        SET exam_date = NULL, start_time = NULL, end_time = NULL
        WHERE id = ? AND exam_id = ?
    """, (subject_id, exam_id))
    
    cursor.execute("""
        SELECT MIN(exam_date), MAX(exam_date)
        FROM cbt_exam_subjects
        WHERE exam_id = ? AND exam_date IS NOT NULL AND exam_date != ''
    """, (exam_id,))
    min_date, max_date = cursor.fetchone()
    cursor.execute("UPDATE cbt_exams SET start_date = ?, end_date = ? WHERE id = ?", (min_date, max_date, exam_id))
    
    db.commit()
    db.close()
    return {"success": True, "message": "Jadwal mata pelajaran berhasil dikosongkan."}

@router.put("/{exam_id}/status")
def update_exam_status(exam_id: int, req: UpdateExamStatusRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE cbt_exams SET status = ? WHERE id = ?", (req.status, exam_id))
    db.commit()
    db.close()
    return {"success": True, "message": f"Status ujian diperbarui menjadi '{req.status}'."}

@router.put("/{exam_id}/anti-cheat")
def update_exam_anti_cheat(exam_id: int, req: UpdateExamAntiCheatRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id FROM cbt_exams WHERE id = ?", (exam_id,))
    if not cursor.fetchone():
        db.close()
        raise HTTPException(status_code=404, detail="Ujian tidak ditemukan.")

    fields = []
    values = []
    if req.randomize_questions is not None:
        fields.append("randomize_questions = ?")
        values.append(1 if req.randomize_questions else 0)
    if req.randomize_options is not None:
        fields.append("randomize_options = ?")
        values.append(1 if req.randomize_options else 0)
    if req.show_results is not None:
        fields.append("show_results = ?")
        values.append(1 if req.show_results else 0)
    if req.max_violations is not None:
        fields.append("max_violations = ?")
        values.append(req.max_violations)

    if fields:
        values.append(exam_id)
        cursor.execute(f"UPDATE cbt_exams SET {', '.join(fields)} WHERE id = ?", tuple(values))
        db.commit()

    db.close()
    return {"success": True, "message": "Pengaturan anti-kecurangan berhasil diperbarui!"}

def get_or_refresh_token(cursor, exam_row):
    """
    Memeriksa apakah interval perubahan token sudah lewat.
    Jika sudah lewat dan interval > 0, otomatis buat token baru dan perbarui database.
    Mengembalikan (current_token, remaining_seconds, is_refreshed).
    """
    interval_minutes = exam_row.get("token_refresh_interval")
    if interval_minutes is None:
        interval_minutes = 15
    
    current_token = exam_row.get("token") or generate_random_token(5)
    updated_at_str = exam_row.get("token_updated_at")
    
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    if not updated_at_str:
        cursor.execute("UPDATE cbt_exams SET token = ?, token_updated_at = ? WHERE id = ?", (current_token, now_str, exam_row["id"]))
        updated_at_str = now_str

    if interval_minutes <= 0:
        return current_token, 0, False

    try:
        if isinstance(updated_at_str, datetime):
            last_updated = updated_at_str
        else:
            clean_str = str(updated_at_str).replace("T", " ").split(".")[0]
            last_updated = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        last_updated = now

    elapsed = int((now - last_updated).total_seconds())
    interval_seconds = interval_minutes * 60

    if elapsed >= interval_seconds:
        new_token = generate_random_token(5)
        cursor.execute("UPDATE cbt_exams SET previous_token = token, token = ?, token_updated_at = ? WHERE id = ?", (new_token, now_str, exam_row["id"]))
        return new_token, interval_seconds, True
    else:
        remaining = max(0, interval_seconds - elapsed)
        return current_token, remaining, False

@router.get("/{exam_id}/test-status")
def get_exam_test_status(exam_id: int, current_user: dict = Depends(get_current_user)):
    """Mengambil status tes aktif: token, countdown refresh, sesi mata pelajaran terpilih, dan monitoring peserta."""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT * FROM cbt_exams WHERE id = ?", (exam_id,))
    exam = cursor.fetchone()
    if not exam:
        db.close()
        raise HTTPException(status_code=404, detail="Paket ujian tidak ditemukan.")

    exam_dict = dict(exam)
    is_completed_exam = (exam_dict.get("status") == "completed")
    if is_completed_exam:
        token = "-"
        remaining_seconds = 0
        is_token_active = False
    else:
        token, remaining_seconds, refreshed = get_or_refresh_token(cursor, exam_dict)
        if refreshed:
            db.commit()
        is_token_active = bool(exam_dict.get("is_token_active", 1))

    # Ambil daftar mapel dalam ujian dengan status sesinya
    cursor.execute("""
        SELECT s.*, b.title as bank_title, b.total_questions as actual_questions
        FROM cbt_exam_subjects s
        LEFT JOIN cbt_question_banks b ON s.bank_id = b.id
        WHERE s.exam_id = ?
        ORDER BY 
            CASE WHEN s.exam_date IS NOT NULL AND s.exam_date != '' THEN 0 ELSE 1 END,
            s.exam_date ASC, s.start_time ASC, s.id ASC
    """, (exam_id,))
    raw_subjects = [dict(r) for r in cursor.fetchall()]
    for s_row in raw_subjects:
        try:
            s_row["target_classes"] = json.loads(s_row.get("target_classes") or "[]")
        except Exception:
            s_row["target_classes"] = []
    
    # Ambil ringkasan peserta real-time
    cursor.execute("SELECT status, COUNT(*) as count FROM cbt_exam_sessions WHERE exam_id = ? GROUP BY status", (exam_id,))
    counts = {r[0]: r[1] for r in cursor.fetchall()}

    in_progress = counts.get("in_progress", 0)
    submitted = counts.get("submitted", 0)
    locked = counts.get("locked", 0)

    # Hitung total siswa di kelas sasaran
    all_target_classes = set()
    e_tc = exam_dict.get("target_classes")
    if isinstance(e_tc, str):
        try:
            e_tc = json.loads(e_tc)
        except Exception:
            e_tc = [e_tc] if e_tc else []
    if isinstance(e_tc, list):
        for c in e_tc:
            if c:
                all_target_classes.add(str(c).strip())

    for s_row in raw_subjects:
        s_tc = s_row.get("target_classes")
        if isinstance(s_tc, str):
            try:
                s_tc = json.loads(s_tc)
            except Exception:
                s_tc = [s_tc] if s_tc else []
        if isinstance(s_tc, list):
            for c in s_tc:
                if c:
                    all_target_classes.add(str(c).strip())

    total_eligible = 0
    if all_target_classes:
        is_all_classes = any(c.lower() == "all" for c in all_target_classes)
        if not is_all_classes:
            cursor.execute("SELECT COUNT(*) FROM cbt_synced_students WHERE class_name = ANY(%s)", (list(all_target_classes),))
        elif exam_dict.get("grade"):
            cursor.execute("SELECT COUNT(*) FROM cbt_synced_students WHERE grade = %s", (exam_dict.get("grade"),))
        else:
            cursor.execute("SELECT COUNT(*) FROM cbt_synced_students")
        total_eligible = cursor.fetchone()[0] or 0

    total_participants = max(total_eligible, sum(counts.values()))
    not_started = max(0, total_participants - in_progress - submitted - locked)

    # Hitung jumlah siswa terindikasi curang (sedang terkunci atau riwayat lock_count > 0)
    cursor.execute("""
        SELECT COUNT(*) FROM cbt_exam_sessions 
        WHERE exam_id = ? AND (status = 'locked' OR lock_count > 0)
    """, (exam_id,))
    susp_row = cursor.fetchone()
    suspicious_count = (susp_row[0] if susp_row else 0) or 0

    # Ambil daftar sesi master untuk pemetaan nama sesi (Sesi 1, Sesi 2, dst)
    cursor.execute("SELECT id, session_name, start_time, end_time FROM cbt_sessions ORDER BY start_time ASC")
    session_rows = [dict(r) for r in cursor.fetchall()]

    db.close()

    return {
        "success": True,
        "exam_id": exam_id,
        "title": exam_dict.get("title"),
        "exam_type": exam_dict.get("exam_type", "daily"),
        "status": exam_dict.get("status"),
        "token": token,
        "is_token_active": is_token_active,
        "token_refresh_interval": exam_dict.get("token_refresh_interval", 15),
        "token_updated_at": exam_dict.get("token_updated_at"),
        "remaining_seconds": remaining_seconds,
        "active_subject_id": exam_dict.get("active_subject_id"),
        "subjects": raw_subjects,
        "sessions": session_rows,
        "summary": {
            "total_participants": total_participants,
            "in_progress": in_progress,
            "submitted": submitted,
            "locked": locked,
            "not_started": not_started,
            "suspicious_count": suspicious_count,
        }
    }

@router.post("/{exam_id}/refresh-token")
def refresh_exam_token(exam_id: int, current_user: dict = Depends(get_current_user)):
    """Membuat token baru (misal tiap interval oleh Proktor/Admin)"""
    new_token = generate_random_token(5)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE cbt_exams SET previous_token = token, token = ?, token_updated_at = ?, is_token_active = 1 WHERE id = ?", (new_token, now_str, exam_id))
    db.commit()
    db.close()
    return {"success": True, "token": new_token, "token_updated_at": now_str}

@router.put("/{exam_id}/token-config")
def update_token_config(exam_id: int, req: TokenConfigRequest, current_user: dict = Depends(get_current_user)):
    """Mengatur interval perubahan token (menit), status aktif/nonaktif token, atau mengganti token secara kustom"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id, token FROM cbt_exams WHERE id = ?", (exam_id,))
    if not cursor.fetchone():
        db.close()
        raise HTTPException(status_code=404, detail="Paket ujian tidak ditemukan.")

    fields = []
    values = []

    if req.token_refresh_interval is not None:
        fields.append("token_refresh_interval = ?")
        values.append(req.token_refresh_interval)
        fields.append("token_updated_at = ?")
        values.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    
    if req.is_token_active is not None:
        fields.append("is_token_active = ?")
        values.append(1 if req.is_token_active else 0)

    if req.token:
        clean_token = req.token.strip().upper()
        fields.append("previous_token = token")
        fields.append("token = ?")
        values.append(clean_token)
        fields.append("token_updated_at = ?")
        values.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    if fields:
        values.append(exam_id)
        cursor.execute(f"UPDATE cbt_exams SET {', '.join(fields)} WHERE id = ?", tuple(values))
        db.commit()

    db.close()
    return {"success": True, "message": "Pengaturan token berhasil diperbarui!"}

@router.post("/{exam_id}/start-session")
def start_exam_session(exam_id: int, req: SessionActionRequest, current_user: dict = Depends(get_current_user)):
    """Memulai sesi ujian untuk jadwal mata pelajaran yang dipilih"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id, exam_type, created_by FROM cbt_exams WHERE id = ?", (exam_id,))
    exam_row = cursor.fetchone()
    if not exam_row:
        db.close()
        raise HTTPException(status_code=404, detail="Paket ujian tidak ditemukan.")

    exam_type = (exam_row["exam_type"] or "daily").lower()
    role = (current_user.get("role") or "").lower()
    is_admin = role in ("admin", "superadmin", "administrator", "staff")
    user_id = current_user.get("id")

    # Ujian SAS/Sekolah hanya boleh dimulai oleh Admin Pusat
    if exam_type == "sas" and not is_admin:
        db.close()
        raise HTTPException(
            status_code=403, 
            detail="Mulai dan selesainya Ujian Sekolah (SAS) sepenuhnya dikendalikan oleh Administrator / Panitia Ujian Pusat."
        )

    # Ulangan Harian hanya boleh dimulai oleh guru pembuatnya atau Admin
    if exam_type == "daily" and not is_admin:
        if exam_row["created_by"] and exam_row["created_by"] != user_id:
            db.close()
            raise HTTPException(
                status_code=403, 
                detail="Anda hanya dapat memulai sesi untuk Ulangan Harian yang Anda buat sendiri."
            )

    target_ids = req.subject_ids if req.subject_ids else ([req.subject_id] if req.subject_id else [])
    if not target_ids:
        cursor.execute("SELECT id FROM cbt_exam_subjects WHERE exam_id = ?", (exam_id,))
        target_ids = [r[0] for r in cursor.fetchall()]

    if not target_ids:
        cursor.execute("UPDATE cbt_exams SET status = 'active', is_token_active = 1 WHERE id = ?", (exam_id,))
        db.commit()
        db.close()
        return {
            "success": True,
            "message": "Sesi ulangan harian berhasil DIMULAI! Siswa pada kelas sasaran sekarang dapat memasukkan token dan mengerjakan soal.",
            "session_status": "active"
        }

    placeholders = ",".join("?" for _ in target_ids)
    cursor.execute(f"SELECT * FROM cbt_exam_subjects WHERE id IN ({placeholders}) AND exam_id = ?", (*target_ids, exam_id))
    subjects = [dict(r) for r in cursor.fetchall()]
    if not subjects:
        db.close()
        raise HTTPException(status_code=404, detail="Mata pelajaran jadwal tidak ditemukan.")

    subject_names = [s["subject_name"] for s in subjects]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_str = datetime.now().strftime("%Y-%m-%d")
    current_time_str = datetime.now().strftime("%H:%M")

    # Update status sesi seluruh mapel sasaran menjadi active, otomatis isi tanggal & jam mulai jika sebelumnya belum diisi
    cursor.execute(f"""
        UPDATE cbt_exam_subjects
        SET session_status = 'active', 
            session_started_at = ?,
            exam_date = CASE WHEN exam_date IS NULL OR exam_date = '' THEN ? ELSE exam_date END,
            start_time = CASE WHEN start_time IS NULL OR start_time = '' THEN ? ELSE start_time END
        WHERE id IN ({placeholders}) AND exam_id = ?
    """, (now_str, today_str, current_time_str, *target_ids, exam_id))

    # Pastikan status paket ujian adalah active dan set active_subject_id (ambil ID pertama) & is_token_active = 1
    cursor.execute("""
        UPDATE cbt_exams
        SET status = 'active', active_subject_id = ?, is_token_active = 1
        WHERE id = ?
    """, (target_ids[0], exam_id))

    db.commit()
    db.close()

    if len(subject_names) == 1:
        msg = f"Sesi ulangan/ujian '{subject_names[0]}' berhasil DIMULAI! Siswa pada kelas sasaran sekarang dapat memasukkan token dan mengerjakan soal."
    else:
        names_str = ", ".join(subject_names)
        msg = f"Sesi ujian untuk {len(subject_names)} mata pelajaran ({names_str}) berhasil DIMULAI serentak! Siswa pada kelas sasaran sekarang dapat memasukkan token dan mengerjakan soal."

    return {
        "success": True,
        "message": msg,
        "active_subject_ids": target_ids,
        "session_status": "active"
    }

@router.post("/{exam_id}/stop-session")
def stop_exam_session(exam_id: int, req: SessionActionRequest, current_user: dict = Depends(get_current_user)):
    """Menghentikan / menyelesaikan sesi ujian untuk jadwal mata pelajaran yang dipilih"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id, exam_type, created_by FROM cbt_exams WHERE id = ?", (exam_id,))
    exam_row = cursor.fetchone()
    if not exam_row:
        db.close()
        raise HTTPException(status_code=404, detail="Paket ujian tidak ditemukan.")

    exam_type = (exam_row["exam_type"] or "daily").lower()
    role = (current_user.get("role") or "").lower()
    is_admin = role in ("admin", "superadmin", "administrator", "staff")
    user_id = current_user.get("id")

    # Ujian SAS/Sekolah hanya boleh dihentikan oleh Admin Pusat
    if exam_type == "sas" and not is_admin:
        db.close()
        raise HTTPException(
            status_code=403, 
            detail="Mulai dan selesainya Ujian Sekolah (SAS) sepenuhnya dikendalikan oleh Administrator / Panitia Ujian Pusat."
        )

    # Ulangan Harian hanya boleh dihentikan oleh guru pembuatnya atau Admin
    if exam_type == "daily" and not is_admin:
        if exam_row["created_by"] and exam_row["created_by"] != user_id:
            db.close()
            raise HTTPException(
                status_code=403, 
                detail="Anda hanya dapat menghentikan sesi untuk Ulangan Harian yang Anda buat sendiri."
            )

    target_ids = req.subject_ids if req.subject_ids else ([req.subject_id] if req.subject_id else [])
    if not target_ids:
        cursor.execute("SELECT id FROM cbt_exam_subjects WHERE exam_id = ?", (exam_id,))
        target_ids = [r[0] for r in cursor.fetchall()]

    if not target_ids:
        cursor.execute("UPDATE cbt_exams SET status = 'completed', is_token_active = 0 WHERE id = ?", (exam_id,))
        db.commit()
        db.close()
        return {
            "success": True,
            "message": "Sesi ulangan harian berhasil DIHENTIKAN / DISELESAIKAN.",
            "session_status": "completed"
        }

    placeholders = ",".join("?" for _ in target_ids)
    cursor.execute(f"SELECT * FROM cbt_exam_subjects WHERE id IN ({placeholders}) AND exam_id = ?", (*target_ids, exam_id))
    subjects = [dict(r) for r in cursor.fetchall()]
    if not subjects:
        db.close()
        raise HTTPException(status_code=404, detail="Mata pelajaran jadwal tidak ditemukan.")

    subject_names = [s["subject_name"] for s in subjects]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target_status = req.action if req.action in ["completed", "idle"] else "completed"

    cursor.execute(f"""
        UPDATE cbt_exam_subjects
        SET session_status = ?, session_ended_at = ?
        WHERE id IN ({placeholders}) AND exam_id = ?
    """, (target_status, now_str, *target_ids, exam_id))

    # Cek apakah masih ada mapel yang sedang aktif pada ujian ini
    cursor.execute("SELECT id FROM cbt_exam_subjects WHERE exam_id = ? AND session_status = 'active'", (exam_id,))
    remaining_active = [r[0] for r in cursor.fetchall()]

    if not remaining_active:
        # Jika tidak ada lagi mapel aktif yang sedang berjalan, nonaktifkan token dan kosongkan active_subject_id
        # TETAP PERTAHANKAN status ujian (status = 'active'), jangan diubah ke 'completed'
        # karena paket ujian (SAS / Ulangan Harian) masih berlangsung untuk sesi/jadwal berikutnya.
        # Status 'completed' untuk seluruh paket ujian HANYA diubah jika Admin mengklik saklar finish-all!
        cursor.execute("""
            UPDATE cbt_exams
            SET is_token_active = 0, active_subject_id = NULL
            WHERE id = ?
        """, (exam_id,))
    else:
        # Jika masih ada mapel aktif lain, pastikan active_subject_id mengarah ke salah satu mapel aktif yang tersisa
        cursor.execute("""
            UPDATE cbt_exams
            SET active_subject_id = ?
            WHERE id = ?
        """, (remaining_active[0], exam_id))

    db.commit()
    db.close()

    if len(subject_names) == 1:
        msg = f"Sesi ulangan/ujian '{subject_names[0]}' berhasil dihentikan (Status: {target_status})."
    else:
        names_str = ", ".join(subject_names)
        msg = f"Sesi ujian untuk {len(subject_names)} mata pelajaran ({names_str}) berhasil dihentikan (Status: {target_status})."

    return {
        "success": True,
        "message": msg,
        "session_status": target_status
    }

@router.get("/{exam_id}/completion-check")
def check_exam_completion_readiness(exam_id: int, current_user: dict = Depends(get_current_user)):
    """
    Memeriksa kesiapan penyelesaian paket ujian sebelum Admin menutupnya secara permanen.
    Mengidentifikasi:
    1. Sesi / mata pelajaran yang belum pernah dimulai sama sekali (session_started_at IS NULL).
    2. Sesi / mata pelajaran yang saat ini masih sedang berjalan (session_status = 'active').
    3. Siswa pada rombel/kelas sasaran yang belum pernah mengerjakan soal tertentu.
    4. Siswa yang saat ini masih berstatus sedang ujian / terkunci (in_progress / locked).
    """
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id, title, exam_type, status FROM cbt_exams WHERE id = ?", (exam_id,))
    exam_row = cursor.fetchone()
    if not exam_row:
        db.close()
        raise HTTPException(status_code=404, detail="Paket ujian tidak ditemukan.")

    exam_dict = dict(exam_row)

    # 1. Ambil seluruh mata pelajaran pada paket ujian
    cursor.execute("""
        SELECT id, subject_name, exam_date, start_time, end_time, session_status, session_started_at, target_classes, grade
        FROM cbt_exam_subjects
        WHERE exam_id = ?
        ORDER BY 
            CASE WHEN exam_date IS NOT NULL AND exam_date != '' THEN 0 ELSE 1 END,
            exam_date ASC, start_time ASC, id ASC
    """, (exam_id,))
    subjects = [dict(r) for r in cursor.fetchall()]

    unstarted_sessions = []
    active_sessions = []
    unattempted_summary = []

    for s in subjects:
        s_status = (s.get("session_status") or "idle").lower()
        never_started = (s.get("session_started_at") is None)

        if never_started:
            unstarted_sessions.append({
                "id": s["id"],
                "subject_name": s["subject_name"],
                "exam_date": s.get("exam_date"),
                "session_time": f"{s.get('start_time', '')} - {s.get('end_time', '')}".strip(" -"),
                "status": "never_started"
            })
        elif s_status == "active":
            active_sessions.append({
                "id": s["id"],
                "subject_name": s["subject_name"],
                "exam_date": s.get("exam_date"),
                "session_time": f"{s.get('start_time', '')} - {s.get('end_time', '')}".strip(" -"),
                "status": "active"
            })

        # Cek siswa sasaran vs yang sudah mulai/mengerjakan
        target_cls = []
        try:
            target_cls = json.loads(s.get("target_classes") or "[]")
        except Exception:
            target_cls = []

        clean_cls = [c.strip() for c in target_cls if isinstance(c, str) and c.strip()]
        if clean_cls and "all" not in clean_cls:
            cursor.execute("SELECT id, name, class_name FROM cbt_synced_students WHERE TRIM(class_name) = ANY(?)", (clean_cls,))
        else:
            if s.get("grade"):
                cursor.execute("SELECT id, name, class_name FROM cbt_synced_students WHERE grade = ?", (s["grade"],))
            else:
                cursor.execute("SELECT id, name, class_name FROM cbt_synced_students")
        
        target_students = [dict(st) for st in cursor.fetchall()]
        total_target = len(target_students)

        # Siswa yang sudah berpartisipasi / mengerjakan soal
        cursor.execute("""
            SELECT DISTINCT student_id 
            FROM cbt_exam_sessions 
            WHERE exam_id = ? AND subject_id = ? AND (status != 'not_started' OR total_answered > 0)
        """, (exam_id, s["id"]))
        attempted_ids = set(r[0] for r in cursor.fetchall())

        unattempted_students = [st for st in target_students if st["id"] not in attempted_ids]

        if len(unattempted_students) > 0 and total_target > 0:
            unattempted_summary.append({
                "subject_id": s["id"],
                "subject_name": s["subject_name"],
                "exam_date": s.get("exam_date"),
                "total_target": total_target,
                "attempted_count": len(attempted_ids),
                "unattempted_count": len(unattempted_students),
                "unattempted_samples": [f"{st['name']} ({st['class_name']})" for st in unattempted_students[:5]]
            })

    # 3. Hitung siswa yang saat ini masih in_progress atau locked
    cursor.execute("""
        SELECT 
            COUNT(CASE WHEN status = 'in_progress' THEN 1 END) as in_progress_count,
            COUNT(CASE WHEN status = 'locked' THEN 1 END) as locked_count
        FROM cbt_exam_sessions
        WHERE exam_id = ?
    """, (exam_id,))
    counts_row = cursor.fetchone()
    in_progress_count = (counts_row["in_progress_count"] if counts_row else 0) or 0
    locked_count = (counts_row["locked_count"] if counts_row else 0) or 0

    db.close()

    has_warnings = bool(unstarted_sessions or active_sessions or unattempted_summary or in_progress_count > 0 or locked_count > 0)

    return {
        "success": True,
        "exam_id": exam_id,
        "title": exam_dict.get("title"),
        "exam_type": exam_dict.get("exam_type"),
        "status": exam_dict.get("status"),
        "has_warnings": has_warnings,
        "unstarted_sessions_count": len(unstarted_sessions),
        "unstarted_sessions": unstarted_sessions,
        "active_sessions_count": len(active_sessions),
        "active_sessions": active_sessions,
        "unattempted_subjects_count": len(unattempted_summary),
        "unattempted_summary": unattempted_summary,
        "in_progress_count": in_progress_count,
        "locked_count": locked_count
    }

def archive_and_reset_exam_proctoring_setup(cursor, exam_id: int):
    """
    Mengarsipkan penugasan pengawas ruangan, pengawas cadangan, pengawas terpilih,
    dan alokasi plotting siswa ke tabel arsip untuk exam_id ini, kemudian mereset (mengosongkan)
    tabel operasional agar role admin dan guru kembali ke status siaga (standby / reset).
    """
    # 1. Arsipkan dan Reset cbt_supervisor_assignments
    cursor.execute("""
        INSERT INTO cbt_supervisor_assignments_archive
        (original_id, exam_id, exam_date, room_name, session_name, supervisor1_name, supervisor2_name, supervisor3_name, proctor_name, notes)
        SELECT id, %s, exam_date, room_name, session_name, supervisor1_name, supervisor2_name, supervisor3_name, proctor_name, notes
        FROM cbt_supervisor_assignments
    """, (exam_id,))
    cursor.execute("DELETE FROM cbt_supervisor_assignments")

    # 2. Arsipkan dan Reset cbt_backup_supervisors
    cursor.execute("""
        INSERT INTO cbt_backup_supervisors_archive
        (original_id, exam_id, exam_date, session_name, teacher_name, order_num, notes)
        SELECT id, %s, exam_date, session_name, teacher_name, order_num, notes
        FROM cbt_backup_supervisors
    """, (exam_id,))
    cursor.execute("DELETE FROM cbt_backup_supervisors")

    # 3. Arsipkan dan Reset cbt_selected_supervisors
    cursor.execute("""
        INSERT INTO cbt_selected_supervisors_archive
        (original_id, exam_id, teacher_id, teacher_name, nip, email, assigned_at)
        SELECT id, %s, teacher_id, teacher_name, nip, email, assigned_at
        FROM cbt_selected_supervisors
    """, (exam_id,))
    cursor.execute("DELETE FROM cbt_selected_supervisors")

    # 4. Arsipkan dan Reset cbt_student_allocations
    cursor.execute("""
        INSERT INTO cbt_student_allocations_archive
        (original_id, exam_id, room_id, student_id, student_name, class_name, nisn, room_name, session_name, seat_number)
        SELECT id, %s, room_id, student_id, student_name, class_name, nisn, room_name, session_name, seat_number
        FROM cbt_student_allocations
    """, (exam_id,))
    cursor.execute("DELETE FROM cbt_student_allocations")


def restore_exam_proctoring_setup_from_archive(cursor, exam_id: int):
    """
    Memulihkan kembali penugasan pengawas dan alokasi siswa dari arsip untuk exam_id ini
    jika paket ujian diaktifkan kembali dan tabel operasional sedang kosong.
    """
    # 1. Cek apakah ada arsip pengawas ruangan
    cursor.execute("SELECT count(*) FROM cbt_supervisor_assignments")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO cbt_supervisor_assignments
            (exam_date, room_name, session_name, supervisor1_name, supervisor2_name, supervisor3_name, proctor_name, notes)
            SELECT exam_date, room_name, session_name, supervisor1_name, supervisor2_name, supervisor3_name, proctor_name, notes
            FROM cbt_supervisor_assignments_archive
            WHERE exam_id = %s
            ORDER BY id ASC
        """, (exam_id,))

    # 2. Cek apakah ada arsip cadangan
    cursor.execute("SELECT count(*) FROM cbt_backup_supervisors")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO cbt_backup_supervisors
            (exam_date, session_name, teacher_name, order_num, notes)
            SELECT exam_date, session_name, teacher_name, order_num, notes
            FROM cbt_backup_supervisors_archive
            WHERE exam_id = %s
            ORDER BY id ASC
        """, (exam_id,))

    # 3. Cek apakah ada arsip pengawas terpilih
    cursor.execute("SELECT count(*) FROM cbt_selected_supervisors")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO cbt_selected_supervisors
            (teacher_id, teacher_name, nip, email, is_active, assigned_at)
            SELECT teacher_id, teacher_name, nip, email, 1, COALESCE(assigned_at, CURRENT_TIMESTAMP)
            FROM cbt_selected_supervisors_archive
            WHERE exam_id = %s
            ORDER BY id ASC
        """, (exam_id,))

    # 4. Cek apakah ada arsip alokasi siswa
    cursor.execute("SELECT count(*) FROM cbt_student_allocations")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO cbt_student_allocations
            (room_id, student_id, student_name, class_name, nisn, room_name, session_name, seat_number)
            SELECT room_id, student_id, student_name, class_name, nisn, room_name, session_name, seat_number
            FROM cbt_student_allocations_archive
            WHERE exam_id = %s
            ORDER BY id ASC
        """, (exam_id,))


@router.post("/{exam_id}/finish-all")
def finish_all_exam_sessions(exam_id: int, current_user: dict = Depends(get_current_user)):
    """
    Menyelesaikan dan menutup seluruh pelaksanaan paket ujian (SAS / Ulangan Harian).
    - Status paket ujian diubah menjadi 'completed'
    - Seluruh sesi mapel diselesaikan (session_status = 'completed')
    - Siswa yang masih in_progress disubmit secara aman (force submit)
    - Token ujian dinonaktifkan
    - DATA NILAI, HASIL UJIAN, PRESENSI, DAN BERITA ACARA TIDAK DIHAPUS (TETAP AMAN)
    - Menu Jadwal Jaga di role Guru dan Proktoring/Status Tes di Admin akan otomatis ter-reset ke mode standby.
    - Jadwal pengawas ruang, cadangan, daftar pengawas, dan alokasi siswa otomatis diarsipkan dan di-reset.
    """
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id, title, exam_type, created_by FROM cbt_exams WHERE id = ?", (exam_id,))
    exam_row = cursor.fetchone()
    if not exam_row:
        db.close()
        raise HTTPException(status_code=404, detail="Paket ujian tidak ditemukan.")

    exam_title = exam_row["title"] or f"Ujian #{exam_id}"
    exam_type = (exam_row["exam_type"] or "daily").lower()
    role = (current_user.get("role") or "").lower()
    is_admin = role in ("admin", "superadmin", "administrator", "staff")
    user_id = current_user.get("id")

    if exam_type == "sas" and not is_admin:
        db.close()
        raise HTTPException(status_code=403, detail="Hanya Administrator / Panitia Ujian yang dapat menutup seluruh Ujian Sekolah (SAS).")

    if exam_type == "daily" and not is_admin:
        if exam_row["created_by"] and exam_row["created_by"] != user_id:
            db.close()
            raise HTTPException(status_code=403, detail="Anda hanya dapat menyelesaikan Ulangan Harian yang Anda buat sendiri.")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Update status paket ujian menjadi completed dan nonaktifkan token
    cursor.execute("""
        UPDATE cbt_exams
        SET status = 'completed', is_token_active = 0, token = '', active_subject_id = NULL
        WHERE id = ?
    """, (exam_id,))

    # 2. Selesaikan seluruh sesi mata pelajaran yang belum selesai
    cursor.execute("""
        UPDATE cbt_exam_subjects
        SET session_status = 'completed',
            session_ended_at = CASE WHEN session_ended_at IS NULL THEN ? ELSE session_ended_at END
        WHERE exam_id = ?
    """, (now_str, exam_id))

    # 3. Kumpulkan secara aman siswa yang masih berstatus in_progress atau locked
    cursor.execute("""
        UPDATE cbt_exam_sessions
        SET status = 'submitted', submitted_at = CASE WHEN submitted_at IS NULL THEN CURRENT_TIMESTAMP ELSE submitted_at END
        WHERE exam_id = ? AND status IN ('in_progress', 'locked')
    """, (exam_id,))

    # 4. Arsipkan dan Reset penugasan pengawas ruangan, cadangan, daftar pengawas, dan plotting siswa
    archive_and_reset_exam_proctoring_setup(cursor, exam_id)

    db.commit()
    db.close()

    return {
        "success": True,
        "message": f"Seluruh ujian '{exam_title}' berhasil diselesaikan dan ditutup. Jadwal pengawas, daftar pengawas, dan plotting ruangan telah ter-reset ke mode standby. Riwayat nilai dan berita acara tetap aman tersimpan.",
        "status": "completed"
    }

@router.post("/{exam_id}/reopen")
def reopen_exam(exam_id: int, current_user: dict = Depends(get_current_user)):
    """
    Membuka kembali paket ujian jika diperlukan pelaksanaan susulan atau peninjauan ulang.
    """
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id, title, exam_type, created_by FROM cbt_exams WHERE id = ?", (exam_id,))
    exam_row = cursor.fetchone()
    if not exam_row:
        db.close()
        raise HTTPException(status_code=404, detail="Paket ujian tidak ditemukan.")

    exam_title = exam_row["title"] or f"Ujian #{exam_id}"
    role = (current_user.get("role") or "").lower()
    is_admin = role in ("admin", "superadmin", "administrator", "staff")

    if not is_admin:
        db.close()
        raise HTTPException(status_code=403, detail="Hanya Administrator yang dapat membuka kembali periode ujian.")

    cursor.execute("""
        UPDATE cbt_exams
        SET status = 'active'
        WHERE id = ?
    """, (exam_id,))

    # Pulihkan kembali penugasan pengawas dan alokasi jika tabel operasional kosong
    restore_exam_proctoring_setup_from_archive(cursor, exam_id)

    db.commit()
    db.close()

    return {
        "success": True,
        "message": f"Paket ujian '{exam_title}' berhasil diaktifkan kembali. Data penugasan dan alokasi telah dipulihkan dari arsip.",
        "status": "active"
    }

# -------------------------------------------------------------
# LIVE MONITORING (DASHBOARD GURU & PENGAWAS)
# -------------------------------------------------------------
@router.get("/{exam_id}/monitoring")
def get_exam_monitoring(exam_id: int, room_name: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """
    Live data peserta ujian: siapa yang sedang mengerjakan,
    siapa yang terkunci (melanggar tab), siapa yang selesai, dan sisa waktu.
    """
    db = get_db()
    cursor = db.cursor()

    # Info ringkasan ujian
    cursor.execute("SELECT * FROM cbt_exams WHERE id = ?", (exam_id,))
    exam_row = cursor.fetchone()
    if not exam_row:
        db.close()
        raise HTTPException(status_code=404, detail="Ujian tidak ditemukan.")

    exam_dict = dict(exam_row)

    # Token otomatis & countdown monitoring
    is_completed_exam = (exam_dict.get("status") == "completed")
    if is_completed_exam:
        token = "-"
        remaining_seconds = 0
        is_token_active = False
    else:
        token, remaining_seconds, refreshed = get_or_refresh_token(cursor, exam_dict)
        if refreshed:
            db.commit()
        is_token_active = bool(exam_dict.get("is_token_active", 1))

    exam_dict["token"] = token
    exam_dict["remaining_seconds"] = remaining_seconds
    exam_dict["is_token_active"] = is_token_active
    exam_dict["token_refresh_interval"] = exam_dict.get("token_refresh_interval") if exam_dict.get("token_refresh_interval") is not None else 15
    exam_dict["token_updated_at"] = exam_dict.get("token_updated_at")

    cursor.execute("""
        SELECT s.*,
               COALESCE(s.randomize_questions, b.randomize_questions, 1) as randomize_questions,
               COALESCE(s.randomize_options, b.randomize_options, 1) as randomize_options,
               COALESCE(s.show_score, b.show_score, 1) as show_score,
               COALESCE(s.show_explanation, b.show_explanation, 0) as show_explanation,
               COALESCE(s.duration_minutes, b.duration_minutes, 90) as duration_minutes,
               COALESCE(s.passing_score, b.passing_score, 75.0) as passing_score,
               COALESCE(b.max_violations, 3) as max_violations,
               b.title as bank_title, b.total_questions as actual_questions
        FROM cbt_exam_subjects s
        LEFT JOIN cbt_question_banks b ON s.bank_id = b.id
        WHERE s.exam_id = ?
        ORDER BY s.id ASC
    """, (exam_id,))
    raw_subjects = [dict(r) for r in cursor.fetchall()]
    for s_row in raw_subjects:
        try:
            s_row["target_classes"] = json.loads(s_row.get("target_classes") or "[]")
        except Exception:
            s_row["target_classes"] = []
    exam_dict["subjects"] = raw_subjects

    is_session_active = False
    if raw_subjects:
        is_session_active = any(s.get("session_status") == "active" or s.get("id") == exam_dict.get("active_subject_id") for s in raw_subjects)
    else:
        is_session_active = (exam_dict.get("status") == "active")
    exam_dict["is_session_active"] = is_session_active

    query = """
        SELECT s.*,
               (SELECT COUNT(*) FROM cbt_violations v WHERE v.session_id = s.id) as violation_count,
               (SELECT v.violation_type FROM cbt_violations v WHERE v.session_id = s.id ORDER BY v.id DESC LIMIT 1) as last_violation_type,
               (SELECT v.occurred_at FROM cbt_violations v WHERE v.session_id = s.id ORDER BY v.id DESC LIMIT 1) as last_violation_time
        FROM cbt_exam_sessions s
        WHERE s.exam_id = ?
    """
    params = [exam_id]

    if room_name and room_name != "all":
        query += " AND s.room_name = ?"
        params.append(room_name)

    query += " ORDER BY s.class_name, s.student_name ASC"
    cursor.execute(query, tuple(params))
    
    raw_sessions = [dict(row) for row in cursor.fetchall()]

    # Kumpulkan seluruh target classes dari konfigurasi paket ujian & jadwal mapel
    all_target_classes = set()
    e_tc = exam_dict.get("target_classes")
    if isinstance(e_tc, str):
        try:
            e_tc = json.loads(e_tc)
        except Exception:
            e_tc = [e_tc] if e_tc else []
    if isinstance(e_tc, list):
        for c in e_tc:
            if c:
                all_target_classes.add(str(c).strip())

    for s_row in raw_subjects:
        s_tc = s_row.get("target_classes")
        if isinstance(s_tc, str):
            try:
                s_tc = json.loads(s_tc)
            except Exception:
                s_tc = [s_tc] if s_tc else []
        if isinstance(s_tc, list):
            for c in s_tc:
                if c:
                    all_target_classes.add(str(c).strip())

    # Ambil siswa dari kelas sasaran yang belum memulai ujian (status: not_started)
    existing_student_ids = {s.get("student_id") for s in raw_sessions if s.get("student_id")}

    if all_target_classes:
        is_all_classes = any(c.lower() == "all" for c in all_target_classes)
        student_query = """
            SELECT s.id as student_id, s.name as student_name, s.class_name, s.nisn, s.grade,
                   a.room_name, a.session_name, a.seat_number
            FROM cbt_synced_students s
            LEFT JOIN cbt_student_allocations a ON s.id = a.student_id
            WHERE 1=1
        """
        student_params = []
        if not is_all_classes:
            student_query += " AND s.class_name = ANY(%s)"
            student_params.append(list(all_target_classes))
        elif exam_dict.get("grade"):
            student_query += " AND s.grade = %s"
            student_params.append(exam_dict.get("grade"))

        if room_name and room_name != "all":
            student_query += " AND a.room_name = %s"
            student_params.append(room_name)

        student_query += " ORDER BY s.class_name ASC, s.name ASC"
        cursor.execute(student_query, tuple(student_params))
        eligible_students = [dict(r) for r in cursor.fetchall()]

        active_subj_id = exam_dict.get("active_subject_id") or (raw_subjects[0]["id"] if raw_subjects else None)

        for st in eligible_students:
            if st["student_id"] not in existing_student_ids:
                raw_sessions.append({
                    "id": None,
                    "exam_id": exam_id,
                    "subject_id": active_subj_id,
                    "student_id": st["student_id"],
                    "student_name": st["student_name"],
                    "class_name": st["class_name"],
                    "nisn": st.get("nisn"),
                    "seat_number": st.get("seat_number"),
                    "room_name": st.get("room_name"),
                    "session_name": st.get("session_name"),
                    "status": "not_started",
                    "remaining_seconds": 0,
                    "total_answered": 0,
                    "score": None,
                    "lock_reason": None,
                    "lock_count": 0,
                    "unlock_code": None,
                    "violation_count": 0,
                    "last_violation_type": None,
                    "last_violation_time": None,
                    "is_suspicious": False,
                    "device_id": None,
                    "device_info": None,
                    "browser_info": None,
                    "ip_address": None,
                    "ping_ms": None,
                    "connection_quality": None,
                })

    raw_sessions.sort(key=lambda x: (x.get("class_name") or "", x.get("student_name") or ""))

    sessions = []
    suspicious_count = 0
    in_progress_count = 0
    locked_count = 0
    submitted_count = 0
    not_started_count = 0

    for s in raw_sessions:
        ex_status = s.get("status") or "not_started"
        lock_cnt = s.get("lock_count") or 0
        v_cnt = s.get("violation_count") or 0

        # Cek indikasi kecurangan
        is_suspicious = bool((ex_status == "locked") or (lock_cnt > 0) or (v_cnt > 0))
        s["is_suspicious"] = is_suspicious
        if is_suspicious:
            suspicious_count += 1

        # Perangkat & Browser default (Hanya jika siswa sudah mulai ujian)
        if ex_status != "not_started":
            s["device_info"] = s.get("device_info") or (s.get("device_id") and "Laptop/PC (Windows)") or None
            s["browser_info"] = s.get("browser_info") or None
            s["ip_address"] = s.get("ip_address") or None

            # Ping & Koneksi
            ping_val = s.get("ping_ms") if s.get("ping_ms") is not None else 25
            s["ping_ms"] = ping_val

            # Cek detak jantung (heartbeat) terputus
            last_hb = s.get("last_heartbeat")
            is_offline = False
            if ex_status == "in_progress" and last_hb:
                try:
                    diff = (datetime.now() - last_hb).total_seconds()
                    if diff > 45:
                        is_offline = True
                except Exception:
                    pass

            if is_offline:
                s["connection_quality"] = "offline"
            else:
                s["connection_quality"] = s.get("connection_quality") or ("stabil" if ping_val < 60 else "sedang" if ping_val < 180 else "lemah")
        else:
            s["device_info"] = None
            s["browser_info"] = None
            s["ip_address"] = None
            s["ping_ms"] = None
            s["connection_quality"] = None

        # Kode buka kunci jika terkunci
        if ex_status == "locked":
            cur_code = s.get("unlock_code")
            if not cur_code:
                cur_code = str(random.randint(100000, 999999))
                cursor.execute("UPDATE cbt_exam_sessions SET unlock_code = %s WHERE id = %s", (cur_code, s["id"]))
                db.commit()
            s["unlock_code"] = cur_code
        else:
            s["unlock_code"] = None

        if ex_status == "in_progress":
            in_progress_count += 1
        elif ex_status == "locked":
            locked_count += 1
        elif ex_status == "submitted":
            submitted_count += 1
        else:
            not_started_count += 1

        sessions.append(s)

    summary = {
        "total_participants": len(sessions),
        "in_progress": in_progress_count,
        "locked": locked_count,
        "submitted": submitted_count,
        "not_started": not_started_count,
        "suspicious_count": suspicious_count,
    }

    db.close()
    return {
        "success": True,
        "exam": exam_dict,
        "summary": summary,
        "participants": sessions
    }

@router.post("/{exam_id}/unlock-student")
def unlock_student(exam_id: int, req: UnlockStudentRequest, current_user: dict = Depends(get_current_user)):
    """
    Tombol 'BUKA KUNCI' yang ditekan oleh Guru / Pengawas Ruangan
    setelah siswa ditegur karena membuka tab atau aplikasi lain.
    Mendukung buka kunci tunggal maupun massal (session_ids).
    """
    ids_to_unlock = []
    if req.session_ids:
        ids_to_unlock.extend(req.session_ids)
    if req.session_id and req.session_id not in ids_to_unlock:
        ids_to_unlock.append(req.session_id)

    if not ids_to_unlock:
        return {"success": True, "message": "Tidak ada siswa yang dipilih.", "unlocked": 0}

    db = get_db()
    cursor = db.cursor()

    placeholders = ",".join("%s" for _ in ids_to_unlock)
    cursor.execute(f"""
        UPDATE cbt_exam_sessions
        SET status = 'in_progress', lock_reason = NULL, unlock_code = NULL
        WHERE id IN ({placeholders}) AND exam_id = %s
    """, (*ids_to_unlock, exam_id))

    unlocked_count = cursor.rowcount
    db.commit()
    db.close()

    return {
        "success": True,
        "message": f"Kunci ujian {unlocked_count} siswa berhasil dibuka. Siswa dapat melanjutkan pengerjaan soal.",
        "unlocked": unlocked_count
    }

@router.post("/{exam_id}/reset-device")
def reset_student_device(exam_id: int, req: ResetDeviceRequest, current_user: dict = Depends(get_current_user)):
    """
    Tombol 'RESET DEVICE' jika HP siswa mati atau error,
    sehingga siswa bisa login di perangkat lain tanpa kehilangan jawaban.
    """
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        UPDATE cbt_exam_sessions
        SET device_id = NULL, ip_address = NULL, lock_reason = NULL, unlock_code = NULL,
            status = CASE WHEN status = 'locked' THEN 'in_progress' ELSE status END
        WHERE id = %s AND exam_id = %s
    """, (req.session_id, exam_id))

    db.commit()
    db.close()

    return {
        "success": True,
        "message": "Sesi perangkat siswa berhasil direset. Siswa dapat login kembali dari perangkat baru."
    }

@router.post("/{exam_id}/submit-student")
def force_submit_student(exam_id: int, req: ForceSubmitStudentRequest, current_user: dict = Depends(get_current_user)):
    """
    Tombol 'SELESAIKAN UJIAN' secara paksa (force submit) oleh Guru jika waktu habis atau siswa meninggalkan ruangan.
    """
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        UPDATE cbt_exam_sessions
        SET status = 'submitted', submitted_at = CURRENT_TIMESTAMP
        WHERE id = %s AND exam_id = %s
    """, (req.session_id, exam_id))

    affected = cursor.rowcount
    db.commit()
    db.close()

    if affected == 0:
        raise HTTPException(status_code=404, detail="Sesi ujian siswa tidak ditemukan.")

    return {
        "success": True,
        "message": "Ujian siswa berhasil dikumpulkan secara paksa."
    }


