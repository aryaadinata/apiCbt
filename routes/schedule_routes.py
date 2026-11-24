import random
import re
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from database import get_db
from auth import get_current_user

def clean_academic_titles(name: str) -> str:
    if not name:
        return ""
    prefixes = [r'^\s*dr\.\s*', r'^\s*drs\.\s*', r'^\s*dra\.\s*', r'^\s*prof\.\s*', r'^\s*ir\.\s*', r'^\s*h\.\s*', r'^\s*hj\.\s*']
    res = name.strip()
    for p in prefixes:
        res = re.sub(p, '', res, flags=re.IGNORECASE)
    res = re.sub(r',.*$', '', res)
    res = re.sub(r'\s+s\.pd\b.*$', '', res, flags=re.IGNORECASE)
    res = re.sub(r'\s+m\.pd\b.*$', '', res, flags=re.IGNORECASE)
    res = re.sub(r'\s+s\.sn\b.*$', '', res, flags=re.IGNORECASE)
    res = re.sub(r'\s+s\.si\b.*$', '', res, flags=re.IGNORECASE)
    res = re.sub(r'\s+m\.kom\b.*$', '', res, flags=re.IGNORECASE)
    res = re.sub(r'\s+s\.kom\b.*$', '', res, flags=re.IGNORECASE)
    res = re.sub(r'\s+s\.e\b.*$', '', res, flags=re.IGNORECASE)
    res = re.sub(r'\s+m\.m\b.*$', '', res, flags=re.IGNORECASE)
    res = re.sub(r'\s+s\.t\b.*$', '', res, flags=re.IGNORECASE)
    res = re.sub(r'\s+m\.t\b.*$', '', res, flags=re.IGNORECASE)
    return res.strip(' ,.')

def is_name_match(query_name: str, candidate_name: str) -> bool:
    if not query_name or not candidate_name:
        return False
    q = query_name.strip().lower()
    cand = candidate_name.strip().lower()
    return q == cand or q in cand or cand in q

def get_teacher_matched_names(current_user: dict, cursor) -> list[str]:
    names = set()
    raw_name = (current_user.get("name") or "").strip()
    if raw_name:
        names.add(raw_name)
        c_name = clean_academic_titles(raw_name)
        if c_name:
            names.add(c_name)
    nip = (current_user.get("nip") or "").strip()
    username = (current_user.get("username") or "").strip()
    teacher_id = current_user.get("teacher_id") or current_user.get("id")
    try:
        cursor.execute("""
            SELECT id, name, nip, email FROM cbt_synced_teachers 
            WHERE (nip IS NOT NULL AND nip != '' AND (nip = %s OR nip = %s)) 
               OR (CAST(id AS TEXT) = %s) 
               OR LOWER(TRIM(name)) = LOWER(TRIM(%s)) 
               OR LOWER(TRIM(%s)) LIKE CONCAT('%%', LOWER(TRIM(name)), '%%') 
               OR LOWER(TRIM(name)) LIKE CONCAT('%%', LOWER(TRIM(%s)), '%%') 
            ORDER BY CASE WHEN nip = %s THEN 1 WHEN LOWER(TRIM(name)) = LOWER(TRIM(%s)) THEN 2 ELSE 3 END 
            LIMIT 1
        """, (nip, username, str(teacher_id) if teacher_id else '-1', raw_name, raw_name, raw_name, nip, raw_name))
        row_t = cursor.fetchone()
        if row_t:
            t_name = (row_t["name"] if isinstance(row_t, dict) else row_t[1] or "").strip()
            if t_name:
                names.add(t_name)
                c2 = clean_academic_titles(t_name)
                if c2:
                    names.add(c2)
    except Exception as e_match:
        print("[MATCH] Error resolving synced teacher:", e_match)

    return [n for n in names if len(n) >= 2]

router = APIRouter(prefix="/api/cbt/schedule", tags=["Schedule & Allocation"])

class RoomRequest(BaseModel):
    name: str
    capacity: int = 36
    location: Optional[str] = None

class UpdateRoomRequest(BaseModel):
    name: str
    capacity: int = 36
    location: Optional[str] = None

class AllocateStudentsRequest(BaseModel):
    student_ids: List[int]
    session_name: Optional[str] = "Sesi 1"

class AllocateClassRequest(BaseModel):
    class_name: str
    session_name: Optional[str] = "Sesi 1"
    only_unallocated: bool = True

class SessionRequest(BaseModel):
    session_name: str
    start_time: str # "07:30"
    end_time: str   # "09:30"

class SupervisorAssignmentRequest(BaseModel):
    id: Optional[int] = None
    exam_date: str
    room_name: str
    session_name: str
    supervisor1_name: Optional[str] = None
    supervisor2_name: Optional[str] = None
    supervisor3_name: Optional[str] = None
    proctor_name: Optional[str] = None
    notes: Optional[str] = None

class BackupSupervisorRequest(BaseModel):
    id: Optional[int] = None
    exam_date: str
    session_name: str
    teacher_name: str
    order_num: int = 1
    notes: Optional[str] = None

class AutoAssignSupervisorsRequest(BaseModel):
    exam_dates: Optional[List[str]] = None
    supervisors_per_room: int = 2 # 1, 2, or 3
    backup_count_per_session: int = 1 # 0, 1, 2, or 3
    assign_proctors: bool = True
    selected_teachers: Optional[List[str]] = None
    proctors_pool: Optional[List[str]] = None
    replace_existing: bool = True

class SasMatrixRequest(BaseModel):
    exam_date: str
    day_name: str
    period_number: int = 1
    subject_name: str
    grade: int = 10
    bank_id: Optional[int] = None
    duration_minutes: int = 90
    start_time: str = "07:30"
    end_time: str = "09:00"

class ToggleSupervisorRequest(BaseModel):
    teacher_id: int
    is_supervisor: bool

class BatchSupervisorsRequest(BaseModel):
    teacher_ids: Optional[List[int]] = None
    action: str = "set_selected" # "set_selected" | "set_all" | "clear_all"

@router.get("/overview")
def get_schedule_overview(current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT COUNT(*) FROM cbt_rooms")
    total_rooms = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM cbt_sessions")
    total_sessions = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM cbt_synced_students")
    total_students = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM cbt_student_allocations")
    total_allocated = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM cbt_supervisor_assignments")
    total_assignments = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM cbt_sas_schedules")
    total_matrix = cursor.fetchone()[0]

    db.close()

    return {
        "success": True,
        "total_rooms": total_rooms,
        "total_sessions": total_sessions,
        "total_students": total_students,
        "total_allocated": total_allocated,
        "total_unallocated": max(0, total_students - total_allocated),
        "total_assignments": total_assignments,
        "total_matrix": total_matrix
    }

# -------------------------------------------------------------
# 1. MASTER RUANGAN & ALOKASI SISWA PER RUANGAN
# -------------------------------------------------------------
@router.get("/rooms")
def list_rooms(current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT r.*,
               COUNT(a.id) as allocated_count,
               STRING_AGG(DISTINCT a.class_name, ',') as allocated_classes_str
        FROM cbt_rooms r
        LEFT JOIN cbt_student_allocations a ON (a.room_id = r.id OR a.room_name = r.name)
        GROUP BY r.id
        ORDER BY r.name ASC
    """)
    rooms = []
    for row in cursor.fetchall():
        item = dict(row)
        classes_str = item.pop("allocated_classes_str", None)
        item["allocated_classes"] = [c.strip() for c in classes_str.split(",") if c.strip()] if classes_str else []
        item["remaining_seats"] = max(0, item["capacity"] - item["allocated_count"])
        item["is_full"] = item["allocated_count"] >= item["capacity"]
        rooms.append(item)
    db.close()
    return {"success": True, "rooms": rooms}

@router.post("/rooms")
def create_room(req: RoomRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("INSERT INTO cbt_rooms (name, capacity, location) VALUES (%s, %s, %s) RETURNING id",
                       (req.name.strip(), req.capacity, req.location))
        room_id = cursor.fetchone()[0]
        db.commit()
        db.close()
        return {"success": True, "message": f"Ruangan '{req.name}' berhasil ditambahkan.", "room_id": room_id}
    except Exception as e:
        db.close()
        raise HTTPException(status_code=400, detail=f"Gagal menambahkan ruangan: {str(e)}")

@router.put("/rooms/{room_id}")
def update_room(room_id: int, req: UpdateRoomRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM cbt_rooms WHERE id = ?", (room_id,))
    old_room = cursor.fetchone()
    if not old_room:
        db.close()
        raise HTTPException(status_code=404, detail="Ruangan tidak ditemukan.")
    
    old_name = old_room["name"]
    new_name = req.name.strip()

    cursor.execute("""
        UPDATE cbt_rooms
        SET name = ?, capacity = ?, location = ?
        WHERE id = ?
    """, (new_name, req.capacity, req.location, room_id))

    # Sinkronkan room_name di tabel alokasi siswa jika nama berubah
    if old_name != new_name:
        cursor.execute("""
            UPDATE cbt_student_allocations
            SET room_name = ?
            WHERE room_id = ? OR room_name = ?
        """, (new_name, room_id, old_name))

    db.commit()
    db.close()
    return {"success": True, "message": f"Ruangan '{new_name}' berhasil diperbarui!"}

@router.delete("/rooms/{room_id}")
def delete_room(room_id: int, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT name FROM cbt_rooms WHERE id = ?", (room_id,))
    row = cursor.fetchone()
    if not row:
        db.close()
        raise HTTPException(status_code=404, detail="Ruangan tidak ditemukan.")
    
    room_name = row[0]
    # Hapus alokasi siswa di ruangan ini
    cursor.execute("DELETE FROM cbt_student_allocations WHERE room_id = ? OR room_name = ?", (room_id, room_name))
    cursor.execute("DELETE FROM cbt_rooms WHERE id = ?", (room_id,))
    db.commit()
    db.close()
    return {"success": True, "message": f"Ruangan '{room_name}' dan data alokasi siswanya berhasil dihapus."}

@router.get("/rooms/{room_id}/students")
def get_room_students(room_id: int, current_user: dict = Depends(get_current_user)):
    """Mengambil daftar siswa yang dialokasikan di ruangan tertentu"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM cbt_rooms WHERE id = ?", (room_id,))
    room = cursor.fetchone()
    if not room:
        db.close()
        raise HTTPException(status_code=404, detail="Ruangan tidak ditemukan.")
    
    room_dict = dict(room)
    cursor.execute("""
        SELECT a.*, s.nis, s.gender, s.photo, s.nik, s.exam_password
        FROM cbt_student_allocations a
        LEFT JOIN cbt_synced_students s ON a.student_id = s.id
        WHERE a.room_id = ? OR a.room_name = ?
        ORDER BY a.seat_number ASC, a.student_name ASC
    """, (room_id, room_dict["name"]))
    
    students = [dict(r) for r in cursor.fetchall()]
    db.close()

    return {
        "success": True,
        "room": room_dict,
        "total_students": len(students),
        "capacity": room_dict["capacity"],
        "remaining_seats": max(0, room_dict["capacity"] - len(students)),
        "students": students
    }

@router.post("/rooms/{room_id}/allocate-students")
def allocate_students_to_room(room_id: int, req: AllocateStudentsRequest, current_user: dict = Depends(get_current_user)):
    """Menambahkan beberapa siswa pilihan secara spesifik ke ruangan ini"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM cbt_rooms WHERE id = ?", (room_id,))
    room = cursor.fetchone()
    if not room:
        db.close()
        raise HTTPException(status_code=404, detail="Ruangan tidak ditemukan.")
    
    room_dict = dict(room)
    capacity = room_dict["capacity"]

    # Ambil nomor kursi yang sudah terpakai
    cursor.execute("SELECT seat_number, student_id FROM cbt_student_allocations WHERE room_id = ? OR room_name = ?", (room_id, room_dict["name"]))
    existing = cursor.fetchall()
    existing_student_ids = {r[1] for r in existing}
    used_seats = {r[0] for r in existing if r[0]}

    available_seats = [s for s in range(1, capacity + 1) if s not in used_seats]
    if not available_seats:
        db.close()
        raise HTTPException(status_code=400, detail=f"Ruangan '{room_dict['name']}' sudah penuh (Kapasitas: {capacity} siswa).")

    added = 0
    session_name = req.session_name or "Sesi 1"

    for sid in req.student_ids:
        if sid in existing_student_ids:
            continue
        if not available_seats:
            break
        
        cursor.execute("SELECT id, name, class_name, nisn FROM cbt_synced_students WHERE id = ?", (sid,))
        stu = cursor.fetchone()
        if not stu:
            continue
        
        next_seat = available_seats.pop(0)
        # Hapus jika siswa sebelumnya ada di ruangan lain
        cursor.execute("DELETE FROM cbt_student_allocations WHERE student_id = ?", (sid,))
        
        cursor.execute("""
            INSERT INTO cbt_student_allocations 
            (room_id, room_name, student_id, student_name, class_name, nisn, session_name, seat_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (room_id, room_dict["name"], stu[0], stu[1], stu[2], stu[3], session_name, next_seat))
        added += 1

    db.commit()
    db.close()

    return {
        "success": True,
        "message": f"Berhasil menambahkan {added} siswa ke ruangan '{room_dict['name']}'!",
        "added_count": added
    }

@router.post("/rooms/{room_id}/allocate-class")
def allocate_class_to_room(room_id: int, req: AllocateClassRequest, current_user: dict = Depends(get_current_user)):
    """Memasukkan seluruh siswa dari satu kelas tertentu ke ruangan ini (hingga kapasitas penuh)"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM cbt_rooms WHERE id = ?", (room_id,))
    room = cursor.fetchone()
    if not room:
        db.close()
        raise HTTPException(status_code=404, detail="Ruangan tidak ditemukan.")
    
    room_dict = dict(room)
    capacity = room_dict["capacity"]

    cursor.execute("SELECT seat_number FROM cbt_student_allocations WHERE room_id = ? OR room_name = ?", (room_id, room_dict["name"]))
    used_seats = {r[0] for r in cursor.fetchall() if r[0]}
    available_seats = [s for s in range(1, capacity + 1) if s not in used_seats]

    if not available_seats:
        db.close()
        raise HTTPException(status_code=400, detail=f"Ruangan '{room_dict['name']}' sudah penuh.")

    if req.only_unallocated:
        cursor.execute("""
            SELECT s.id, s.name, s.class_name, s.nisn
            FROM cbt_synced_students s
            LEFT JOIN cbt_student_allocations a ON s.id = a.student_id
            WHERE TRIM(s.class_name) = TRIM(?) AND a.id IS NULL
            ORDER BY s.name ASC
        """, (req.class_name,))
    else:
        cursor.execute("""
            SELECT s.id, s.name, s.class_name, s.nisn
            FROM cbt_synced_students s
            WHERE TRIM(s.class_name) = TRIM(?)
            ORDER BY s.name ASC
        """, (req.class_name,))
    
    class_students = cursor.fetchall()
    if not class_students:
        db.close()
        raise HTTPException(status_code=400, detail=f"Tidak ada siswa yang tersedia di kelas '{req.class_name}'.")

    added = 0
    session_name = req.session_name or "Sesi 1"

    for stu in class_students:
        if not available_seats:
            break
        next_seat = available_seats.pop(0)
        cursor.execute("DELETE FROM cbt_student_allocations WHERE student_id = ?", (stu[0],))
        cursor.execute("""
            INSERT INTO cbt_student_allocations 
            (room_id, room_name, student_id, student_name, class_name, nisn, session_name, seat_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (room_id, room_dict["name"], stu[0], stu[1], stu[2], stu[3], session_name, next_seat))
        added += 1

    db.commit()
    db.close()

    return {
        "success": True,
        "message": f"Berhasil memasukkan {added} siswa kelas '{req.class_name}' ke ruangan '{room_dict['name']}'!",
        "added_count": added
    }

@router.delete("/rooms/{room_id}/students/{allocation_id}")
def remove_student_from_room(room_id: int, allocation_id: int, current_user: dict = Depends(get_current_user)):
    """Mengeluarkan satu siswa dari ruangan ujian"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM cbt_student_allocations WHERE id = ? AND (room_id = ? OR room_name = (SELECT name FROM cbt_rooms WHERE id = ?))", (allocation_id, room_id, room_id))
    db.commit()
    db.close()
    return {"success": True, "message": "Siswa berhasil dikeluarkan dari ruangan."}

@router.delete("/rooms/{room_id}/clear-students")
def clear_room_students(room_id: int, current_user: dict = Depends(get_current_user)):
    """Mengosongkan seluruh siswa dari ruangan ujian terpilih"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM cbt_student_allocations WHERE room_id = ? OR room_name = (SELECT name FROM cbt_rooms WHERE id = ?)", (room_id, room_id))
    db.commit()
    db.close()
    return {"success": True, "message": "Seluruh alokasi siswa pada ruangan ini berhasil dikosongkan."}

