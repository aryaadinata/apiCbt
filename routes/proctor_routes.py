from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from database import get_db
from auth import get_current_user

router = APIRouter(prefix="/api/cbt/proctor", tags=["Proctor"])

class BatchUnlockRequest(BaseModel):
    session_ids: List[int]

class FinalizeRoomRequest(BaseModel):
    notes: Optional[str] = "Ujian berjalan tertib"

@router.get("/rooms/{exam_id}")
def get_rooms_summary(exam_id: int, current_user: dict = Depends(get_current_user)):
    """
    Daftar seluruh ruangan ujian SAS beserta status agregatnya:
    Total siswa, yang sedang mengerjakan, terkunci, dan selesai.
    """
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        SELECT s.room_name,
               COUNT(*) as total_students,
               SUM(CASE WHEN s.status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
               SUM(CASE WHEN s.status = 'locked' THEN 1 ELSE 0 END) as locked,
               SUM(CASE WHEN s.status = 'submitted' THEN 1 ELSE 0 END) as submitted,
               SUM(CASE WHEN s.status = 'not_started' THEN 1 ELSE 0 END) as not_started
        FROM cbt_exam_sessions s
        WHERE s.exam_id = ?
        GROUP BY s.room_name
        ORDER BY s.room_name ASC
    """, (exam_id,))

    rooms = [dict(row) for row in cursor.fetchall()]
    db.close()
    return {"success": True, "rooms": rooms}

@router.post("/batch-unlock")
def batch_unlock(req: BatchUnlockRequest, current_user: dict = Depends(get_current_user)):
    """Buka kunci beberapa siswa sekaligus"""
    if not req.session_ids:
        return {"success": True, "unlocked": 0}

    db = get_db()
    cursor = db.cursor()
    placeholders = ",".join("?" for _ in req.session_ids)
    cursor.execute(f"""
        UPDATE cbt_exam_sessions
        SET status = 'in_progress', lock_reason = NULL
        WHERE id IN ({placeholders}) AND status = 'locked'
    """, req.session_ids)

    affected = cursor.rowcount
    db.commit()
    db.close()

    return {"success": True, "message": f"Berhasil membuka kunci {affected} siswa.", "unlocked": affected}

@router.get("/export-results/{exam_id}")
def export_results(exam_id: int, current_user: dict = Depends(get_current_user)):
    """
    Rekapitulasi nilai seluruh peserta ujian untuk persiapan kirim ke SIAK.
    """
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        SELECT e.title, e.subject_name, e.grade, s.student_id, s.student_name,
               s.class_name, s.nisn, s.room_name, s.score, s.total_correct,
               s.total_answered, s.submitted_at
        FROM cbt_exam_sessions s
        JOIN cbt_exams e ON s.exam_id = e.id
        WHERE s.exam_id = ? AND s.status = 'submitted'
        ORDER BY s.class_name, s.student_name ASC
    """, (exam_id,))

    results = [dict(row) for row in cursor.fetchall()]
    db.close()

    return {
        "success": True,
        "total": len(results),
        "results": results
    }

@router.get("/locked-students")
def get_all_locked_students(current_user: dict = Depends(get_current_user)):
    """
    Daftar seluruh siswa yang saat ini terkunci di semua ujian (SAS & Ulangan).
    Memungkinkan Panitia/Admin membuka kunci darurat dari satu dashboard terpusat.
    """
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        SELECT s.id as session_id, s.student_id, s.student_name, s.class_name,
               s.nisn, s.room_name, s.lock_reason, s.lock_count as violation_count, s.start_time as started_at,
               e.id as exam_id, e.title as exam_title, e.subject_name, e.exam_type
        FROM cbt_exam_sessions s
        JOIN cbt_exams e ON s.exam_id = e.id
        WHERE s.status = 'locked'
        ORDER BY s.id DESC
    """)
    locked = [dict(row) for row in cursor.fetchall()]
    db.close()

    return {"success": True, "total": len(locked), "locked_students": locked}

@router.post("/unlock-all")
def unlock_all_students(current_user: dict = Depends(get_current_user)):
    """Membuka kunci seluruh siswa yang sedang terkunci di seluruh ujian."""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        UPDATE cbt_exam_sessions
        SET status = 'in_progress', lock_reason = NULL
        WHERE status = 'locked'
    """)
    affected = cursor.rowcount
    db.commit()
    db.close()

    return {
        "success": True,
        "message": f"Berhasil membuka kunci seluruh {affected} siswa yang terkunci.",
        "unlocked": affected
    }

@router.get("/system-overview")
def get_system_overview(current_user: dict = Depends(get_current_user)):
    """
    Ringkasan metrik lengkap untuk Dashboard Panitia / Admin CBT.
    """
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT COUNT(*) FROM cbt_synced_students")
    total_students = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM cbt_synced_teachers")
    total_teachers = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM cbt_synced_classes")
    total_classes = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM cbt_exams WHERE exam_type = 'sas'")
    total_sas_exams = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM cbt_exams WHERE exam_type = 'daily'")
    total_daily_exams = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM cbt_question_banks")
    total_banks = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM cbt_exam_sessions WHERE status = 'in_progress'")
    active_in_progress = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM cbt_exam_sessions WHERE status = 'locked'")
    active_locked = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM cbt_exam_sessions WHERE status = 'submitted'")
    total_submitted = cursor.fetchone()[0]

    cursor.execute("SELECT synced_at FROM cbt_synced_students ORDER BY synced_at DESC LIMIT 1")
    last_row = cursor.fetchone()
    last_synced = last_row[0] if last_row else None

    db.close()

    return {
        "success": True,
        "stats": {
            "total_students": total_students,
            "total_teachers": total_teachers,
            "total_classes": total_classes,
            "total_sas_exams": total_sas_exams,
            "total_daily_exams": total_daily_exams,
            "total_banks": total_banks,
            "active_in_progress": active_in_progress,
            "active_locked": active_locked,
            "total_submitted": total_submitted,
            "last_synced": last_synced,
            "server_status": "online",
            "db_mode": "PostgreSQL (db_cbt)"
        }
    }
