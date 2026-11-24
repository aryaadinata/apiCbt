import os
import re
import json
import uuid
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from pydantic import BaseModel
try:
    import docx
except ImportError:
    docx = None
from database import get_db
from auth import get_current_user

router = APIRouter(prefix="/api/cbt/banks", tags=["Question Banks"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

class QuestionOption(BaseModel):
    key: str
    text: str
    image_url: Optional[str] = None
    match: Optional[str] = None

class QuestionItem(BaseModel):
    question_number: Optional[int] = None
    question_type: str = "multiple_choice"
    content: str
    image_url: Optional[str] = None
    audio_url: Optional[str] = None
    points: float = 1.0
    options: Optional[List[QuestionOption]] = []
    correct_answer: Optional[str] = ""
    explanation: Optional[str] = None
    lock_order: Optional[int] = 0
    randomize_options_mode: Optional[str] = "default" # "default", "disabled", "enabled"
    difficulty: Optional[str] = "sedang" # "mudah", "sedang", "sukar", "hots"
    topic: Optional[str] = ""
    layout: Optional[str] = "vertical" # "vertical", "grid"
    is_required: Optional[int] = 0

class QuestionSettingsRequest(BaseModel):
    lock_order: Optional[int] = 0
    randomize_options_mode: Optional[str] = "default"
    difficulty: Optional[str] = "sedang"
    topic: Optional[str] = ""
    layout: Optional[str] = "vertical"
    is_required: Optional[int] = 0

class CreateBankRequest(BaseModel):
    title: str
    subject_name: str
    grade: int = 10
    teacher_id: Optional[int] = None
    teacher_name: Optional[str] = None
    questions: Optional[List[QuestionItem]] = []

class UpdateBankRequest(BaseModel):
    title: Optional[str] = None
    subject_name: Optional[str] = None
    grade: Optional[int] = None
    teacher_id: Optional[int] = None
    teacher_name: Optional[str] = None

class AssignBankTeacherRequest(BaseModel):
    teacher_id: Optional[int] = None
    teacher_name: str

class UpdateBankExamSettingsRequest(BaseModel):
    randomize_questions: bool = True
    randomize_options: bool = True
    show_score: bool = True
    show_explanation: bool = False
    duration_minutes: Optional[int] = 90
    passing_score: Optional[float] = 75.0
    max_violations: Optional[int] = 3

class TextParseRequest(BaseModel):
    raw_text: str

# -------------------------------------------------------------
# HELPER: PARSER TEKS / WORD CERDAS & RAMAH GURU
# -------------------------------------------------------------
def parse_raw_question_text(text: str) -> List[dict]:
    """
    Parser pintar untuk mengubah teks mentah dari Word atau copy-paste
    menjadi struktur soal terstandarisasi.
    Format yang didukung sangat fleksibel:
    1. Pertanyaan...
       A. Opsi 1
       B. Opsi 2
       *C. Opsi 3 (kunci)
       D. Opsi 4
       Kunci: C
    """
    lines = text.replace('\r\n', '\n').split('\n')
    questions = []
    current_q = None
    
    # Regex patterns
    q_start_pattern = re.compile(r'^\s*(\d+)[\.\)]\s*(.*)', re.IGNORECASE)
    opt_pattern = re.compile(r'^\s*(\*?)\s*([A-Ea-e])[\.\)]\s*(.*)')
    key_pattern = re.compile(r'^\s*(?:KUNCI|JAWABAN|KEY)\s*[:=]\s*([A-Ea-e])', re.IGNORECASE)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Cek apakah baris ini adalah nomor soal baru (misal: "1. Apa itu...")
        q_match = q_start_pattern.match(stripped)
        if q_match:
            if current_q:
                questions.append(current_q)
            q_num = int(q_match.group(1))
            q_content = q_match.group(2).strip()
            current_q = {
                "question_number": q_num,
                "question_type": "multiple_choice",
                "content": q_content,
                "image_url": None,
                "points": 1.0,
                "options": [],
                "correct_answer": "",
                "explanation": "",
                "has_warning": False,
                "warning_message": None
            }
            continue

        if not current_q:
            # Jika teks pembuka sebelum nomor 1, abaikan atau jadikan soal 1
            current_q = {
                "question_number": 1,
                "question_type": "multiple_choice",
                "content": stripped,
                "image_url": None,
                "points": 1.0,
                "options": [],
                "correct_answer": "",
                "explanation": "",
                "has_warning": False,
                "warning_message": None
            }
            continue

        # Cek apakah baris ini adalah kunci jawaban eksplisit (misal: "Kunci: B")
        key_match = key_pattern.match(stripped)
        if key_match:
            current_q["correct_answer"] = key_match.group(1).upper()
            continue

        # Cek apakah baris ini adalah pilihan A, B, C, D, E (misal: "A. Pilihan" atau "*C. Kunci")
        opt_match = opt_pattern.match(stripped)
        if opt_match:
            is_starred = bool(opt_match.group(1))
            opt_key = opt_match.group(2).upper()
            opt_text = opt_match.group(3).strip()
            
            # Jika ada tanda bintang atau kata (kunci) di teks opsi
            if is_starred or "(kunci)" in opt_text.lower() or "[kunci]" in opt_text.lower():
                current_q["correct_answer"] = opt_key
                opt_text = re.sub(r'\(kunci\)|\[kunci\]', '', opt_text, flags=re.IGNORECASE).strip()

            current_q["options"].append({
                "key": opt_key,
                "text": opt_text,
                "image_url": None
            })
            continue

        # Jika masih berupa lanjutan pertanyaan atau opsi
        if len(current_q["options"]) == 0:
            current_q["content"] += " " + stripped
        else:
            # Lanjutan dari opsi terakhir
            current_q["options"][-1]["text"] += " " + stripped

    if current_q:
        questions.append(current_q)

    # Validasi awal & beri tanda peringatan ramah bagi guru
    for idx, q in enumerate(questions, 1):
        q["question_number"] = idx
        if len(q["options"]) < 2:
            q["has_warning"] = True
            q["warning_message"] = "Pilihan ganda kurang lengkap (minimal 2 opsi A dan B)."
        elif not q["correct_answer"]:
            q["has_warning"] = True
            q["warning_message"] = "Kunci jawaban belum ditentukan."

    return questions

# -------------------------------------------------------------
# ENDPOINT: CRUD BANK SOAL
# -------------------------------------------------------------
@router.get("")
def list_question_banks(filter: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()

    user_role = (current_user.get("role") or "").lower()
    is_admin = "admin" in user_role or "staff" in user_role or "superadmin" in user_role

    # Jika guru meminta data miliknya (atau default guru jika tidak meminta filter='all')
    if filter == "my" or (not is_admin and filter != "all"):
        teacher_id = current_user.get("teacher_id") or current_user.get("id")
        teacher_name = (current_user.get("name") or "").strip()
        cursor.execute("""
            SELECT b.id, b.title, b.subject_name, b.grade, b.teacher_id, b.teacher_name, b.total_questions, b.created_at, b.updated_at,
                   b.origin, es.exam_id, e.title as exam_title, e.exam_type,
                   COALESCE(b.randomize_questions, 1) as randomize_questions,
                   COALESCE(b.randomize_options, 1) as randomize_options,
                   COALESCE(b.show_score, 1) as show_score,
                   COALESCE(b.show_explanation, 0) as show_explanation,
                   COALESCE(b.duration_minutes, 90) as duration_minutes,
                   COALESCE(b.passing_score, 75.0) as passing_score,
                   COALESCE(b.max_violations, 3) as max_violations,
                   CASE 
                       WHEN b.origin = 'official' OR (es.id IS NOT NULL AND (e.exam_type IS NULL OR e.exam_type != 'daily')) THEN 'official_assignment'
                       ELSE 'self_created'
                   END as category
            FROM cbt_question_banks b
            LEFT JOIN cbt_exam_subjects es ON es.bank_id = b.id
            LEFT JOIN cbt_exams e ON es.exam_id = e.id
            WHERE (%s::int IS NOT NULL AND b.teacher_id = %s::int)
               OR (b.teacher_name IS NOT NULL AND b.teacher_name = %s)
               OR (%s != '' AND b.teacher_name ILIKE CONCAT('%%', %s, '%%'))
            ORDER BY b.updated_at DESC
        """, (teacher_id, teacher_id, teacher_name, teacher_name, teacher_name))
    else:
        cursor.execute("""
            SELECT b.id, b.title, b.subject_name, b.grade, b.teacher_id, b.teacher_name, b.total_questions, b.created_at, b.updated_at,
                   b.origin, es.exam_id, e.title as exam_title, e.exam_type,
                   COALESCE(b.randomize_questions, 1) as randomize_questions,
                   COALESCE(b.randomize_options, 1) as randomize_options,
                   COALESCE(b.show_score, 1) as show_score,
                   COALESCE(b.show_explanation, 0) as show_explanation,
                   COALESCE(b.duration_minutes, 90) as duration_minutes,
                   COALESCE(b.passing_score, 75.0) as passing_score,
                   COALESCE(b.max_violations, 3) as max_violations,
                   CASE 
                       WHEN b.origin = 'official' OR (es.id IS NOT NULL AND (e.exam_type IS NULL OR e.exam_type != 'daily')) THEN 'official_assignment'
                       ELSE 'self_created'
                   END as category
            FROM cbt_question_banks b
            LEFT JOIN cbt_exam_subjects es ON es.bank_id = b.id
            LEFT JOIN cbt_exams e ON es.exam_id = e.id
            ORDER BY b.updated_at DESC
        """)

    banks = [dict(row) for row in cursor.fetchall()]
    db.close()
    return {"success": True, "banks": banks}

@router.post("")
def create_question_bank(req: CreateBankRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    
    user_role = (current_user.get("role") or "").lower()
    is_admin = "admin" in user_role or "staff" in user_role or "superadmin" in user_role
    origin = "official" if is_admin else "self"

    # Prioritaskan teacher_id & teacher_name dari request (misal admin menugaskan guru tertentu)
    teacher_id = req.teacher_id if req.teacher_id is not None else (current_user.get("teacher_id") or current_user.get("id"))
    teacher_name = req.teacher_name.strip() if req.teacher_name else (current_user.get("name") or "Guru")

    cursor.execute("""
        INSERT INTO cbt_question_banks (title, subject_name, grade, teacher_id, teacher_name, total_questions, origin)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (req.title, req.subject_name, req.grade, teacher_id, teacher_name, len(req.questions), origin))
    bank_id = cursor.fetchone()[0]

    # Simpan butir soal jika disertakan langsung
    for idx, q in enumerate(req.questions, 1):
        opts_json = json.dumps([opt.dict() for opt in q.options], ensure_ascii=False)
        cursor.execute("""
            INSERT INTO cbt_questions (bank_id, question_number, question_type, content, image_url, audio_url, points, options, correct_answer, explanation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (bank_id, idx, q.question_type, q.content, q.image_url, q.audio_url, q.points, opts_json, q.correct_answer.upper(), q.explanation))

    db.commit()
    db.close()

    return {
        "success": True,
        "message": "Bank soal berhasil dibuat!",
        "bank_id": bank_id
    }

@router.put("/{bank_id}/assign-teacher")
def assign_bank_teacher(bank_id: int, req: AssignBankTeacherRequest, current_user: dict = Depends(get_current_user)):
    """Menugaskan guru sebagai pembuat/pengelola bank soal"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id, title FROM cbt_question_banks WHERE id = ?", (bank_id,))
    bank = cursor.fetchone()
    if not bank:
        db.close()
        raise HTTPException(status_code=404, detail="Bank soal tidak ditemukan.")

    t_name = req.teacher_name.strip()
    t_id = req.teacher_id
    cursor.execute("""
        UPDATE cbt_question_banks
        SET teacher_id = ?, teacher_name = ?, origin = 'official', updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (t_id, t_name, bank_id))

    # Sinkronkan juga ke cbt_exam_subjects jika bank_id ini terhubung ke jadwal ujian
    cursor.execute("""
        UPDATE cbt_exam_subjects
        SET teacher_id = ?, teacher_name = ?
        WHERE bank_id = ?
    """, (t_id, t_name, bank_id))

    # Kirim notifikasi penugasan bank soal ke guru
    try:
        cursor.execute("""
            INSERT INTO cbt_notifications (teacher_id, teacher_name, title, message, type, link, is_read, created_at)
            VALUES (%s, %s, %s, %s, 'assignment', '/bank-soal', 0, CURRENT_TIMESTAMP)
        """, (
            t_id,
            t_name,
            f"Penugasan Bank Soal: {bank['title']}",
            f"Administrator menugaskan Anda sebagai penyusun / pengelola butir soal untuk '{bank['title']}'. Silakan buka menu Bank Soal untuk mengelola soal."
        ))
    except Exception as e_notif:
        print("Gagal menyimpan notifikasi bank soal:", e_notif)

    db.commit()
    db.close()
    return {"success": True, "message": f"Bank soal '{bank['title']}' berhasil ditugaskan ke guru '{t_name}'."}

@router.get("/{bank_id}")
def get_question_bank(bank_id: int, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("SELECT * FROM cbt_question_banks WHERE id = ?", (bank_id,))
    bank_row = cursor.fetchone()
    if not bank_row:
        db.close()
        raise HTTPException(status_code=404, detail="Bank soal tidak ditemukan.")

    bank = dict(bank_row)

    cursor.execute("""
        SELECT id, bank_id, question_number, question_type, content, image_url, audio_url, points, options, correct_answer, explanation,
               COALESCE(lock_order, 0) as lock_order,
               COALESCE(randomize_options_mode, 'default') as randomize_options_mode,
               COALESCE(difficulty, 'sedang') as difficulty,
               COALESCE(topic, '') as topic,
               COALESCE(layout, 'vertical') as layout,
               COALESCE(is_required, 0) as is_required
        FROM cbt_questions
        WHERE bank_id = ?
        ORDER BY question_number ASC
    """, (bank_id,))
    
    questions = []
    for row in cursor.fetchall():
        q = dict(row)
        try:
            q["options"] = json.loads(q["options"])
        except Exception:
            q["options"] = []
        questions.append(q)

    bank["questions"] = questions
    db.close()

    return {"success": True, "bank": bank}

@router.put("/{bank_id}")
def update_question_bank_info(bank_id: int, req: UpdateBankRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id FROM cbt_question_banks WHERE id = ?", (bank_id,))
    if not cursor.fetchone():
        db.close()
        raise HTTPException(status_code=404, detail="Bank soal tidak ditemukan.")
    
    updates = []
    params = []
    if req.title is not None:
        updates.append("title = ?")
        params.append(req.title)
    if req.subject_name is not None:
        updates.append("subject_name = ?")
        params.append(req.subject_name)
    if req.grade is not None:
        updates.append("grade = ?")
        params.append(req.grade)
    if req.teacher_id is not None:
        updates.append("teacher_id = ?")
        params.append(req.teacher_id)
    if req.teacher_name is not None:
        updates.append("teacher_name = ?")
        params.append(req.teacher_name)
    
    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(bank_id)
        cursor.execute(f"UPDATE cbt_question_banks SET {', '.join(updates)} WHERE id = ?", params)
        db.commit()
    db.close()
    return {"success": True, "message": "Informasi kuis berhasil diperbarui."}

@router.put("/{bank_id}/exam-settings")
def update_bank_exam_settings(bank_id: int, req: UpdateBankExamSettingsRequest, current_user: dict = Depends(get_current_user)):
    """Mengatur aturan ujian untuk satu mata pelajaran / bank soal (Acak Soal, Acak Opsi, Tampilkan Skor, Pembahasan, Durasi, KKM)"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id, title, subject_name FROM cbt_question_banks WHERE id = ?", (bank_id,))
    bank = cursor.fetchone()
    if not bank:
        db.close()
        raise HTTPException(status_code=404, detail="Bank soal tidak ditemukan.")

    # 1. Update cbt_question_banks
    cursor.execute("""
        UPDATE cbt_question_banks
        SET randomize_questions = ?,
            randomize_options = ?,
            show_score = ?,
            show_explanation = ?,
            duration_minutes = ?,
            passing_score = ?,
            max_violations = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        1 if req.randomize_questions else 0,
        1 if req.randomize_options else 0,
        1 if req.show_score else 0,
        1 if req.show_explanation else 0,
        req.duration_minutes or 90,
        req.passing_score or 75.0,
        req.max_violations or 3,
        bank_id
    ))

    # 2. Sinkronkan juga ke cbt_exam_subjects jika bank_id ini terhubung ke jadwal/paket ujian
    cursor.execute("""
        UPDATE cbt_exam_subjects
        SET randomize_questions = ?,
            randomize_options = ?,
            show_score = ?,
            show_explanation = ?,
            duration_minutes = COALESCE(?, duration_minutes),
            passing_score = COALESCE(?, passing_score)
        WHERE bank_id = ?
    """, (
        1 if req.randomize_questions else 0,
        1 if req.randomize_options else 0,
        1 if req.show_score else 0,
        1 if req.show_explanation else 0,
        req.duration_minutes,
        req.passing_score,
        bank_id
    ))

    # 3. Jika ini ujian mandiri (daily exam) yang terhubung langsung di cbt_exams.bank_id, update cbt_exams juga
    cursor.execute("""
        UPDATE cbt_exams
        SET randomize_questions = ?,
            randomize_options = ?,
            show_results = ?,
            max_violations = ?
        WHERE bank_id = ?
    """, (
        1 if req.randomize_questions else 0,
        1 if req.randomize_options else 0,
        1 if req.show_score else 0,
        req.max_violations or 3,
        bank_id
    ))

    db.commit()
    db.close()

    return {
        "success": True,
        "message": f"Pengaturan ujian untuk mata pelajaran '{bank['title']}' berhasil disimpan!"
    }

@router.delete("/{bank_id}")
def delete_question_bank(bank_id: int, current_user: dict = Depends(get_current_user)):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM cbt_question_banks WHERE id = ?", (bank_id,))
    db.commit()
    db.close()
    return {"success": True, "message": "Bank soal berhasil dihapus."}

# -------------------------------------------------------------
# FITUR RAMAH GURU: PARSE TEKS & PARSE DOKUMEN WORD (.DOCX)
# -------------------------------------------------------------
@router.post("/parse-text")
def parse_text_endpoint(req: TextParseRequest, current_user: dict = Depends(get_current_user)):
    """
    Mengubah teks hasil copy-paste guru menjadi pratinjau soal siap simpan.
    """
    if not req.raw_text.strip():
        raise HTTPException(status_code=400, detail="Teks soal tidak boleh kosong.")
    
    parsed = parse_raw_question_text(req.raw_text)
    
    total_valid = sum(1 for q in parsed if not q["has_warning"])
    total_warning = len(parsed) - total_valid

    return {
        "success": True,
        "total_parsed": len(parsed),
        "total_valid": total_valid,
        "total_warning": total_warning,
        "questions": parsed
    }

@router.post("/parse-docx")
async def parse_docx_endpoint(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    """
    Membaca file Microsoft Word (.docx) langsung dari guru,
    mengekstrak teks & gambar tertanam, lalu menghasilkan pratinjau soal.
    """
    if docx is None:
        raise HTTPException(
            status_code=500,
            detail="Library 'python-docx' belum terinstal. Silakan jalankan 'pip install python-docx'."
        )

    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Format file harus berupa Microsoft Word (.docx).")

    temp_path = os.path.join(UPLOAD_DIR, f"temp_{uuid.uuid4().hex}_{file.filename}")
    try:
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        doc = docx.Document(temp_path)
        full_text = []

        # Ekstrak paragraf teks
        for p in doc.paragraphs:
            text = p.text.strip()
            if not text:
                continue

            # Periksa jika ada run yang bold yang mungkin merupakan kunci jawaban
            for r in p.runs:
                if r.bold and re.match(r'^[A-Ea-e][\.\)]', r.text.strip()):
                    text = f"*{text}"
                    break
            full_text.append(text)

        raw_joined = "\n".join(full_text)
        parsed = parse_raw_question_text(raw_joined)

        total_valid = sum(1 for q in parsed if not q["has_warning"])
        total_warning = len(parsed) - total_valid

        return {
            "success": True,
            "filename": file.filename,
            "total_parsed": len(parsed),
            "total_valid": total_valid,
            "total_warning": total_warning,
            "questions": parsed
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal membaca file Word: {str(e)}")
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

@router.post("/{bank_id}/questions/batch")
def save_batch_questions(bank_id: int, questions: List[QuestionItem], current_user: dict = Depends(get_current_user)):
    """
    Menyimpan hasil review pratinjau soal ke dalam database bank soal.
    """
    db = get_db()
    cursor = db.cursor()

    # Cek apakah bank ada
    cursor.execute("SELECT id FROM cbt_question_banks WHERE id = ?", (bank_id,))
    if not cursor.fetchone():
        db.close()
        raise HTTPException(status_code=404, detail="Bank soal tidak ditemukan.")

    # Cari nomor soal terakhir
    cursor.execute("SELECT COALESCE(MAX(question_number), 0) FROM cbt_questions WHERE bank_id = ?", (bank_id,))
    start_num = cursor.fetchone()[0]

    for idx, q in enumerate(questions, start_num + 1):
        opts_json = json.dumps([opt.dict() for opt in q.options], ensure_ascii=False)
        cursor.execute("""
            INSERT INTO cbt_questions (bank_id, question_number, question_type, content, image_url, audio_url, points, options, correct_answer, explanation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (bank_id, idx, q.question_type, q.content, q.image_url, q.audio_url, q.points, opts_json, q.correct_answer.upper(), q.explanation))

    # Update total questions count
    cursor.execute("SELECT COUNT(*) FROM cbt_questions WHERE bank_id = ?", (bank_id,))
    total_q = cursor.fetchone()[0]
    cursor.execute("UPDATE cbt_question_banks SET total_questions = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (total_q, bank_id))

    db.commit()
    db.close()

    return {
        "success": True,
        "message": f"Berhasil menyimpan {len(questions)} butir soal ke bank soal!",
        "total_questions": total_q
    }

@router.post("/upload-image")
async def upload_question_image(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    """Upload gambar pendukung soal CBT"""
    valid_extensions = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in valid_extensions:
        raise HTTPException(status_code=400, detail="Format file gambar harus berupa PNG, JPG, JPEG, GIF, WEBP, atau SVG.")
    
    unique_name = f"q_{uuid.uuid4().hex[:12]}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)
    try:
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
            
        return {
            "success": True,
            "image_url": f"/static/uploads/{unique_name}",
            "filename": unique_name
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal mengunggah gambar: {str(e)}")

@router.post("/{bank_id}/questions")
def add_single_question(bank_id: int, q: QuestionItem, current_user: dict = Depends(get_current_user)):
    """Menambahkan satu butir soal secara manual ke bank soal"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id FROM cbt_question_banks WHERE id = ?", (bank_id,))
    if not cursor.fetchone():
        db.close()
        raise HTTPException(status_code=404, detail="Bank soal tidak ditemukan.")

    cursor.execute("SELECT COALESCE(MAX(question_number), 0) + 1 FROM cbt_questions WHERE bank_id = ?", (bank_id,))
    next_num = q.question_number or cursor.fetchone()[0]

    opts_list = [opt.dict() for opt in (q.options or [])]
    opts_json = json.dumps(opts_list, ensure_ascii=False)
    ans_str = (q.correct_answer or "").strip()
    if q.question_type in ("multiple_choice", "true_false", "checkbox"):
        ans_str = ans_str.upper()

    cursor.execute("""
        INSERT INTO cbt_questions (bank_id, question_number, question_type, content, image_url, audio_url, points, options, correct_answer, explanation, lock_order, randomize_options_mode, difficulty, topic, layout, is_required)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (bank_id, next_num, q.question_type, q.content.strip(), q.image_url, q.audio_url, q.points, opts_json, ans_str, q.explanation, 1 if q.lock_order else 0, q.randomize_options_mode or "default", q.difficulty or "sedang", q.topic or "", q.layout or "vertical", 1 if q.is_required else 0))
    q_id = cursor.fetchone()[0]

    # Update total questions count
    cursor.execute("SELECT COUNT(*) FROM cbt_questions WHERE bank_id = ?", (bank_id,))
    total_q = cursor.fetchone()[0]
    cursor.execute("UPDATE cbt_question_banks SET total_questions = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (total_q, bank_id))

    db.commit()
    db.close()

    return {
        "success": True,
        "message": "Butir soal berhasil ditambahkan!",
        "question_id": q_id,
        "total_questions": total_q
    }

class ReorderQuestionsRequest(BaseModel):
    question_ids: List[int]

@router.put("/{bank_id}/questions/reorder")
def reorder_questions(bank_id: int, req: ReorderQuestionsRequest, current_user: dict = Depends(get_current_user)):
    """Memperbarui urutan nomor butir soal di dalam bank soal"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id FROM cbt_question_banks WHERE id = ?", (bank_id,))
    if not cursor.fetchone():
        db.close()
        raise HTTPException(status_code=404, detail="Bank soal tidak ditemukan.")

    for new_num, q_id in enumerate(req.question_ids, 1):
        cursor.execute(
            "UPDATE cbt_questions SET question_number = ? WHERE id = ? AND bank_id = ?",
            (new_num, q_id, bank_id),
        )

    cursor.execute("UPDATE cbt_question_banks SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (bank_id,))
    db.commit()
    db.close()

    return {
        "success": True,
        "message": "Urutan butir soal berhasil diperbarui!"
    }

@router.put("/{bank_id}/questions/{question_id}")
def update_single_question(bank_id: int, question_id: int, q: QuestionItem, current_user: dict = Depends(get_current_user)):
    """Memperbarui satu butir soal di bank soal"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id FROM cbt_questions WHERE id = ? AND bank_id = ?", (question_id, bank_id))
    if not cursor.fetchone():
        db.close()
        raise HTTPException(status_code=404, detail="Butir soal tidak ditemukan.")

    opts_list = [opt.dict() for opt in (q.options or [])]
    opts_json = json.dumps(opts_list, ensure_ascii=False)
    ans_str = (q.correct_answer or "").strip()
    if q.question_type in ("multiple_choice", "true_false", "checkbox"):
        ans_str = ans_str.upper()

    cursor.execute("""
        UPDATE cbt_questions
        SET content = ?, question_type = ?, image_url = ?, audio_url = ?, points = ?, options = ?, correct_answer = ?, explanation = ?,
            lock_order = ?, randomize_options_mode = ?, difficulty = ?, topic = ?, layout = ?, is_required = ?
        WHERE id = ? AND bank_id = ?
    """, (q.content.strip(), q.question_type, q.image_url, q.audio_url, q.points, opts_json, ans_str, q.explanation, 1 if q.lock_order else 0, q.randomize_options_mode or "default", q.difficulty or "sedang", q.topic or "", q.layout or "vertical", 1 if q.is_required else 0, question_id, bank_id))

    cursor.execute("UPDATE cbt_question_banks SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (bank_id,))

    db.commit()
    db.close()

    return {
        "success": True,
        "message": "Butir soal berhasil diperbarui!"
    }

@router.put("/{bank_id}/questions/{question_id}/settings")
def update_question_settings(bank_id: int, question_id: int, req: QuestionSettingsRequest, current_user: dict = Depends(get_current_user)):
    """Memperbarui pengaturan spesifik satu butir soal (kunci urutan, acak opsi, kesulitan, topik, layout)"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT id FROM cbt_questions WHERE id = ? AND bank_id = ?", (question_id, bank_id))
    if not cursor.fetchone():
        db.close()
        raise HTTPException(status_code=404, detail="Butir soal tidak ditemukan.")

    cursor.execute("""
        UPDATE cbt_questions
        SET lock_order = ?,
            randomize_options_mode = ?,
            difficulty = ?,
            topic = ?,
            layout = ?,
            is_required = ?
        WHERE id = ? AND bank_id = ?
    """, (
        1 if req.lock_order else 0,
        req.randomize_options_mode or "default",
        req.difficulty or "sedang",
        req.topic or "",
        req.layout or "vertical",
        1 if req.is_required else 0,
        question_id,
        bank_id
    ))

    cursor.execute("UPDATE cbt_question_banks SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (bank_id,))
    db.commit()
    db.close()

    return {
        "success": True,
        "message": "Pengaturan butir soal berhasil disimpan!"
    }

@router.delete("/{bank_id}/questions/{question_id}")
def delete_single_question(bank_id: int, question_id: int, current_user: dict = Depends(get_current_user)):
    """Menghapus satu butir soal dari bank soal"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("DELETE FROM cbt_questions WHERE id = ? AND bank_id = ?", (question_id, bank_id))
    
    # Update total questions count & re-sequence question numbers
    cursor.execute("SELECT id FROM cbt_questions WHERE bank_id = ? ORDER BY question_number ASC, id ASC", (bank_id,))
    rows = cursor.fetchall()
    for new_idx, r in enumerate(rows, 1):
        cursor.execute("UPDATE cbt_questions SET question_number = ? WHERE id = ?", (new_idx, r[0]))

    total_q = len(rows)
    cursor.execute("UPDATE cbt_question_banks SET total_questions = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (total_q, bank_id))

    db.commit()
    db.close()

    return {
        "success": True,
        "message": "Butir soal berhasil dihapus.",
        "total_questions": total_q
    }