@router.get("/available-students")
def get_available_students(
    class_name: Optional[str] = None,
    unallocated_only: bool = False,
    current_user: dict = Depends(get_current_user)
):
    """Mengambil daftar siswa beserta informasi alokasi ruangannya untuk kebutuhan plotting"""
    db = get_db()
    cursor = db.cursor()

    query = """
        SELECT s.id, s.name, s.class_name, s.nisn, s.nis, s.gender,
               a.id as allocation_id, a.room_id, a.room_name, a.seat_number, a.session_name
        FROM cbt_synced_students s
        LEFT JOIN cbt_student_allocations a ON s.id = a.student_id
        WHERE 1=1
    """
    params = []

    if class_name and class_name != "all":
        query += " AND TRIM(s.class_name) = TRIM(?)"
        params.append(class_name)

    if unallocated_only:
        query += " AND a.id IS NULL"

    query += " ORDER BY s.class_name ASC, s.name ASC"
    cursor.execute(query, tuple(params))
    students = [dict(r) for r in cursor.fetchall()]

    # Ambil juga ringkasan seluruh kelas resmi (prioritaskan yang memiliki siswa)
    cursor.execute("""
        SELECT 
            COALESCE(c.name, s.class_name) as class_name,
            MIN(COALESCE(c.grade, s.grade, 10)) as grade,
            COUNT(DISTINCT s.id) as total_students,
            COUNT(DISTINCT a.id) as allocated_count
        FROM cbt_synced_classes c
        LEFT JOIN cbt_synced_students s ON (TRIM(s.class_name) = TRIM(c.name))
        LEFT JOIN cbt_student_allocations a ON s.id = a.student_id
        WHERE COALESCE(c.name, s.class_name) IS NOT NULL 
          AND COALESCE(c.name, s.class_name) != '' 
          AND COALESCE(c.name, s.class_name) != '-'
        GROUP BY COALESCE(c.name, s.class_name)
        ORDER BY 
            CASE WHEN COUNT(DISTINCT s.id) > 0 THEN 0 ELSE 1 END,
            MIN(COALESCE(c.grade, s.grade, 10)) ASC, 
            COALESCE(c.name, s.class_name) ASC
    """)
    classes = [dict(r) for r in cursor.fetchall()]

    db.close()
    return {
        "success": True,
        "total": len(students),
        "students": students,
        "classes": classes
    }

# -------------------------------------------------------------
# 2. MASTER SESI UJIAN
# -------------------------------------------------------------
@router.get("/sessions")
def list_sessions(current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM cbt_sessions ORDER BY start_time ASC")
    sessions = [dict(row) for row in cursor.fetchall()]
    db.close()
    return {"success": True, "sessions": sessions}

@router.post("/sessions")
def create_session(req: SessionRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("INSERT INTO cbt_sessions (session_name, start_time, end_time) VALUES (%s, %s, %s) RETURNING id",
                       (req.session_name.strip(), req.start_time.strip(), req.end_time.strip()))
        s_id = cursor.fetchone()[0]
        db.commit()
        db.close()
        return {"success": True, "message": f"Sesi '{req.session_name}' berhasil ditambahkan.", "session_id": s_id}
    except Exception as e:
        db.close()
        raise HTTPException(status_code=400, detail=f"Gagal menambahkan sesi: {str(e)}")

@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM cbt_sessions WHERE id = ?", (session_id,))
    db.commit()
    db.close()
    return {"success": True, "message": "Sesi berhasil dihapus."}

# -------------------------------------------------------------
# 3. PLOTTING & ALOKASI SISWA KE RUANG & SESI
# -------------------------------------------------------------
@router.get("/allocations")
def list_allocations(
    class_name: Optional[str] = None,
    room_name: Optional[str] = None,
    session_name: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    db = get_db()
    cursor = db.cursor()

    query = """
        SELECT a.*, s.nis, s.gender, s.photo, s.nik, s.exam_password
        FROM cbt_student_allocations a
        LEFT JOIN cbt_synced_students s ON a.student_id = s.id
        WHERE 1=1
    """
    params = []

    if class_name and class_name != "all":
        query += " AND a.class_name = ?"
        params.append(class_name)
    if room_name and room_name != "all":
        query += " AND a.room_name = ?"
        params.append(room_name)
    if session_name and session_name != "all":
        query += " AND a.session_name = ?"
        params.append(session_name)

    query += " ORDER BY a.room_name ASC, a.session_name ASC, a.seat_number ASC"
    cursor.execute(query, tuple(params))
    allocations = [dict(row) for row in cursor.fetchall()]
    db.close()

    return {"success": True, "total": len(allocations), "allocations": allocations}

@router.post("/auto-allocate")
def auto_allocate_students(current_user: dict = Depends(get_current_user)):
    """
    GENERATE PLOTTING OTOMATIS:
    Membagi seluruh siswa dari database SIAK secara berurutan ke dalam:
    1. Ruangan-ruangan yang tersedia (berdasarkan kapasitas kursi/PC)
    2. Sesi 1, Sesi 2, Sesi 3 jika kapasitas lab lebih kecil dari total siswa
    3. Nomor Meja (01, 02, 03... per ruangan)
    """
    db = get_db()
    cursor = db.cursor()

    # Ambil seluruh siswa aktif terurut per kelas dan nama
    cursor.execute("""
        SELECT id, name, class_name, nisn
        FROM cbt_synced_students
        ORDER BY class_name ASC, name ASC
    """)
    students = [dict(row) for row in cursor.fetchall()]

    if not students:
        db.close()
        raise HTTPException(status_code=400, detail="Belum ada data siswa. Silakan lakukan 'Sinkron Data SIAK' terlebih dahulu.")

    # Ambil ruangan dan sesi yang tersedia
    cursor.execute("SELECT * FROM cbt_rooms ORDER BY name ASC")
    rooms = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT * FROM cbt_sessions ORDER BY start_time ASC")
    sessions = [dict(row) for row in cursor.fetchall()]

    if not rooms:
        # Fallback default room
        rooms = [{"name": "Lab Komputer 1", "capacity": 36}]
    if not sessions:
        # Fallback default session
        sessions = [{"session_name": "Sesi 1"}]

    # Bersihkan alokasi lama
    cursor.execute("DELETE FROM cbt_student_allocations")

    allocated_count = 0
    student_idx = 0
    total_students = len(students)

    # Distribusi: Loop Sesi -> Loop Ruangan -> Isi sampai kapasitas -> Nomor Meja
    for sess in sessions:
        s_name = sess["session_name"]
        for rm in rooms:
            r_name = rm["name"]
            capacity = rm.get("capacity") or 36

            for seat in range(1, capacity + 1):
                if student_idx >= total_students:
                    break

                stu = students[student_idx]
                cursor.execute("""
                    INSERT INTO cbt_student_allocations 
                    (student_id, student_name, class_name, nisn, room_name, session_name, seat_number)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (stu["id"], stu["name"], stu["class_name"], stu["nisn"], r_name, s_name, seat))

                allocated_count += 1
                student_idx += 1

            if student_idx >= total_students:
                break
        if student_idx >= total_students:
            break

    db.commit()
    db.close()

    return {
        "success": True,
        "message": f"Berhasil membagi {allocated_count} siswa ke dalam {len(rooms)} ruangan dan {len(sessions)} sesi secara otomatis!",
        "allocated_count": allocated_count,
        "remaining_unallocated": max(0, total_students - allocated_count)
    }


# -------------------------------------------------------------
# 3b. PORTAL JADWAL JAGA SAYA (KHUSUS ROLE GURU - READ-ONLY)
# -------------------------------------------------------------
@router.get("/my-schedule")
def get_my_schedule(
    teacher_name: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Mengambil data jadwal tugas mengawas khusus guru yang sedang login (Read-Only).
    Admin atau staff dapat melihat jadwal guru mana pun dengan mengirim param `teacher_name`.
    """
    db = get_db()
    cursor = db.cursor()

    role = (current_user.get("role") or "").lower()
    is_admin = role in ("admin", "superadmin", "administrator", "staff")

    # Cek apakah ada ujian SAS yang sedang aktif
    cursor.execute("SELECT COUNT(*) FROM cbt_exams WHERE exam_type = 'sas' AND status = 'active'")
    row_active_sas = cursor.fetchone()
    active_sas_count = row_active_sas[0] if row_active_sas else 0
    is_exam_completed = (active_sas_count == 0)

    # Tentukan nama guru target & nama-nama padanan (dengan/tanpa gelar, NIP)
    target_name = (current_user.get("name") or "").strip()
    matched_names = get_teacher_matched_names(current_user, cursor)
    if teacher_name and teacher_name.strip():
        if is_admin or teacher_name.strip().lower() == target_name.lower():
            target_name = teacher_name.strip()
            matched_names.append(target_name)
            t_clean = clean_academic_titles(target_name)
            if t_clean:
                matched_names.append(t_clean)
    matched_names = list(set([n for n in matched_names if len(n) >= 2]))
    official_name = matched_names[0] if matched_names else target_name

    norm_name = target_name.lower()
    teacher_profile = {
        "id": current_user.get("teacher_id") or current_user.get("id"),
        "name": official_name,
        "nip": current_user.get("nip") or "-",
        "email": current_user.get("email") or "-",
    }

    # 2. Cek apakah guru terdaftar di cbt_selected_supervisors
    sel_checks = []
    sel_params = []
    for n in matched_names:
        sel_checks.append("""
            (teacher_name IS NOT NULL AND TRIM(teacher_name) != '' AND (
                LOWER(TRIM(teacher_name)) = LOWER(TRIM(%s))
                OR LOWER(TRIM(%s)) LIKE CONCAT('%%', LOWER(TRIM(teacher_name)), '%%')
                OR LOWER(TRIM(teacher_name)) LIKE CONCAT('%%', LOWER(TRIM(%s)), '%%')
            ))
        """)
        sel_params.extend([n, n, n])
    where_sel = " OR ".join(sel_checks) if sel_checks else "1=0"
    cursor.execute(f"""
        SELECT is_active, nip, email FROM cbt_selected_supervisors 
        WHERE {where_sel}
        LIMIT 1
    """, tuple(sel_params))
    row_sel = cursor.fetchone()
    is_selected = bool(row_sel and (row_sel["is_active"] if isinstance(row_sel, dict) else row_sel[0]) == 1)

    # 3. Master Ruang & Master Sesi
    cursor.execute("SELECT id, name, capacity, location FROM cbt_rooms")
    rooms_map = {r["name"]: dict(r) for r in cursor.fetchall()}

    cursor.execute("SELECT id, session_name, start_time, end_time FROM cbt_sessions")
    sessions_map = {s["session_name"]: dict(s) for s in cursor.fetchall()}

    # 4. Ambil jadwal penugasan ruang
    col_checks = []
    col_params = []
    for n in matched_names:
        for col in ["supervisor1_name", "supervisor2_name", "supervisor3_name", "proctor_name"]:
            col_checks.append(f"""
                ({col} IS NOT NULL AND TRIM({col}) != '' AND (
                    LOWER(TRIM({col})) = LOWER(TRIM(%s))
                    OR LOWER(TRIM(%s)) LIKE CONCAT('%%', LOWER(TRIM({col})), '%%')
                    OR LOWER(TRIM({col})) LIKE CONCAT('%%', LOWER(TRIM(%s)), '%%')
                ))
            """)
            col_params.extend([n, n, n])
    where_assign = " OR ".join(col_checks) if col_checks else "1=0"
    cursor.execute(f"""
        SELECT id, exam_date, room_name, session_name, 
               supervisor1_name, supervisor2_name, supervisor3_name, 
               proctor_name, notes, created_at
        FROM cbt_supervisor_assignments
        WHERE {where_assign}
        ORDER BY exam_date ASC, session_name ASC, room_name ASC
    """, tuple(col_params))
    raw_assignments = [dict(r) for r in cursor.fetchall()]

    # 5. Ambil jadwal pengawas cadangan
    back_checks = []
    back_params = []
    for n in matched_names:
        back_checks.append("""
            (teacher_name IS NOT NULL AND TRIM(teacher_name) != '' AND (
                LOWER(TRIM(teacher_name)) = LOWER(TRIM(%s))
                OR LOWER(TRIM(%s)) LIKE CONCAT('%%', LOWER(TRIM(teacher_name)), '%%')
                OR LOWER(TRIM(teacher_name)) LIKE CONCAT('%%', LOWER(TRIM(%s)), '%%')
            ))
        """)
        back_params.extend([n, n, n])
    where_back = " OR ".join(back_checks) if back_checks else "1=0"
    cursor.execute(f"""
        SELECT id, exam_date, session_name, teacher_name, order_num, notes, created_at
        FROM cbt_backup_supervisors
        WHERE {where_back}
        ORDER BY exam_date ASC, session_name ASC, order_num ASC
    """, tuple(back_params))
    raw_backups = [dict(r) for r in cursor.fetchall()]

    # 6. Ambil mapel ujian pada tanggal-tanggal tersebut
    distinct_dates = set([a["exam_date"] for a in raw_assignments if a.get("exam_date")] + [b["exam_date"] for b in raw_backups if b.get("exam_date")])
    date_subjects_map = {}
    if distinct_dates:
        placeholders = ", ".join(["%s"] * len(distinct_dates))
        cursor.execute(f"""
            SELECT DISTINCT id, exam_id, exam_date, subject_name, start_time, end_time, duration_minutes, session_status, session_started_at, session_ended_at
            FROM cbt_exam_subjects
            WHERE exam_date IN ({placeholders})
            ORDER BY exam_date ASC, start_time ASC
        """, tuple(distinct_dates))
        for row in cursor.fetchall():
            d = dict(row)
            ed = d["exam_date"]
            if ed not in date_subjects_map:
                date_subjects_map[ed] = []
            date_subjects_map[ed].append(d)

    # 7. Enrich room assignments
    enriched_room_assignments = []
    for a in raw_assignments:
        s1 = (a.get("supervisor1_name") or "").strip()
        s2 = (a.get("supervisor2_name") or "").strip()
        s3 = (a.get("supervisor3_name") or "").strip()
        pr = (a.get("proctor_name") or "").strip()

        # Tentukan posisi tugas
        role_label = "Pengawas Ruang"
        partners = []
        is_p1 = any(is_name_match(n, s1) for n in matched_names)
        is_p2 = any(is_name_match(n, s2) for n in matched_names)
        is_p3 = any(is_name_match(n, s3) for n in matched_names)
        is_pr = any(is_name_match(n, pr) for n in matched_names)
        if is_p1:
            role_label = "Pengawas 1 (Utama)"
            if s2 and s2 != "-": partners.append(s2)
            if s3 and s3 != "-": partners.append(s3)
        elif is_p2:
            role_label = "Pengawas 2"
            if s1 and s1 != "-": partners.append(s1)
            if s3 and s3 != "-": partners.append(s3)
        elif is_p3:
            role_label = "Pengawas 3"
            if s1 and s1 != "-": partners.append(s1)
            if s2 and s2 != "-": partners.append(s2)
        elif is_pr:
            role_label = "Proktor Ruangan"
            if s2 and s2 != "-": partners.append(s2)
            if s3 and s3 != "-": partners.append(s3)
        elif norm_name in s2.lower():
            role_label = "Pengawas 2"
            if s1 and s1 != "-": partners.append(s1)
            if s3 and s3 != "-": partners.append(s3)
        elif norm_name in s3.lower():
            role_label = "Pengawas 3"
            if s1 and s1 != "-": partners.append(s1)
            if s2 and s2 != "-": partners.append(s2)

        r_info = rooms_map.get(a.get("room_name"), {})
        s_info = sessions_map.get(a.get("session_name"), {})

        time_range = ""
        s_start = (s_info.get("start_time") or "").strip()
        s_end = (s_info.get("end_time") or "").strip()
        if s_start and s_end:
            time_range = f"{s_start} - {s_end}"

        # Cari mata pelajaran yang relevan dengan sesi ini
        all_day_subjects = date_subjects_map.get(a.get("exam_date"), [])
        matched_subjects = []
        for sub in all_day_subjects:
            sub_st = (sub.get("start_time") or "").strip()
            if s_start and sub_st:
                if sub_st == s_start:
                    matched_subjects.append(sub)
                elif s_end and s_start <= sub_st < s_end:
                    matched_subjects.append(sub)

        # Fallback jika tidak ada kecocokan jam persis
        if not matched_subjects and all_day_subjects:
            m = re.search(r'\d+', a.get("session_name") or "")
            if m:
                s_idx = int(m.group(0)) - 1
                if 0 <= s_idx < len(all_day_subjects):
                    matched_subjects = [all_day_subjects[s_idx]]
            if not matched_subjects:
                matched_subjects = all_day_subjects

        # Tentukan status sesi ujian berdasarkan cbt_exam_subjects yang diaktifkan Admin
        is_session_active = any((s.get("session_status") or "").lower() == "active" for s in matched_subjects)
        all_completed = len(matched_subjects) > 0 and all((s.get("session_status") or "").lower() == "completed" for s in matched_subjects)
        any_completed = any((s.get("session_status") or "").lower() == "completed" for s in matched_subjects)

        if is_session_active:
            duty_session_status = "active"
        elif all_completed:
            duty_session_status = "completed"
        elif any_completed:
            duty_session_status = "completed"
        else:
            duty_session_status = "idle"

        enriched_room_assignments.append({
            "id": a["id"],
            "type": "room",
            "exam_date": a.get("exam_date"),
            "session_name": a.get("session_name"),
            "session_time": time_range,
            "room_name": a.get("room_name"),
            "room_location": r_info.get("location") or "Gedung Sekolah",
            "room_capacity": r_info.get("capacity") or 36,
            "role_label": role_label,
            "partners": partners,
            "proctor_name": a.get("proctor_name"),
            "notes": a.get("notes"),
            "subjects": matched_subjects if matched_subjects else all_day_subjects,
            "all_day_subjects": all_day_subjects,
            "is_session_active": is_session_active,
            "session_status": duty_session_status,
            "can_start_proctoring": is_session_active or is_admin
        })

    # 8. Enrich backup assignments
    enriched_backup_assignments = []
    for b in raw_backups:
        s_info = sessions_map.get(b.get("session_name"), {})
        time_range = ""
        s_start = (s_info.get("start_time") or "").strip()
        s_end = (s_info.get("end_time") or "").strip()
        if s_start and s_end:
            time_range = f"{s_start} - {s_end}"

        all_day_subjects = date_subjects_map.get(b.get("exam_date"), [])
        matched_subjects = []
        for sub in all_day_subjects:
            sub_st = (sub.get("start_time") or "").strip()
            if s_start and sub_st:
                if sub_st == s_start:
                    matched_subjects.append(sub)
                elif s_end and s_start <= sub_st < s_end:
                    matched_subjects.append(sub)

        is_session_active = any((s.get("session_status") or "").lower() == "active" for s in matched_subjects)
        all_completed = len(matched_subjects) > 0 and all((s.get("session_status") or "").lower() == "completed" for s in matched_subjects)
        if is_session_active:
            duty_session_status = "active"
        elif all_completed:
            duty_session_status = "completed"
        else:
            duty_session_status = "idle"

        enriched_backup_assignments.append({
            "id": b["id"],
            "type": "backup",
            "exam_date": b.get("exam_date"),
            "session_name": b.get("session_name"),
            "session_time": time_range,
            "order_num": b.get("order_num", 1),
            "role_label": f"Pengawas Cadangan (Ke-{b.get('order_num', 1)})",
            "location": "Sekretariat Panitia Ujian / Ruang Piket",
            "notes": b.get("notes") or "Standby di Ruang Panitia CBT untuk menggantikan pengawas utama yang berhalangan",
            "subjects": matched_subjects if matched_subjects else all_day_subjects,
            "is_session_active": is_session_active,
            "session_status": duty_session_status
        })

    # 9. Profil Sekolah untuk Lembar Cetak
    cursor.execute("SELECT * FROM cbt_synced_school_profile LIMIT 1")
    sp = cursor.fetchone()
    school_profile = dict(sp) if sp else {
        "school_name": "SMA Negeri 1",
        "address": "Jl. Pendidikan No. 1",
        "headmaster_name": "Kepala Sekolah",
        "headmaster_nip": "-"
    }

    # 10. Daftar seluruh guru pengawas (untuk switcher admin jika admin membuka halaman ini)
    all_supervisors = []
    if is_admin:
        cursor.execute("""
            SELECT DISTINCT t.name, t.nip,
                   COALESCE(s.is_active, 0) as is_supervisor
            FROM cbt_synced_teachers t
            LEFT JOIN cbt_selected_supervisors s ON LOWER(TRIM(t.name)) = LOWER(TRIM(s.teacher_name))
            ORDER BY t.name ASC
        """)
        all_supervisors = [dict(r) for r in cursor.fetchall()]

    db.close()

    total_duties = len(enriched_room_assignments) + len(enriched_backup_assignments)

    return {
        "success": True,
        "teacher": teacher_profile,
        "is_selected_supervisor": is_selected,
        "is_admin": is_admin,
        "is_exam_completed": is_exam_completed,
        "summary": {
            "total_duties": total_duties,
            "room_duties_count": len(enriched_room_assignments),
            "backup_duties_count": len(enriched_backup_assignments),
            "distinct_dates_count": len(distinct_dates),
            "distinct_dates": sorted(list(distinct_dates))
        },
        "room_assignments": enriched_room_assignments,
        "backup_assignments": enriched_backup_assignments,
        "school_profile": school_profile,
        "all_teachers": all_supervisors
    }

# -------------------------------------------------------------
# 4. PENUGASAN PENGAWAS & PROKTOR RUANGAN + PENGAWAS CADANGAN
# -------------------------------------------------------------
@router.get("/supervisors")
def list_supervisors(current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()

    # 1. Jadwal Pengawas Ruangan
    cursor.execute("SELECT * FROM cbt_supervisor_assignments ORDER BY exam_date ASC, session_name ASC, room_name ASC")
    assignments = [dict(row) for row in cursor.fetchall()]

    # 2. Pengawas Cadangan (Standby)
    cursor.execute("SELECT * FROM cbt_backup_supervisors ORDER BY exam_date ASC, session_name ASC, order_num ASC")
    backups = [dict(row) for row in cursor.fetchall()]

    # 3. Daftar Guru Aktif dari Database
    cursor.execute("SELECT id, name, nip, email FROM cbt_synced_teachers ORDER BY name ASC")
    teachers = [dict(row) for row in cursor.fetchall()]

    # 4. Rekap Beban Mengawas per Guru
    duty_counts = {}
    for a in assignments:
        for s_field in ["supervisor1_name", "supervisor2_name", "supervisor3_name"]:
            name = a.get(s_field)
            if name and name.strip() and name != "-":
                duty_counts[name] = duty_counts.get(name, 0) + 1
    for b in backups:
        name = b.get("teacher_name")
        if name and name.strip():
            duty_counts[name] = duty_counts.get(name, 0) + 1

    # 5. Master Ruangan
    cursor.execute("SELECT id, name, capacity, location FROM cbt_rooms ORDER BY name ASC")
    rooms = [dict(row) for row in cursor.fetchall()]

    # 6. Master Sesi
    cursor.execute("SELECT id, session_name, start_time, end_time FROM cbt_sessions ORDER BY start_time ASC")
    sessions = [dict(row) for row in cursor.fetchall()]

    # 7. Guru yang Ditetapkan Sebagai Pengawas Ujian
    cursor.execute("SELECT teacher_id, teacher_name, nip FROM cbt_selected_supervisors WHERE is_active = 1 ORDER BY teacher_name ASC")
    selected_supervisors = [dict(row) for row in cursor.fetchall()]

    # 8. Daftar Tanggal Ujian yang Tersedia
    cursor.execute("""
        SELECT DISTINCT exam_date FROM (
            SELECT exam_date FROM cbt_supervisor_assignments
            UNION
            SELECT exam_date FROM cbt_backup_supervisors
            UNION
            SELECT exam_date FROM cbt_sas_schedules
            UNION
            SELECT exam_date FROM cbt_exam_subjects WHERE exam_date IS NOT NULL
        ) AS sub WHERE exam_date IS NOT NULL AND exam_date != ''
        ORDER BY exam_date ASC
    """)
    dates = [r[0] for r in cursor.fetchall()]

    # 9. Cek apakah ada paket ujian SAS/sekolah yang sedang aktif
    cursor.execute("SELECT COUNT(*) FROM cbt_exams WHERE LOWER(COALESCE(exam_type, 'sas')) = 'sas' AND status = 'active'")
    row_active_sas = cursor.fetchone()
    active_sas_count = row_active_sas[0] if row_active_sas else 0
    is_exam_completed = (active_sas_count == 0)

    db.close()
    return {
        "success": True,
        "is_exam_completed": is_exam_completed,
        "assignments": assignments,
        "backups": backups,
        "teachers": teachers,
        "duty_counts": duty_counts,
        "rooms": rooms,
        "sessions": sessions,
        "selected_supervisors": selected_supervisors,
        "available_dates": dates
    }

@router.get("/supervisors/archives")
def list_supervisor_archives(current_user: dict = Depends(get_current_user)):
    """Mengambil daftar riwayat arsip jadwal pengawas dari paket ujian yang telah selesai"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        SELECT 
            e.id as exam_id,
            e.title as exam_title,
            e.status as exam_status,
            COUNT(DISTINCT a.id) as assignments_count,
            COUNT(DISTINCT b.id) as backups_count,
            MAX(COALESCE(a.archived_at, b.archived_at)) as archived_at
        FROM cbt_exams e
        LEFT JOIN cbt_supervisor_assignments_archive a ON e.id = a.exam_id
        LEFT JOIN cbt_backup_supervisors_archive b ON e.id = b.exam_id
        WHERE a.id IS NOT NULL OR b.id IS NOT NULL
        GROUP BY e.id, e.title, e.status
        ORDER BY MAX(COALESCE(a.archived_at, b.archived_at)) DESC
    """)
    archives = [dict(r) for r in cursor.fetchall()]
    db.close()
    return {"success": True, "archives": archives}

@router.get("/supervisors/archives/{exam_id}")
def get_supervisor_archive_detail(exam_id: int, current_user: dict = Depends(get_current_user)):
    """Mengambil detail jadwal pengawas ruangan dan cadangan yang tersimpan di arsip untuk paket ujian tertentu"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id, title, status FROM cbt_exams WHERE id = %s", (exam_id,))
    exam = cursor.fetchone()
    if not exam:
        db.close()
        raise HTTPException(status_code=404, detail="Paket ujian tidak ditemukan.")

    cursor.execute("""
        SELECT * FROM cbt_supervisor_assignments_archive 
        WHERE exam_id = %s 
        ORDER BY exam_date ASC, session_name ASC, room_name ASC
    """, (exam_id,))
    assignments = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT * FROM cbt_backup_supervisors_archive 
        WHERE exam_id = %s 
        ORDER BY exam_date ASC, session_name ASC, order_num ASC
    """, (exam_id,))
    backups = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT teacher_id, teacher_name, nip, email 
        FROM cbt_selected_supervisors_archive 
        WHERE exam_id = %s 
        ORDER BY teacher_name ASC
    """, (exam_id,))
    selected_supervisors = [dict(r) for r in cursor.fetchall()]

    # Hitung rekap beban mengawas dari arsip
    duty_counts = {}
    for a in assignments:
        for s_field in ["supervisor1_name", "supervisor2_name", "supervisor3_name"]:
            name = a.get(s_field)
            if name and name.strip() and name != "-":
                duty_counts[name] = duty_counts.get(name, 0) + 1
    for b in backups:
        name = b.get("teacher_name")
        if name and name.strip():
            duty_counts[name] = duty_counts.get(name, 0) + 1

    db.close()
    return {
        "success": True,
        "exam": dict(exam),
        "assignments": assignments,
        "backups": backups,
        "selected_supervisors": selected_supervisors,
        "duty_counts": duty_counts
    }

# -------------------------------------------------------------
# 4b. MANAJEMEN PENGAWAS UJIAN (PILIHAN DARI DATA GURU SIAK)
# -------------------------------------------------------------
@router.get("/supervisors/candidates")
def list_supervisor_candidates(current_user: dict = Depends(get_current_user)):
    """Mengambil daftar seluruh guru dari SIAK beserta status apakah dipilih sebagai pengawas ujian"""
    db = get_db()
    cursor = db.cursor()

    # Tabel cbt_selected_supervisors sudah diinisialisasi di database.py

    cursor.execute("""
        SELECT 
            t.id, 
            t.nip, 
            t.name, 
            t.email, 
            t.synced_at,
            CASE WHEN s.id IS NOT NULL AND s.is_active = 1 THEN 1 ELSE 0 END as is_supervisor,
            s.assigned_at,
            (
                SELECT COUNT(*) FROM cbt_supervisor_assignments a 
                WHERE a.supervisor1_name = t.name 
                   OR a.supervisor2_name = t.name 
                   OR a.supervisor3_name = t.name
            ) as duty_count,
            (
                SELECT COUNT(*) FROM cbt_backup_supervisors b 
                WHERE b.teacher_name = t.name
            ) as backup_count
        FROM cbt_synced_teachers t
        LEFT JOIN cbt_selected_supervisors s ON t.id = s.teacher_id
        ORDER BY 
            is_supervisor DESC,
            t.name ASC
    """)
    teachers = [dict(row) for row in cursor.fetchall()]

    total_teachers = len(teachers)
    total_supervisors = sum(1 for t in teachers if t["is_supervisor"] == 1)
    total_non_supervisors = total_teachers - total_supervisors

    db.close()
    return {
        "success": True,
        "total": total_teachers,
        "total_supervisors": total_supervisors,
        "total_non_supervisors": total_non_supervisors,
        "teachers": teachers
    }

@router.post("/supervisors/toggle")
def toggle_supervisor(req: ToggleSupervisorRequest, current_user: dict = Depends(get_current_user)):
    """Menjadikan atau membatalkan seorang guru sebagai pengawas ujian"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id, name, nip, email FROM cbt_synced_teachers WHERE id = ?", (req.teacher_id,))
    tch = cursor.fetchone()
    if not tch:
        db.close()
        raise HTTPException(status_code=404, detail="Data guru tidak ditemukan.")

    tch_dict = dict(tch)

    if req.is_supervisor:
        cursor.execute("""
            INSERT INTO cbt_selected_supervisors (teacher_id, teacher_name, nip, email, is_active, assigned_at)
            VALUES (%s, %s, %s, %s, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(teacher_id) DO UPDATE SET 
                is_active = 1,
                teacher_name = EXCLUDED.teacher_name,
                nip = EXCLUDED.nip,
                email = EXCLUDED.email,
                assigned_at = CURRENT_TIMESTAMP
        """, (tch_dict["id"], tch_dict["name"], tch_dict["nip"], tch_dict["email"]))
        msg = f"Guru '{tch_dict['name']}' berhasil ditetapkan sebagai Pengawas Ujian."
    else:
        cursor.execute("DELETE FROM cbt_selected_supervisors WHERE teacher_id = ?", (req.teacher_id,))
        msg = f"Status Pengawas Ujian untuk '{tch_dict['name']}' berhasil dicabut."

    db.commit()
    db.close()
    return {"success": True, "message": msg, "teacher_id": req.teacher_id, "is_supervisor": req.is_supervisor}

@router.post("/supervisors/batch-select")
def batch_select_supervisors(req: BatchSupervisorsRequest, current_user: dict = Depends(get_current_user)):
    """Memperbarui penetapan pengawas ujian secara massal (pilih semua, batalkan semua, atau perbarui daftar terpilih)"""
    db = get_db()
    cursor = db.cursor()

    if req.action == "clear_all":
        cursor.execute("DELETE FROM cbt_selected_supervisors")
        db.commit()
        db.close()
        return {"success": True, "message": "Seluruh penetapan pengawas ujian berhasil dikosongkan."}

    if req.action == "set_all":
        cursor.execute("SELECT id, name, nip, email FROM cbt_synced_teachers")
        all_teachers = cursor.fetchall()
        for t in all_teachers:
            t_d = dict(t)
            cursor.execute("""
                INSERT INTO cbt_selected_supervisors (teacher_id, teacher_name, nip, email, is_active, assigned_at)
                VALUES (%s, %s, %s, %s, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(teacher_id) DO UPDATE SET 
                    is_active = 1,
                    teacher_name = EXCLUDED.teacher_name,
                    nip = EXCLUDED.nip,
                    email = EXCLUDED.email
            """, (t_d["id"], t_d["name"], t_d["nip"], t_d["email"]))
        db.commit()
        db.close()
        return {"success": True, "message": f"Seluruh guru ({len(all_teachers)} guru) berhasil ditetapkan sebagai Pengawas Ujian."}

    # action == "set_selected"
    selected_ids = set(req.teacher_ids or [])
    cursor.execute("DELETE FROM cbt_selected_supervisors")
    if selected_ids:
        placeholders = ",".join(["%s"] * len(selected_ids))
        cursor.execute(f"SELECT id, name, nip, email FROM cbt_synced_teachers WHERE id IN ({placeholders})", tuple(selected_ids))
        chosen_teachers = cursor.fetchall()
        for t in chosen_teachers:
            t_d = dict(t)
            cursor.execute("""
                INSERT INTO cbt_selected_supervisors (teacher_id, teacher_name, nip, email, is_active, assigned_at)
                VALUES (%s, %s, %s, %s, 1, CURRENT_TIMESTAMP)
            """, (t_d["id"], t_d["name"], t_d["nip"], t_d["email"]))
        count = len(chosen_teachers)
    else:
        count = 0

    db.commit()
    db.close()
    return {"success": True, "message": f"Berhasil memperbarui penetapan pengawas ujian ({count} guru terpilih)."}

@router.post("/supervisors")
def assign_supervisor(req: SupervisorAssignmentRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()

    s1 = req.supervisor1_name.strip() if req.supervisor1_name and req.supervisor1_name.strip() else None
    s2 = req.supervisor2_name.strip() if req.supervisor2_name and req.supervisor2_name.strip() else None
    s3 = req.supervisor3_name.strip() if req.supervisor3_name and req.supervisor3_name.strip() else None
    proctor = req.proctor_name.strip() if req.proctor_name and req.proctor_name.strip() else None
    notes = req.notes.strip() if req.notes and req.notes.strip() else None

    # 1. Validasi Bentrok Pengawas 1 & Pengawas 2 di Ruangan yang Sama
    if s1 and s2 and s1 == s2:
        db.close()
        raise HTTPException(
            status_code=400,
            detail=f"Jadwal Bentrok: Guru '{s1}' tidak dapat dipilih sekaligus sebagai Pengawas 1 dan Pengawas 2 di ruangan yang sama."
        )

    # Tentukan ID penugasan yang sedang diproses untuk mengecualikan diri sendiri saat pengecekan bentrok
    target_id = req.id
    if not target_id:
        cursor.execute("""
            SELECT id FROM cbt_supervisor_assignments
            WHERE exam_date = ? AND room_name = ? AND session_name = ?
        """, (req.exam_date, req.room_name, req.session_name))
        existing_row = cursor.fetchone()
        if existing_row:
            target_id = existing_row[0]

    # 2. Validasi Bentrok Guru Mengawas di Ruangan Lain pada Tanggal & Sesi yang Sama
    supervisors_to_check = [s for s in [s1, s2, s3] if s]
    for tch in supervisors_to_check:
        if target_id is not None:
            cursor.execute("""
                SELECT room_name FROM cbt_supervisor_assignments
                WHERE exam_date = %s AND session_name = %s
                  AND id != %s
                  AND (supervisor1_name = %s OR supervisor2_name = %s OR supervisor3_name = %s)
            """, (req.exam_date, req.session_name, target_id, tch, tch, tch))
        else:
            cursor.execute("""
                SELECT room_name FROM cbt_supervisor_assignments
                WHERE exam_date = %s AND session_name = %s
                  AND (supervisor1_name = %s OR supervisor2_name = %s OR supervisor3_name = %s)
            """, (req.exam_date, req.session_name, tch, tch, tch))
        clash_room = cursor.fetchone()
        if clash_room:
            db.close()
            raise HTTPException(
                status_code=400,
                detail=f"Jadwal Bentrok: Guru '{tch}' sudah ditugaskan mengawas di ruangan '{clash_room[0]}' pada {req.session_name} ({req.exam_date}). Satu pengawas tidak dapat mengawas di lebih dari satu ruangan pada sesi yang sama."
            )

        # 3. Validasi Bentrok Pengawas Ruang vs Pengawas Cadangan pada Tanggal & Sesi yang Sama
        cursor.execute("""
            SELECT order_num FROM cbt_backup_supervisors
            WHERE exam_date = ? AND session_name = ? AND teacher_name = ?
        """, (req.exam_date, req.session_name, tch))
        clash_backup = cursor.fetchone()
        if clash_backup:
            db.close()
            raise HTTPException(
                status_code=400,
                detail=f"Jadwal Bentrok: Guru '{tch}' sudah terdaftar sebagai Pengawas Cadangan {clash_backup[0]} pada {req.session_name} ({req.exam_date}). Harap batalkan tugas cadangannya terlebih dahulu jika ingin menugaskannya di ruangan."
            )

    if req.id:
        cursor.execute("""
            UPDATE cbt_supervisor_assignments
            SET exam_date = ?, room_name = ?, session_name = ?, supervisor1_name = ?, supervisor2_name = ?, supervisor3_name = ?, proctor_name = ?, notes = ?
            WHERE id = ?
        """, (req.exam_date, req.room_name, req.session_name, s1, s2, s3, proctor, notes, req.id))
    else:
        if target_id:
            cursor.execute("""
                UPDATE cbt_supervisor_assignments
                SET supervisor1_name = ?, supervisor2_name = ?, supervisor3_name = ?, proctor_name = ?, notes = ?
                WHERE id = ?
            """, (s1, s2, s3, proctor, notes, target_id))
        else:
            cursor.execute("""
                INSERT INTO cbt_supervisor_assignments
                (exam_date, room_name, session_name, supervisor1_name, supervisor2_name, supervisor3_name, proctor_name, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (req.exam_date, req.room_name, req.session_name, s1, s2, s3, proctor, notes))

    db.commit()
    db.close()
    return {"success": True, "message": "Penugasan Pengawas & Proktor berhasil disimpan!"}

@router.delete("/supervisors/{assignment_id}")
def delete_supervisor_assignment(assignment_id: int, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM cbt_supervisor_assignments WHERE id = ?", (assignment_id,))
    db.commit()
    db.close()
    return {"success": True, "message": "Tugas pengawas ruang berhasil dihapus."}

@router.post("/supervisors/backups")
def add_backup_supervisor(req: BackupSupervisorRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    tch = req.teacher_name.strip()

    # 1. Validasi Bentrok Guru Sedang Mengawas di Ruangan pada Sesi Tersebut
    cursor.execute("""
        SELECT room_name FROM cbt_supervisor_assignments
        WHERE exam_date = ? AND session_name = ?
          AND (supervisor1_name = ? OR supervisor2_name = ? OR supervisor3_name = ?)
    """, (req.exam_date, req.session_name, tch, tch, tch))
    clash_room = cursor.fetchone()
    if clash_room:
        db.close()
        raise HTTPException(
            status_code=400,
            detail=f"Jadwal Bentrok: Guru '{tch}' sedang bertugas mengawas di ruangan '{clash_room[0]}' pada {req.session_name} ({req.exam_date}). Tidak dapat ditugaskan sebagai pengawas cadangan pada sesi yang sama."
        )

    # 2. Validasi Bentrok Guru Sudah Terdaftar Sebagai Cadangan pada Sesi Tersebut
    if req.id is not None:
        cursor.execute("""
            SELECT order_num FROM cbt_backup_supervisors
            WHERE exam_date = %s AND session_name = %s AND teacher_name = %s
              AND id != %s
        """, (req.exam_date, req.session_name, tch, req.id))
    else:
        cursor.execute("""
            SELECT order_num FROM cbt_backup_supervisors
            WHERE exam_date = %s AND session_name = %s AND teacher_name = %s
        """, (req.exam_date, req.session_name, tch))
    clash_backup = cursor.fetchone()
    if clash_backup:
        db.close()
        raise HTTPException(
            status_code=400,
            detail=f"Jadwal Bentrok: Guru '{tch}' sudah terdaftar sebagai Cadangan {clash_backup[0]} pada {req.session_name} ({req.exam_date})."
        )

    try:
        if req.id:
            cursor.execute("""
                UPDATE cbt_backup_supervisors
                SET exam_date = ?, session_name = ?, teacher_name = ?, order_num = ?, notes = ?
                WHERE id = ?
            """, (req.exam_date, req.session_name, tch, req.order_num, req.notes, req.id))
            msg = f"Pengawas cadangan '{tch}' berhasil diperbarui!"
        else:
            cursor.execute("""
                INSERT INTO cbt_backup_supervisors (exam_date, session_name, teacher_name, order_num, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (req.exam_date, req.session_name, tch, req.order_num, req.notes))
            msg = f"Pengawas cadangan '{tch}' berhasil ditambahkan!"
        db.commit()
        db.close()
        return {"success": True, "message": msg}
    except HTTPException:
        db.close()
        raise
    except Exception as e:
        db.close()
        raise HTTPException(status_code=400, detail=f"Gagal menambahkan pengawas cadangan: {str(e)}")

@router.delete("/supervisors/backups/{backup_id}")
def delete_backup_supervisor(backup_id: int, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM cbt_backup_supervisors WHERE id = ?", (backup_id,))
    db.commit()
    db.close()
    return {"success": True, "message": "Pengawas cadangan berhasil dihapus."}

@router.delete("/supervisors/clear-all")
def clear_all_supervisors(exam_date: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    if exam_date:
        cursor.execute("DELETE FROM cbt_supervisor_assignments WHERE exam_date = ?", (exam_date,))
        cursor.execute("DELETE FROM cbt_backup_supervisors WHERE exam_date = ?", (exam_date,))
        msg = f"Seluruh jadwal pengawas pada tanggal {exam_date} berhasil dikosongkan."
    else:
        cursor.execute("DELETE FROM cbt_supervisor_assignments")
        cursor.execute("DELETE FROM cbt_backup_supervisors")
        msg = "Seluruh penugasan pengawas dan cadangan berhasil dikosongkan."
    db.commit()
    db.close()
    return {"success": True, "message": msg}

@router.post("/supervisors/auto-assign")
def auto_assign_supervisors(req: AutoAssignSupervisorsRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()

    # 1. Tentukan tanggal ujian yang akan di-plot
    dates = req.exam_dates
    if not dates or len(dates) == 0:
        cursor.execute("""
            SELECT DISTINCT exam_date FROM (
                SELECT exam_date FROM cbt_sas_schedules
                UNION
                SELECT exam_date FROM cbt_exam_subjects WHERE exam_date IS NOT NULL
                UNION
                SELECT exam_date FROM cbt_supervisor_assignments
            ) AS sub WHERE exam_date IS NOT NULL AND exam_date != ''
            ORDER BY exam_date ASC
        """)
        dates = [r[0] for r in cursor.fetchall() if r[0]]
    if not dates:
        dates = [datetime.now().strftime("%Y-%m-%d")]

    # 2. Ambil master Ruangan
    cursor.execute("SELECT name FROM cbt_rooms ORDER BY name ASC")
    rooms = [r[0] for r in cursor.fetchall()]
    if not rooms:
        db.close()
        raise HTTPException(status_code=400, detail="Belum ada Ruang Lab yang terdaftar. Tambahkan ruang lab terlebih dahulu.")

    # 3. Ambil master Sesi
    cursor.execute("SELECT session_name FROM cbt_sessions ORDER BY start_time ASC")
    sessions = [r[0] for r in cursor.fetchall()]
    if not sessions:
        db.close()
        raise HTTPException(status_code=400, detail="Belum ada Sesi Ujian yang terdaftar. Tambahkan sesi terlebih dahulu.")

    # 4. Ambil daftar Guru yang siap ditugaskan
    teachers = req.selected_teachers
    if not teachers or len(teachers) == 0:
        cursor.execute("SELECT teacher_name FROM cbt_selected_supervisors WHERE is_active = 1 ORDER BY teacher_name ASC")
        selected_sup = [r[0] for r in cursor.fetchall() if r[0]]
        if selected_sup:
            teachers = selected_sup
        else:
            cursor.execute("SELECT name FROM cbt_synced_teachers ORDER BY name ASC")
            teachers = [r[0] for r in cursor.fetchall() if r[0]]

    if not teachers:
        db.close()
        raise HTTPException(status_code=400, detail="Belum ada data guru. Silakan sinkronkan data guru dari SIAK.")

    # 5. Parameter pembagian
    sup_per_room = min(max(req.supervisors_per_room, 1), 3)
    backup_count = max(req.backup_count_per_session, 0)
    proctors = req.proctors_pool or ["Ahmad Fauzi, S.Kom.", "Proktor Lab 1", "Proktor Lab 2", "Proktor Lab 3"]

    # Inisialisasi hitungan beban tugas guru
    duty_counts = {t: 0 for t in teachers}

    # Hapus jadwal sebelumnya untuk tanggal-tanggal terpilih jika replace_existing
    if req.replace_existing:
        for d in dates:
            cursor.execute("DELETE FROM cbt_supervisor_assignments WHERE exam_date = ?", (d,))
            cursor.execute("DELETE FROM cbt_backup_supervisors WHERE exam_date = ?", (d,))

    total_room_assignments = 0
    total_backups_assigned = 0

    # Algoritma Rotasi Bergilir & Anti-Bentrok Sesi
    for d in dates:
        for sess in sessions:
            assigned_this_session = set()

            # A. Plotting Pengawas Ruangan
            for rm_idx, rm in enumerate(rooms):
                # Cari guru yang belum ditugaskan pada sesi ini
                available = [t for t in teachers if t not in assigned_this_session]
                # Urutkan berdasarkan beban terendah, dengan jitter acak agar variatif
                available.sort(key=lambda t: (duty_counts[t], random.random()))

                chosen_supervisors = []
                for _ in range(sup_per_room):
                    if available:
                        chosen = available.pop(0)
                        chosen_supervisors.append(chosen)
                        assigned_this_session.add(chosen)
                        duty_counts[chosen] += 1

                s1 = chosen_supervisors[0] if len(chosen_supervisors) > 0 else "-"
                s2 = chosen_supervisors[1] if len(chosen_supervisors) > 1 else None
                s3 = chosen_supervisors[2] if len(chosen_supervisors) > 2 else None

                cursor.execute("""
                    INSERT INTO cbt_supervisor_assignments
                    (exam_date, room_name, session_name, supervisor1_name, supervisor2_name, supervisor3_name, proctor_name, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, NULL, NULL)
                    ON CONFLICT (exam_date, room_name, session_name) DO UPDATE SET
                        supervisor1_name = EXCLUDED.supervisor1_name,
                        supervisor2_name = EXCLUDED.supervisor2_name,
                        supervisor3_name = EXCLUDED.supervisor3_name,
                        proctor_name = NULL,
                        notes = NULL
                """, (d, rm, sess, s1, s2, s3))
                total_room_assignments += 1

            # B. Plotting Pengawas Cadangan / Standby (Sekretariat Panitia)
            if backup_count > 0:
                backup_avail = [t for t in teachers if t not in assigned_this_session]
                backup_avail.sort(key=lambda t: (duty_counts[t], random.random()))

                for b_idx in range(1, backup_count + 1):
                    if backup_avail:
                        chosen_backup = backup_avail.pop(0)
                        assigned_this_session.add(chosen_backup)
                        duty_counts[chosen_backup] += 1

                        cursor.execute("""
                            INSERT INTO cbt_backup_supervisors
                            (exam_date, session_name, teacher_name, order_num, notes)
                            VALUES (%s, %s, %s, %s, 'Pengawas Cadangan (Standby Sekretariat)')
                            ON CONFLICT (exam_date, session_name, teacher_name) DO UPDATE SET
                                order_num = EXCLUDED.order_num,
                                notes = EXCLUDED.notes
                        """, (d, sess, chosen_backup, b_idx))
                        total_backups_assigned += 1

    db.commit()
    db.close()

    return {
        "success": True,
        "message": f"Berhasil menugaskan pengawas secara otomatis untuk {len(dates)} tanggal! Terisi {total_room_assignments} ruangan dan {total_backups_assigned} pengawas cadangan.",
        "total_room_assignments": total_room_assignments,
        "total_backups_assigned": total_backups_assigned,
        "duty_counts": duty_counts
    }

# -------------------------------------------------------------
# 5. MATRIKS JADWAL MATA PELAJARAN SAS
# -------------------------------------------------------------
@router.get("/matriks")
def list_matrix(current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT m.*, b.title as bank_title, b.total_questions
        FROM cbt_sas_schedules m
        LEFT JOIN cbt_question_banks b ON m.bank_id = b.id
        ORDER BY m.exam_date ASC, m.period_number ASC
    """)
    matrix = [dict(row) for row in cursor.fetchall()]
    db.close()
    return {"success": True, "matrix": matrix}

@router.post("/matriks")
def create_matrix_item(req: SasMatrixRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO cbt_sas_schedules
        (exam_date, day_name, period_number, subject_name, grade, bank_id, duration_minutes, start_time, end_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (req.exam_date, req.day_name, req.period_number, req.subject_name, req.grade, req.bank_id, req.duration_minutes, req.start_time, req.end_time))
    db.commit()
    db.close()
    return {"success": True, "message": f"Mata pelajaran {req.subject_name} berhasil ditambahkan ke jadwal SAS!"}

@router.delete("/matriks/{item_id}")
def delete_matrix_item(item_id: int, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM cbt_sas_schedules WHERE id = ?", (item_id,))
    db.commit()
    db.close()
    return {"success": True, "message": "Jadwal berhasil dihapus."}


# -------------------------------------------------------------
# 6. PENGAWAS RUANGAN: PROKTORING, PRESENSI & BERITA ACARA
# -------------------------------------------------------------

class RoomProctorUnlockRequest(BaseModel):
    session_ids: Optional[List[int]] = None
    session_id: Optional[int] = None

class RoomProctorResetLoginRequest(BaseModel):
    session_id: int

class RoomProctorSubmitRequest(BaseModel):
    session_id: int

class RoomAttendanceItem(BaseModel):
    student_id: int
    student_name: str
    class_name: Optional[str] = None
    nisn: Optional[str] = None
    status: str = "H"  # 'H' (Hadir), 'I' (Izin), 'S' (Sakit), 'A' (Alpa)
    notes: Optional[str] = None

class SaveRoomAttendanceRequest(BaseModel):
    exam_date: str
    session_name: str
    room_name: str
    subject_name: Optional[str] = None
    attendances: List[RoomAttendanceItem]

class SaveRoomBeritaAcaraRequest(BaseModel):
    exam_date: str
    session_name: str
    room_name: str
    subject_name: Optional[str] = None
    total_registered: int = 0
    total_present: int = 0
    total_absent: int = 0
    absent_students: Optional[str] = None
    supervisor1_name: Optional[str] = None
    supervisor2_name: Optional[str] = None
    proctor_name: Optional[str] = None
    notes: Optional[str] = None


@router.get("/my-supervisor-status")
def get_my_supervisor_status(current_user: dict = Depends(get_current_user)):
    """
    Cek apakah user yang login memiliki penugasan sebagai Pengawas Ruangan atau Pengawas Cadangan.
    Digunakan oleh Sidebar untuk menentukan apakah menu Pengawas Ruangan harus ditampilkan atau disembunyikan.
    """
    db = get_db()
    cursor = db.cursor()

    role = (current_user.get("role") or "").lower()
    is_admin = role in ("admin", "superadmin", "administrator", "staff")
    target_name = (current_user.get("name") or "").strip()

    # Cek apakah ada paket ujian SAS/sekolah yang sedang aktif
    cursor.execute("SELECT COUNT(*) FROM cbt_exams WHERE exam_type = 'sas' AND status = 'active'")
    row_active_sas = cursor.fetchone()
    active_sas_count = row_active_sas[0] if row_active_sas else 0
    is_exam_completed = (active_sas_count == 0)

    # Jika seluruh ujian sekolah SAS telah diselesaikan/ditutup oleh Admin (atau belum ada ujian aktif),
    # maka menu Jadwal Jaga Saya di role guru otomatis disembunyikan (has_duty = False)!
    if not is_admin and active_sas_count == 0:
        db.close()
        return {
            "success": True,
            "has_duty": False,
            "is_admin": False,
            "total_duties": 0,
            "room_duties_count": 0,
            "backup_duties_count": 0,
            "duties": [],
            "is_exam_completed": True,
            "message": "Seluruh pelaksanaan ujian sekolah telah selesai. Menunggu paket ujian selanjutnya."
        }

    # Ambil data profil dari master guru jika ada
    cursor.execute("""
        SELECT name FROM cbt_synced_teachers
        WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s))
           OR LOWER(TRIM(name)) LIKE LOWER(TRIM(%s))
        LIMIT 1
    """, (target_name, f"%{target_name}%"))
    row_t = cursor.fetchone()
    official_name = (row_t["name"] if row_t else target_name).strip()

    # Master Ruangan & Sesi
    cursor.execute("SELECT name, capacity, location FROM cbt_rooms")
    rooms_map = {r["name"]: dict(r) for r in cursor.fetchall()}

    cursor.execute("SELECT session_name, start_time, end_time FROM cbt_sessions")
    sessions_map = {s["session_name"]: dict(s) for s in cursor.fetchall()}

    # Jika admin, admin punya akses penuh ke semua penugasan ruangan
    if is_admin:
        cursor.execute("""
            SELECT id, exam_date, room_name, session_name,
                   supervisor1_name, supervisor2_name, supervisor3_name,
                   proctor_name, notes
            FROM cbt_supervisor_assignments
            ORDER BY exam_date ASC, session_name ASC, room_name ASC
        """)
        all_assignments = [dict(r) for r in cursor.fetchall()]

        duties = []
        for a in all_assignments:
            s_info = sessions_map.get(a.get("session_name"), {})
            r_info = rooms_map.get(a.get("room_name"), {})
            time_range = f"{s_info.get('start_time', '')} - {s_info.get('end_time', '')}".strip(" -")
            duties.append({
                "id": a["id"],
                "type": "room",
                "exam_date": a["exam_date"],
                "session_name": a["session_name"],
                "session_time": time_range,
                "room_name": a["room_name"],
                "room_location": r_info.get("location") or "Gedung Sekolah",
                "room_capacity": r_info.get("capacity") or 36,
                "role_label": "Pengawas Ruangan (Mode Admin)",
                "supervisor1_name": a.get("supervisor1_name"),
                "supervisor2_name": a.get("supervisor2_name"),
                "supervisor3_name": a.get("supervisor3_name"),
                "proctor_name": a.get("proctor_name"),
                "notes": a.get("notes")
            })

        db.close()
        return {
            "success": True,
            "has_duty": len(duties) > 0,
            "is_admin": True,
            "total_duties": len(duties),
            "room_duties_count": len(duties),
            "backup_duties_count": 0,
            "duties": duties,
            "is_exam_completed": is_exam_completed
        }

    # Untuk Guru: Ambil jadwal penugasan ruang menggunakan pencocokan cerdas
    matched_names = get_teacher_matched_names(current_user, cursor)
    col_checks = []
    col_params = []
    for n in matched_names:
        for col in ["supervisor1_name", "supervisor2_name", "supervisor3_name", "proctor_name"]:
            col_checks.append(f"""
                ({col} IS NOT NULL AND TRIM({col}) != '' AND (
                    LOWER(TRIM({col})) = LOWER(TRIM(%s))
                    OR LOWER(TRIM(%s)) LIKE CONCAT('%%', LOWER(TRIM({col})), '%%')
                    OR LOWER(TRIM({col})) LIKE CONCAT('%%', LOWER(TRIM(%s)), '%%')
                ))
            """)
            col_params.extend([n, n, n])
    where_assign = " OR ".join(col_checks) if col_checks else "1=0"
    cursor.execute(f"""
        SELECT id, exam_date, room_name, session_name,
               supervisor1_name, supervisor2_name, supervisor3_name,
               proctor_name, notes
        FROM cbt_supervisor_assignments
        WHERE {where_assign}
        ORDER BY exam_date ASC, session_name ASC, room_name ASC
    """, tuple(col_params))
    raw_assignments = [dict(r) for r in cursor.fetchall()]

    # Jadwal pengawas cadangan
    back_checks = []
    back_params = []
    for n in matched_names:
        back_checks.append("""
            (teacher_name IS NOT NULL AND TRIM(teacher_name) != '' AND (
                LOWER(TRIM(teacher_name)) = LOWER(TRIM(%s))
                OR LOWER(TRIM(%s)) LIKE CONCAT('%%', LOWER(TRIM(teacher_name)), '%%')
                OR LOWER(TRIM(teacher_name)) LIKE CONCAT('%%', LOWER(TRIM(%s)), '%%')
            ))
        """)
        back_params.extend([n, n, n])
    where_back = " OR ".join(back_checks) if back_checks else "1=0"
    cursor.execute(f"""
        SELECT id, exam_date, session_name, teacher_name, order_num, notes
        FROM cbt_backup_supervisors
        WHERE {where_back}
        ORDER BY exam_date ASC, session_name ASC, order_num ASC
    """, tuple(back_params))
    raw_backups = [dict(r) for r in cursor.fetchall()]

    duties = []

    for a in raw_assignments:
        s1 = (a.get("supervisor1_name") or "").strip()
        s2 = (a.get("supervisor2_name") or "").strip()
        s3 = (a.get("supervisor3_name") or "").strip()
        pr = (a.get("proctor_name") or "").strip()

        role_label = "Pengawas Ruangan"
        partners = []
        is_p1 = any(is_name_match(n, s1) for n in matched_names)
        is_p2 = any(is_name_match(n, s2) for n in matched_names)
        is_p3 = any(is_name_match(n, s3) for n in matched_names)
        is_pr = any(is_name_match(n, pr) for n in matched_names)
        if is_p1:
            role_label = "Pengawas 1 (Utama)"
            if s2 and s2 != "-": partners.append(s2)
            if s3 and s3 != "-": partners.append(s3)
        elif is_p2:
            role_label = "Pengawas 2"
            if s1 and s1 != "-": partners.append(s1)
            if s3 and s3 != "-": partners.append(s3)
        elif is_p3:
            role_label = "Pengawas 3"
            if s1 and s1 != "-": partners.append(s1)
            if s2 and s2 != "-": partners.append(s2)
        elif is_pr:
            role_label = "Proktor Ruangan"

        r_info = rooms_map.get(a.get("room_name"), {})
        s_info = sessions_map.get(a.get("session_name"), {})
        time_range = f"{s_info.get('start_time', '')} - {s_info.get('end_time', '')}".strip(" -")

        duties.append({
            "id": a["id"],
            "type": "room",
            "exam_date": a["exam_date"],
            "session_name": a["session_name"],
            "session_time": time_range,
            "room_name": a["room_name"],
            "room_location": r_info.get("location") or "Gedung Sekolah",
            "room_capacity": r_info.get("capacity") or 36,
            "role_label": role_label,
            "partners": partners,
            "supervisor1_name": s1,
            "supervisor2_name": s2,
            "supervisor3_name": s3,
            "proctor_name": pr,
            "notes": a.get("notes")
        })

    for b in raw_backups:
        s_info = sessions_map.get(b.get("session_name"), {})
        time_range = f"{s_info.get('start_time', '')} - {s_info.get('end_time', '')}".strip(" -")
        duties.append({
            "id": b["id"],
            "type": "backup",
            "exam_date": b["exam_date"],
            "session_name": b["session_name"],
            "session_time": time_range,
            "room_name": "Ruang Panitia",
            "room_location": "Sekretariat Panitia Ujian / Ruang Piket",
            "room_capacity": 0,
            "role_label": f"Pengawas Cadangan (Ke-{b.get('order_num', 1)})",
            "partners": [],
            "supervisor1_name": b.get("teacher_name"),
            "supervisor2_name": None,
            "supervisor3_name": None,
            "proctor_name": None,
            "notes": b.get("notes") or "Standby di Ruang Panitia CBT"
        })

    db.close()

    total_duties = len(duties)
    return {
        "success": True,
        "has_duty": total_duties > 0,
        "is_admin": False,
        "total_duties": total_duties,
        "room_duties_count": len(raw_assignments),
        "backup_duties_count": len(raw_backups),
        "duties": duties
    }


@router.get("/room-proctoring")
def get_room_proctoring_data(
    exam_date: Optional[str] = None,
    session_name: Optional[str] = None,
    room_name: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Mengambil data lengkap proktoring untuk ruangan dan sesi tertentu:
    - Informasi ruangan & penugasan pengawas
    - Mata pelajaran yang sedang diujikan
    - Daftar peserta teralokasi dengan status live (sedang ujian, terkunci, selesai)
    - Presensi / Kehadiran siswa
    - Berita Acara Pelaksanaan
    """
    db = get_db()
    cursor = db.cursor()

    role = (current_user.get("role") or "").lower()
    is_admin = role in ("admin", "superadmin", "administrator", "staff")
    target_name = (current_user.get("name") or "").strip()

    # Cek apakah ada paket ujian SAS/sekolah yang sedang aktif
    cursor.execute("SELECT COUNT(*) FROM cbt_exams WHERE exam_type = 'sas' AND status = 'active'")
    row_active_sas = cursor.fetchone()
    active_sas_count = row_active_sas[0] if row_active_sas else 0
    is_exam_completed = (active_sas_count == 0)

    matched_names = get_teacher_matched_names(current_user, cursor)

    # 1. Ambil daftar tugas yang dimiliki user (atau seluruh penugasan jika admin)
    if is_admin:
        cursor.execute("""
            SELECT id, exam_date, room_name, session_name,
                   supervisor1_name, supervisor2_name, supervisor3_name,
                   proctor_name, notes
            FROM cbt_supervisor_assignments
            ORDER BY exam_date ASC, session_name ASC, room_name ASC
        """)
    else:
        col_checks = []
        col_params = []
        for n in matched_names:
            for col in ["supervisor1_name", "supervisor2_name", "supervisor3_name", "proctor_name"]:
                col_checks.append(f"""
                    ({col} IS NOT NULL AND TRIM({col}) != '' AND (
                        LOWER(TRIM({col})) = LOWER(TRIM(%s))
                        OR LOWER(TRIM(%s)) LIKE CONCAT('%%', LOWER(TRIM({col})), '%%')
                        OR LOWER(TRIM({col})) LIKE CONCAT('%%', LOWER(TRIM(%s)), '%%')
                    ))
                """)
                col_params.extend([n, n, n])
        where_assign = " OR ".join(col_checks) if col_checks else "1=0"
        cursor.execute(f"""
            SELECT id, exam_date, room_name, session_name,
                   supervisor1_name, supervisor2_name, supervisor3_name,
                   proctor_name, notes
            FROM cbt_supervisor_assignments
            WHERE {where_assign}
            ORDER BY exam_date ASC, session_name ASC, room_name ASC
        """, tuple(col_params))

    available_duties = [dict(r) for r in cursor.fetchall()]

    # Jika guru tidak punya tugas dan bukan admin
    if not is_admin and not available_duties:
        db.close()
        raise HTTPException(
            status_code=403, 
            detail="Anda belum memiliki penugasan pengawas ruangan. Menu ini hanya untuk guru yang bertugas mengawas."
        )

    # Tentukan penugasan aktif
    active_assignment = None

    if is_admin:
        # LOGIKA ADMIN: Admin memiliki kewenangan penuh memilih tanggal, ruangan, dan sesi manapun dari paket ujian
        # 1. Tentukan tanggal ujian
        cur_exam_date = exam_date
        if not cur_exam_date:
            today_str = datetime.now().strftime("%Y-%m-%d")
            match_today = next((d["exam_date"] for d in available_duties if d["exam_date"] == today_str), None)
            cur_exam_date = match_today or (available_duties[0]["exam_date"] if available_duties else today_str)

        # 2. Tentukan ruangan ujian
        cur_room = room_name
        if not cur_room:
            match_room_duty = next((d["room_name"] for d in available_duties if d["exam_date"] == cur_exam_date), None)
            if match_room_duty:
                cur_room = match_room_duty
            else:
                cursor.execute("SELECT name FROM cbt_rooms ORDER BY name ASC LIMIT 1")
                r_row = cursor.fetchone()
                cur_room = r_row["name"] if r_row else "G1"

        # 3. Tentukan sesi ujian
        cur_session = session_name
        if not cur_session:
            match_sess_duty = next((d["session_name"] for d in available_duties if d["exam_date"] == cur_exam_date and d["room_name"] == cur_room), None)
            if match_sess_duty:
                cur_session = match_sess_duty
            else:
                cursor.execute("SELECT session_name FROM cbt_sessions ORDER BY start_time ASC LIMIT 1")
                s_row = cursor.fetchone()
                cur_session = s_row["session_name"] if s_row else "Sesi 1"

        # Cari penugasan pengawas untuk kombinasi spesifik yang dipilih admin
        cursor.execute("""
            SELECT id, exam_date, room_name, session_name,
                   supervisor1_name, supervisor2_name, supervisor3_name,
                   proctor_name, notes
            FROM cbt_supervisor_assignments
            WHERE exam_date = %s AND session_name = %s AND room_name = %s
            LIMIT 1
        """, (cur_exam_date, cur_session, cur_room))
        row_ass = cursor.fetchone()
        if row_ass:
            active_assignment = dict(row_ass)
        else:
            active_assignment = {
                "id": None,
                "exam_date": cur_exam_date,
                "session_name": cur_session,
                "room_name": cur_room,
                "supervisor1_name": "-",
                "supervisor2_name": "-",
                "supervisor3_name": "-",
                "proctor_name": "Panitia CBT",
                "notes": "Pengawasan Terpusat (Admin)"
            }
    else:
        # LOGIKA GURU PENGAWAS: Hanya dapat membuka tugas yang ditugaskan kepada guru bersangkutan
        if room_name or session_name or exam_date:
            for d in available_duties:
                match_room = (not room_name) or (d["room_name"] == room_name)
                match_session = (not session_name) or (d["session_name"] == session_name)
                match_date = (not exam_date) or (d["exam_date"] == exam_date)
                if match_room and match_session and match_date:
                    active_assignment = d
                    break
        if not active_assignment and available_duties:
            active_assignment = available_duties[0]

        if not active_assignment:
            db.close()
            raise HTTPException(status_code=403, detail="Anda belum memiliki penugasan pengawas ruangan pada sesi ini.")

        cur_exam_date = active_assignment["exam_date"]
        cur_session = active_assignment["session_name"]
        cur_room = active_assignment["room_name"]

    # 2. Detail Ruangan & Sesi
    cursor.execute("SELECT id, name, capacity, location FROM cbt_rooms WHERE name = %s LIMIT 1", (cur_room,))
    room_detail = cursor.fetchone()
    room_info = dict(room_detail) if room_detail else {"name": cur_room, "capacity": 36, "location": "Gedung Sekolah"}

    cursor.execute("SELECT id, session_name, start_time, end_time FROM cbt_sessions WHERE session_name = %s LIMIT 1", (cur_session,))
    session_detail = cursor.fetchone()
    session_info = dict(session_detail) if session_detail else {"session_name": cur_session, "start_time": "", "end_time": ""}
    session_time = f"{session_info.get('start_time', '')} - {session_info.get('end_time', '')}".strip(" -")

    # 3. Ambil Rombel / Kelas yang dialokasikan di Ruangan ini pada Sesi ini
    cursor.execute("""
        SELECT DISTINCT class_name 
        FROM cbt_student_allocations 
        WHERE room_name = %s 
          AND (session_name = %s OR session_name = 'Semua Sesi' OR session_name IS NULL OR session_name = '')
    """, (cur_room, cur_session))
    alloc_classes = [r["class_name"] for r in cursor.fetchall() if r.get("class_name")]
    if not alloc_classes:
        cursor.execute("SELECT DISTINCT class_name FROM cbt_student_allocations WHERE room_name = %s", (cur_room,))
        alloc_classes = [r["class_name"] for r in cursor.fetchall() if r.get("class_name")]

    # Ambil mata pelajaran pada tanggal ini dari paket ujian yang ada
    cursor.execute("""
        SELECT s.id, s.exam_id, s.subject_name, s.grade, s.start_time, s.end_time,
               s.duration_minutes, s.session_status, s.session_started_at, s.target_classes
        FROM cbt_exam_subjects s
        JOIN cbt_exams e ON s.exam_id = e.id
        WHERE s.exam_date = %s
          AND e.status != 'draft'
        ORDER BY s.start_time ASC, s.id ASC
    """, (cur_exam_date,))
    all_candidate_subs = [dict(r) for r in cursor.fetchall()]

    if not all_candidate_subs:
        # Fallback jika exam_date kosong atau belum diset
        cursor.execute("""
            SELECT s.id, s.exam_id, s.subject_name, s.grade, s.start_time, s.end_time,
                   s.duration_minutes, s.session_status, s.session_started_at, s.target_classes
            FROM cbt_exam_subjects s
            JOIN cbt_exams e ON s.exam_id = e.id
            WHERE e.status = 'active'
            ORDER BY s.start_time ASC, s.id ASC
        """)
        all_candidate_subs = [dict(r) for r in cursor.fetchall()]

    if not all_candidate_subs:
        # Fallback ke cbt_sas_schedules jika belum ada di cbt_exam_subjects
        cursor.execute("""
            SELECT DISTINCT id, subject_name, start_time, end_time, duration_minutes
            FROM cbt_sas_schedules
            WHERE exam_date = %s
            ORDER BY period_number ASC
        """, (cur_exam_date,))
        all_candidate_subs = [dict(r) for r in cursor.fetchall()]

    # Saring mata pelajaran yang sesuai dengan SESI dan RUANGAN (kelas siswa di ruangan ini)
    s_start = session_info.get("start_time")
    s_end = session_info.get("end_time")
    matched_subjects = []

    for sub in all_candidate_subs:
        # 1. Kecocokan Waktu Sesi
        time_match = False
        if s_start and sub.get("start_time"):
            time_match = (sub["start_time"] == s_start)
        elif not s_start and not sub.get("start_time"):
            time_match = True
        elif not s_start:
            time_match = True

        # 2. Kecocokan Kelas / Sasaran
        try:
            t_cls = json.loads(sub.get("target_classes") or "[]")
        except Exception:
            t_cls = []

        class_match = False
        if not t_cls or "all" in t_cls:
            class_match = True
        elif alloc_classes:
            class_match = any(c in t_cls for c in alloc_classes)
        else:
            class_match = True

        if time_match and class_match:
            matched_subjects.append(sub)

    # Jika pencocokan waktu sesi tidak menghasilkan mapel, coba fallback berdasarkan urutan sesi
    if not matched_subjects and cur_session and all_candidate_subs:
        m = re.search(r'\d+', cur_session)
        if m:
            idx = int(m.group(0)) - 1
            if 0 <= idx < len(all_candidate_subs):
                matched_subjects = [all_candidate_subs[idx]]

    if not matched_subjects and all_candidate_subs:
        matched_subjects = all_candidate_subs

    subjects = matched_subjects
    target_subject = subjects[0] if subjects else None
    target_sub_id = target_subject["id"] if target_subject else None
    target_sub_name = target_subject["subject_name"] if target_subject else None
    sub_ids = [s["id"] for s in subjects if s.get("id")]
    sub_ids_param = sub_ids if sub_ids else [-1]

    # 4. Ambil Siswa yang Teralokasi di Ruangan & Sesi ini beserta Mapel & Sesi Pengerjaannya
    cursor.execute("""
        SELECT 
            a.id as allocation_id,
            a.student_id,
            a.student_name,
            a.class_name,
            a.nisn,
            a.room_name,
            a.session_name,
            a.seat_number,
            att.status as attendance_status,
            att.notes as attendance_notes,
            att.updated_at as attendance_updated_at,
            es.id as session_id,
            es.exam_id,
            es.subject_id,
            es.subject_name,
            es.status as exam_status,
            es.lock_reason,
            es.lock_count,
            es.unlock_code,
            es.total_answered,
            es.score,
            es.device_id,
            es.device_info,
            es.browser_info,
            es.connection_quality,
            es.ping_ms,
            es.last_heartbeat,
            es.ip_address,
            es.start_time as exam_start_time,
            es.submitted_at
        FROM cbt_student_allocations a
        LEFT JOIN cbt_room_attendance att 
            ON att.exam_date = %s 
           AND att.session_name = %s 
           AND att.room_name = %s 
           AND att.student_id = a.student_id
        LEFT JOIN LATERAL (
            SELECT s.id, s.exam_id, s.subject_id, s.status, s.lock_reason, s.lock_count, s.unlock_code, 
                   s.total_answered, s.score, s.device_id, s.device_info, s.browser_info, s.connection_quality, 
                   s.ping_ms, s.last_heartbeat, s.ip_address, s.start_time, s.submitted_at,
                   sub.subject_name
            FROM cbt_exam_sessions s
            LEFT JOIN cbt_exam_subjects sub ON s.subject_id = sub.id
            WHERE s.student_id = a.student_id
              AND (
                  (s.subject_id = ANY(%s))
                  OR (s.status IN ('in_progress', 'locked') AND sub.exam_date = %s)
              )
            ORDER BY 
                CASE WHEN s.subject_id = ANY(%s) THEN 0 ELSE 1 END,
                CASE WHEN s.status = 'in_progress' THEN 0 WHEN s.status = 'locked' THEN 1 ELSE 2 END,
                s.id DESC
            LIMIT 1
        ) es ON true
        WHERE a.room_name = %s 
          AND (
              a.session_name = %s 
              OR a.session_name = 'Semua Sesi'
              OR a.session_name IS NULL 
              OR a.session_name = ''
              OR NOT EXISTS (
                  SELECT 1 FROM cbt_student_allocations a2 
                  WHERE a2.room_name = a.room_name AND a2.session_name = %s
              )
          )
        ORDER BY a.seat_number ASC, a.class_name ASC, a.student_name ASC
    """, (
        cur_exam_date, cur_session, cur_room,
        sub_ids_param, cur_exam_date, sub_ids_param,
        cur_room, cur_session, cur_session
    ))
    
    raw_students = cursor.fetchall()
    students = []
    
    total_present = 0
    total_absent = 0
    in_progress_count = 0
    locked_count = 0
    submitted_count = 0
    not_started_count = 0
    suspicious_count = 0

    for r in raw_students:
        s = dict(r)
        # Default attendance status is 'H' (Hadir) jika belum ada di database
        att_status = s.get("attendance_status") or "H"
        s["attendance_status"] = att_status
        s["attendance_notes"] = s.get("attendance_notes") or ""

        # Tentukan Mapel Ujian untuk siswa ini
        st_sub_name = s.get("subject_name")
        st_sub_id = s.get("subject_id")

        if not st_sub_name:
            # Mapel yang dijadwalkan untuk siswa ini berdasarkan kelasnya di ruangan ini
            stu_class = s.get("class_name")
            matched_for_student = None
            if stu_class and subjects:
                for sub in subjects:
                    try:
                        tc = json.loads(sub.get("target_classes") or "[]")
                    except Exception:
                        tc = []
                    if not tc or "all" in tc or stu_class in tc:
                        matched_for_student = sub
                        break
            if not matched_for_student and subjects:
                matched_for_student = subjects[0]

            st_sub_id = matched_for_student.get("id") if matched_for_student else None
            st_sub_name = matched_for_student.get("subject_name") if matched_for_student else "Mata Pelajaran"

        s["subject_id"] = st_sub_id
        s["subject_name"] = st_sub_name

        # Live exam status
        ex_status = s.get("exam_status") or "not_started"
        s["exam_status"] = ex_status
        s["lock_reason"] = s.get("lock_reason") or ""
        lock_cnt = s.get("lock_count") or 0
        s["lock_count"] = lock_cnt
        s["total_answered"] = s.get("total_answered") or 0

        # Cek indikasi kecurangan:
        # Siswa dicurigai curang jika sedang terkunci karena melanggar atau pernah terkunci (lock_count > 0)
        is_suspicious = bool((ex_status == "locked") or (lock_cnt > 0))
        s["is_suspicious"] = is_suspicious
        if is_suspicious:
            suspicious_count += 1

        # Perangkat & Browser yang digunakan (Hanya jika siswa sudah mulai ujian / memiliki sesi aktif)
        if s.get("session_id") and ex_status != "not_started":
            s["device_info"] = s.get("device_info") or (s.get("device_id") and "Laptop/PC (Windows)") or None
            s["browser_info"] = s.get("browser_info") or None
            s["ip_address"] = s.get("ip_address") or None

            # Kualitas Koneksi & Ping
            ping_val = s.get("ping_ms") if s.get("ping_ms") is not None else 25
            s["ping_ms"] = ping_val

            # Cek apakah heartbeat terputus
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

        # Jika siswa terkunci, pastikan ada kode buka kunci 6 digit yang dapat diberikan pengawas
        if ex_status == "locked":
            cur_code = s.get("unlock_code")
            if not cur_code:
                cur_code = str(random.randint(100000, 999999))
                if s.get("session_id"):
                    cursor.execute("UPDATE cbt_exam_sessions SET unlock_code = %s WHERE id = %s", (cur_code, s["session_id"]))
            s["unlock_code"] = cur_code
        else:
            s["unlock_code"] = None

        # Hitung statistik
        if att_status == "H":
            total_present += 1
        else:
            total_absent += 1

        if ex_status == "in_progress":
            in_progress_count += 1
        elif ex_status == "locked":
            locked_count += 1
        elif ex_status == "submitted":
            submitted_count += 1
        else:
            not_started_count += 1

        students.append(s)

    # 4b. Ambil Token Ujian SAS (Sekolah) Aktif dari Admin (cbt_exams)
    cursor.execute("""
        SELECT e.id, e.title, e.token, e.is_token_active, e.token_updated_at, 
               e.token_refresh_interval, e.active_subject_id, s.subject_name as active_subject_name
        FROM cbt_exams e
        LEFT JOIN cbt_exam_subjects s ON s.id = e.active_subject_id
        WHERE e.exam_type = 'sas' AND e.is_token_active = 1
        ORDER BY e.id DESC
        LIMIT 1
    """)
    active_exam_row = cursor.fetchone()
    if not active_exam_row:
        cursor.execute("""
            SELECT e.id, e.title, e.token, e.is_token_active, e.token_updated_at, 
                   e.token_refresh_interval, e.active_subject_id, s.subject_name as active_subject_name
            FROM cbt_exams e
            LEFT JOIN cbt_exam_subjects s ON s.id = e.active_subject_id
            WHERE e.exam_type = 'sas' AND e.token IS NOT NULL AND e.token != ''
            ORDER BY e.id DESC
            LIMIT 1
        """)
        active_exam_row = cursor.fetchone()

    active_token_info = {
        "token": (active_exam_row["token"] if active_exam_row else "-") or "-",
        "is_active": bool(active_exam_row and active_exam_row.get("is_token_active") == 1),
        "exam_title": (active_exam_row.get("title") if active_exam_row else "Ujian CBT") or "Ujian CBT",
        "active_subject": target_sub_name or (active_exam_row.get("active_subject_name") if active_exam_row else None) or (subjects[0]["subject_name"] if subjects else "Mata Pelajaran"),
        "token_refresh_interval": (active_exam_row.get("token_refresh_interval") if active_exam_row else 15) or 15
    }

    # 5. Berita Acara yang tersimpan
    cursor.execute("""
        SELECT * FROM cbt_room_berita_acara
        WHERE exam_date = %s AND session_name = %s AND room_name = %s
        LIMIT 1
    """, (cur_exam_date, cur_session, cur_room))
    ba_row = cursor.fetchone()
    berita_acara = dict(ba_row) if ba_row else None

    # Jika berita acara belum ada, siapkan data default
    if not berita_acara:
        absent_names = [f"{st['student_name']} ({st['attendance_status']})" for st in students if st['attendance_status'] != "H"]
        berita_acara = {
            "id": None,
            "exam_date": cur_exam_date,
            "session_name": cur_session,
            "room_name": cur_room,
            "subject_name": target_sub_name or (subjects[0]["subject_name"] if subjects else "Mata Pelajaran"),
            "total_registered": len(students),
            "total_present": total_present,
            "total_absent": total_absent,
            "absent_students": ", ".join(absent_names) if absent_names else "-",
            "supervisor1_name": active_assignment.get("supervisor1_name") or "",
            "supervisor2_name": active_assignment.get("supervisor2_name") or "",
            "proctor_name": active_assignment.get("proctor_name") or "",
            "notes": "Pelaksanaan ujian di ruangan berlangsung tertib, aman, dan lancar.",
            "submitted_by": None,
            "submitted_at": None
        }

    # 6. Profil Sekolah untuk format cetak
    cursor.execute("SELECT * FROM cbt_synced_school_profile LIMIT 1")
    sp = cursor.fetchone()
    school_profile = dict(sp) if sp else {
        "school_name": "SMA Negeri 1",
        "address": "Jl. Pendidikan No. 1",
        "headmaster_name": "Kepala Sekolah",
        "headmaster_nip": "-"
    }

    # 7. Ambil Seluruh Daftar Master Ruangan, Sesi, dan Tanggal Ujian dari Paket Ujian Aktif
    cursor.execute("""
        SELECT DISTINCT name FROM (
            SELECT name FROM cbt_rooms WHERE name IS NOT NULL AND name != ''
            UNION
            SELECT room_name as name FROM cbt_student_allocations WHERE room_name IS NOT NULL AND room_name != ''
            UNION
            SELECT room_name as name FROM cbt_supervisor_assignments WHERE room_name IS NOT NULL AND room_name != ''
        ) t ORDER BY name ASC
    """)
    all_rooms = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT DISTINCT session_name FROM (
            SELECT session_name FROM cbt_sessions WHERE session_name IS NOT NULL AND session_name != ''
            UNION
            SELECT session_name FROM cbt_student_allocations WHERE session_name IS NOT NULL AND session_name != ''
            UNION
            SELECT session_name FROM cbt_supervisor_assignments WHERE session_name IS NOT NULL AND session_name != ''
        ) t ORDER BY session_name ASC
    """)
    all_sessions = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT DISTINCT exam_date FROM (
            SELECT s.exam_date 
            FROM cbt_exam_subjects s
            JOIN cbt_exams e ON s.exam_id = e.id
            WHERE e.status = 'active' AND s.exam_date IS NOT NULL AND s.exam_date != ''
            UNION
            SELECT exam_date FROM cbt_supervisor_assignments WHERE exam_date IS NOT NULL AND exam_date != ''
            UNION
            SELECT exam_date FROM cbt_sas_schedules WHERE exam_date IS NOT NULL AND exam_date != ''
        ) t
        ORDER BY exam_date ASC
    """)
    all_dates = [r["exam_date"] for r in cursor.fetchall() if r.get("exam_date")]

    db.close()

    target_status = (target_subject.get("session_status") or "idle").lower() if target_subject else "idle"
    duty_info = {
        "id": active_assignment.get("id"),
        "exam_date": cur_exam_date,
        "session_name": cur_session,
        "session_time": session_time,
        "room_name": cur_room,
        "room_location": room_info.get("location") or "Gedung Sekolah",
        "room_capacity": room_info.get("capacity") or 36,
        "supervisor1_name": active_assignment.get("supervisor1_name"),
        "supervisor2_name": active_assignment.get("supervisor2_name"),
        "supervisor3_name": active_assignment.get("supervisor3_name"),
        "proctor_name": active_assignment.get("proctor_name"),
        "notes": active_assignment.get("notes"),
        "target_subject": target_subject,
        "session_status": target_status,
        "is_session_active": target_status == "active"
    }

    return {
        "success": True,
        "is_exam_completed": is_exam_completed,
        "duty": duty_info,
        "active_token": active_token_info,
        "available_duties": available_duties,
        "rooms": all_rooms,
        "sessions": all_sessions,
        "dates": all_dates,
        "subjects": subjects,
        "students": students,
        "berita_acara": berita_acara,
        "school_profile": school_profile,
        "stats": {
            "total_registered": len(students),
            "total_present": total_present,
            "total_absent": total_absent,
            "in_progress": in_progress_count,
            "locked": locked_count,
            "submitted": submitted_count,
            "not_started": not_started_count,
            "suspicious_count": suspicious_count
        }
    }


@router.post("/room-proctoring/unlock")
def unlock_room_students(req: RoomProctorUnlockRequest, current_user: dict = Depends(get_current_user)):
    """
    Buka kunci siswa di ruangan (baik individual maupun massal).
    Siswa dapat langsung melanjutkan pengerjaan soal.
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

    cursor.execute("""
        UPDATE cbt_exam_sessions
        SET status = 'in_progress', lock_reason = NULL, unlock_code = NULL
        WHERE id = ANY(%s) AND status = 'locked'
    """, (ids_to_unlock,))

    affected = cursor.rowcount
    db.commit()
    db.close()

    return {
        "success": True,
        "message": f"Berhasil membuka kunci {affected} siswa. Siswa dapat melanjutkan pengerjaan.",
        "unlocked": affected
    }


@router.post("/room-proctoring/reset-login")
def reset_student_login(req: RoomProctorResetLoginRequest, current_user: dict = Depends(get_current_user)):
    """
    Reset perangkat / login siswa jika siswa berganti komputer / HP atau koneksi terputus.
    Menghapus device_id dan ip_address serta merestore status jika terkunci.
    """
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        UPDATE cbt_exam_sessions
        SET device_id = NULL,
            ip_address = NULL,
            lock_reason = NULL,
            unlock_code = NULL,
            status = CASE WHEN status = 'locked' THEN 'in_progress' ELSE status END
        WHERE id = %s
    """, (req.session_id,))

    affected = cursor.rowcount
    db.commit()
    db.close()

    if affected == 0:
        raise HTTPException(status_code=404, detail="Sesi ujian siswa tidak ditemukan.")

    return {
        "success": True,
        "message": "Sesi login siswa berhasil direset. Siswa dapat login kembali di perangkat baru."
    }


@router.post("/room-proctoring/submit-student")
def submit_student_exam(req: RoomProctorSubmitRequest, current_user: dict = Depends(get_current_user)):
    """
    Pengawas mengumpulkan / menyelesaikan ujian siswa secara paksa (force submit) dari ruangan pengawas.
    """
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        UPDATE cbt_exam_sessions
        SET status = 'submitted', submitted_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """, (req.session_id,))

    affected = cursor.rowcount
    db.commit()
    db.close()

    if affected == 0:
        raise HTTPException(status_code=404, detail="Sesi ujian siswa tidak ditemukan.")

    return {
        "success": True,
        "message": "Ujian siswa berhasil diselesaikan dan dikumpulkan ke sistem."
    }


@router.post("/room-attendance")
def save_room_attendance(req: SaveRoomAttendanceRequest, current_user: dict = Depends(get_current_user)):
    """
    Menyimpan daftar hadir peserta ujian di ruangan dan sesi tertentu.
    Juga otomatis memperbarui ringkasan kehadiran di berita acara ruangan.
    """
    db = get_db()
    cursor = db.cursor()

    user_name = (current_user.get("name") or "Pengawas").strip()
    absent_list = []
    total_present = 0
    total_absent = 0

    for item in req.attendances:
        status_val = (item.status or "H").upper()
        if status_val not in ("H", "I", "S", "A"):
            status_val = "H"

        if status_val == "H":
            total_present += 1
        else:
            total_absent += 1
            label = {"I": "Izin", "S": "Sakit", "A": "Alpa"}.get(status_val, status_val)
            absent_list.append(f"{item.student_name} ({label})")

        cursor.execute("""
            INSERT INTO cbt_room_attendance (
                exam_date, session_name, room_name, subject_name,
                student_id, student_name, class_name, nisn,
                status, notes, updated_by, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (exam_date, session_name, room_name, student_id)
            DO UPDATE SET
                status = EXCLUDED.status,
                notes = EXCLUDED.notes,
                subject_name = COALESCE(EXCLUDED.subject_name, cbt_room_attendance.subject_name),
                updated_by = EXCLUDED.updated_by,
                updated_at = CURRENT_TIMESTAMP
        """, (
            req.exam_date, req.session_name, req.room_name, req.subject_name,
            item.student_id, item.student_name, item.class_name, item.nisn,
            status_val, item.notes, user_name
        ))

    # Auto-update atau inisialisasi berita acara dengan data presensi terkini
    absent_str = ", ".join(absent_list) if absent_list else "-"
    cursor.execute("""
        INSERT INTO cbt_room_berita_acara (
            exam_date, session_name, room_name, subject_name,
            total_registered, total_present, total_absent, absent_students,
            submitted_by, submitted_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (exam_date, session_name, room_name)
        DO UPDATE SET
            total_registered = EXCLUDED.total_registered,
            total_present = EXCLUDED.total_present,
            total_absent = EXCLUDED.total_absent,
            absent_students = EXCLUDED.absent_students,
            subject_name = COALESCE(EXCLUDED.subject_name, cbt_room_berita_acara.subject_name)
    """, (
        req.exam_date, req.session_name, req.room_name, req.subject_name,
        len(req.attendances), total_present, total_absent, absent_str,
        user_name
    ))

    db.commit()
    db.close()

    return {
        "success": True,
        "message": f"Daftar hadir berhasil disimpan ({total_present} hadir, {total_absent} tidak hadir).",
        "total_present": total_present,
        "total_absent": total_absent
    }


@router.post("/room-berita-acara")
def save_room_berita_acara(req: SaveRoomBeritaAcaraRequest, current_user: dict = Depends(get_current_user)):
    """
    Menyimpan atau memperbarui Berita Acara Pelaksanaan Ujian di Ruangan.
    """
    db = get_db()
    cursor = db.cursor()

    user_name = (current_user.get("name") or "Pengawas").strip()

    cursor.execute("""
        INSERT INTO cbt_room_berita_acara (
            exam_date, session_name, room_name, subject_name,
            total_registered, total_present, total_absent, absent_students,
            supervisor1_name, supervisor2_name, proctor_name, notes,
            submitted_by, submitted_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (exam_date, session_name, room_name)
        DO UPDATE SET
            subject_name = EXCLUDED.subject_name,
            total_registered = EXCLUDED.total_registered,
            total_present = EXCLUDED.total_present,
            total_absent = EXCLUDED.total_absent,
            absent_students = EXCLUDED.absent_students,
            supervisor1_name = EXCLUDED.supervisor1_name,
            supervisor2_name = EXCLUDED.supervisor2_name,
            proctor_name = EXCLUDED.proctor_name,
            notes = EXCLUDED.notes,
            submitted_by = EXCLUDED.submitted_by,
            submitted_at = CURRENT_TIMESTAMP
    """, (
        req.exam_date, req.session_name, req.room_name, req.subject_name,
        req.total_registered, req.total_present, req.total_absent, req.absent_students,
        req.supervisor1_name, req.supervisor2_name, req.proctor_name, req.notes,
        user_name
    ))

    db.commit()
    db.close()

    return {
        "success": True,
        "message": "Berita acara ujian ruangan berhasil disimpan."
    }

