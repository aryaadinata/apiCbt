import random
import json
from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from database import get_db, get_system_settings
from auth import get_current_user

router = APIRouter(prefix="/api/cbt/student", tags=["Student Exam"])

class StartExamRequest(BaseModel):
    exam_id: int
    subject_id: Optional[int] = None
    token: str
    device_id: Optional[str] = None
    device_info: Optional[str] = None
    browser_info: Optional[str] = None

class SaveAnswerRequest(BaseModel):
    session_id: int
    question_id: int
    student_answer: str # 'A', 'B', etc.
    is_doubtful: bool = False

class ReportViolationRequest(BaseModel):
    session_id: int
    violation_type: str # 'tab_switch', 'window_blur', 'fullscreen_exit'
    details: Optional[str] = None

class UnlockWithCodeRequest(BaseModel):
    session_id: int
    unlock_code: str
    details: Optional[str] = None

class HeartbeatRequest(BaseModel):
    session_id: int
    remaining_seconds: int
    ping_ms: Optional[int] = None
    connection_quality: Optional[str] = None
    device_info: Optional[str] = None
    browser_info: Optional[str] = None

def parse_user_agent(ua_string: str) -> dict:
    if not ua_string:
        return {"device": "Laptop (Windows)", "browser": "Google Chrome"}
    ua = ua_string.lower()
    
    # OS / Device
    if "android" in ua:
        if "tablet" in ua or "sm-t" in ua:
            device = "Tablet (Android)"
        else:
            device = "Smartphone (Android)"
    elif "iphone" in ua:
        device = "iPhone (iOS)"
    elif "ipad" in ua:
        device = "iPad (iPadOS)"
    elif "windows nt 10.0" in ua or "windows nt 11.0" in ua or "windows" in ua:
        device = "Laptop/PC (Windows)"
    elif "macintosh" in ua or "mac os" in ua:
        device = "MacBook/iMac (macOS)"
    elif "linux" in ua:
        device = "Komputer (Linux)"
    elif "cros" in ua:
        device = "Chromebook (ChromeOS)"
    else:
        device = "Laptop/PC (Windows)"

    # Browser
    if "edg/" in ua or "edge/" in ua:
        browser = "Microsoft Edge"
    elif "opr/" in ua or "opera" in ua:
        browser = "Opera"
    elif "chrome/" in ua:
        browser = "Google Chrome"
    elif "firefox/" in ua:
        browser = "Mozilla Firefox"
    elif "safari/" in ua:
        browser = "Apple Safari"
    else:
        browser = "Google Chrome"

    return {"device": device, "browser": browser}

class SubmitExamRequest(BaseModel):
    session_id: int

@router.get("/available-exams")
def get_available_exams(current_user: dict = Depends(get_current_user)):
    """
    Mengambil daftar ujian yang tersedia untuk kelas siswa yang sedang login.
    Mendukung sistem Hybrid Cerdas: ujian yang dijadwalkan tetap muncul agar siswa tahu jadwal & tenang,
    namun status dan tombol pengerjaan dikontrol penuh oleh saklar pembukaan sesi oleh guru/pengawas.
    Untuk paket multi-mapel (cbt_exam_subjects), setiap mata pelajaran terjadwal dimunculkan sebagai kartu
    ujian terpisah agar siswa dapat melihat jadwal dan mengerjakan tiap mapel secara mandiri.
    """
    student_id = current_user.get("student_id") or current_user.get("id")
    student_class = current_user.get("class_name") or ""

    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        SELECT e.*, b.title as bank_title, b.total_questions
        FROM cbt_exams e
        LEFT JOIN cbt_question_banks b ON e.bank_id = b.id
        WHERE e.status = 'active'
        ORDER BY e.id DESC
    """)

    exams = []
    for row in cursor.fetchall():
        item = dict(row)
        try:
            target_classes = json.loads(item["target_classes"])
        except Exception:
            target_classes = []

        # Filter kelas: jika target adalah "all" atau cocok dengan nama kelas siswa
        if "all" in target_classes or not target_classes or student_class in target_classes:
            item["target_classes"] = target_classes

            # Cek mata pelajaran dalam paket ujian jika ini adalah paket multi-mapel
            cursor.execute("""
                SELECT s.*, b.title as bank_title, b.total_questions as actual_questions
                FROM cbt_exam_subjects s
                LEFT JOIN cbt_question_banks b ON s.bank_id = b.id
                WHERE s.exam_id = %s
                ORDER BY s.id ASC
            """, (item["id"],))
            raw_subjects = [dict(r) for r in cursor.fetchall()]

            if raw_subjects:
                matching_subjects = []
                for s in raw_subjects:
                    try:
                        s_targets = json.loads(s.get("target_classes") or "[]")
                    except Exception:
                        s_targets = []
                    s["target_classes"] = s_targets

                    # Filter mapel berdasarkan rombel siswa
                    if not s_targets or "all" in s_targets or student_class in s_targets:
                        matching_subjects.append(s)

                for s in matching_subjects:
                    sub_item = dict(item)
                    sub_item["subject_id"] = s["id"]
                    sub_item["subject_name"] = s["subject_name"]
                    sub_item["grade"] = s.get("grade") or item.get("grade")
                    sub_item["duration_minutes"] = s.get("duration_minutes") or item.get("duration_minutes", 60)
                    sub_item["total_questions"] = s.get("actual_questions") or s.get("total_questions") or 0
                    sub_item["bank_id"] = s.get("bank_id")

                    # Periksa sesi siswa untuk mapel spesifik ini
                    cursor.execute("""
                        SELECT id as session_id, status as session_status, score, remaining_seconds
                        FROM cbt_exam_sessions
                        WHERE exam_id = %s AND student_id = %s AND (subject_id = %s OR subject_id IS NULL)
                        ORDER BY CASE WHEN subject_id = %s THEN 0 ELSE 1 END, id DESC
                        LIMIT 1
                    """, (item["id"], student_id, s["id"], s["id"]))
                    sess_row = cursor.fetchone()

                    if sess_row:
                        s_dict = dict(sess_row)
                        sub_item["session_id"] = s_dict["session_id"]
                        sub_item["session_status"] = s_dict["session_status"]
                        sub_item["score"] = s_dict["score"]
                        sub_item["remaining_seconds"] = s_dict["remaining_seconds"]
                    else:
                        sub_item["session_id"] = None
                        sub_item["session_status"] = "not_started"
                        sub_item["score"] = 0.0
                        sub_item["remaining_seconds"] = sub_item["duration_minutes"] * 60

                    is_session_active = bool(
                        item.get("status") == "active"
                        and (s.get("session_status") == "active" or (s["id"] == item.get("active_subject_id") and s.get("session_status") != "completed"))
                    )
                    sub_item["is_session_active"] = is_session_active

                    # Logika status tampilan
                    if sub_item["session_status"] == "submitted":
                        sub_item["display_status"] = "completed"
                    elif not is_session_active:
                        sub_item["display_status"] = "scheduled"
                    elif sub_item["session_status"] in ("in_progress", "locked"):
                        sub_item["display_status"] = "live"
                    elif is_session_active:
                        sub_item["display_status"] = "live"
                    elif s.get("session_status") == "completed":
                        sub_item["display_status"] = "completed"
                    else:
                        sub_item["display_status"] = "scheduled"

                    sub_item["schedule_info"] = {
                        "exam_date": s.get("exam_date"),
                        "start_time": s.get("start_time"),
                        "end_time": s.get("end_time"),
                    }
                    sub_item["requires_token"] = bool(item.get("is_token_active"))
                    if "token" in sub_item:
                        del sub_item["token"]
                    exams.append(sub_item)
            else:
                # Ujian tunggal biasa
                sub_item = dict(item)
                sub_item["subject_id"] = None
                sub_item["subjects"] = []

                cursor.execute("""
                    SELECT id as session_id, status as session_status, score, remaining_seconds
                    FROM cbt_exam_sessions
                    WHERE exam_id = %s AND student_id = %s AND (subject_id IS NULL OR subject_id = 0)
                """, (item["id"], student_id))
                sess_row = cursor.fetchone()

                if sess_row:
                    s_dict = dict(sess_row)
                    sub_item["session_id"] = s_dict["session_id"]
                    sub_item["session_status"] = s_dict["session_status"]
                    sub_item["score"] = s_dict["score"]
                    sub_item["remaining_seconds"] = s_dict["remaining_seconds"]
                else:
                    sub_item["session_id"] = None
                    sub_item["session_status"] = "not_started"
                    sub_item["score"] = 0.0
                    sub_item["remaining_seconds"] = (item.get("duration_minutes") or 60) * 60

                is_active = (item.get("status") == "active")
                sub_item["is_session_active"] = is_active
                if sub_item["session_status"] == "submitted":
                    sub_item["display_status"] = "completed"
                elif not is_active:
                    sub_item["display_status"] = "scheduled"
                elif sub_item["session_status"] in ("in_progress", "locked"):
                    sub_item["display_status"] = "live"
                elif is_active:
                    sub_item["display_status"] = "live"
                elif item.get("status") == "completed":
                    sub_item["display_status"] = "completed"
                else:
                    sub_item["display_status"] = "scheduled"

                sub_item["schedule_info"] = {
                    "exam_date": item.get("start_date"),
                    "start_time": item.get("start_time"),
                    "end_time": item.get("end_time"),
                }
                sub_item["requires_token"] = bool(item.get("is_token_active"))
                if "token" in sub_item:
                    del sub_item["token"]
                exams.append(sub_item)

    db.close()
    return {"success": True, "exams": exams}

@router.post("/start-exam")
def start_exam(req: StartExamRequest, request: Request, current_user: dict = Depends(get_current_user)):
    """
    Memulai ujian: memverifikasi token pengawas, mengunci perangkat (device lock),
    dan mengembalikan daftar soal teracak (TANPA kunci jawaban).
    """
    student_id = current_user.get("student_id") or current_user.get("id")
    student_name = current_user.get("name") or "Siswa"
    class_name = current_user.get("class_name") or "-"
    nisn = current_user.get("nisn") or current_user.get("nis") or "-"
    client_ip = request.client.host if request.client else "127.0.0.1"

    db = get_db()
    cursor = db.cursor()

    # 1. Cek Ujian & Token
    cursor.execute("SELECT * FROM cbt_exams WHERE id = ? AND status = 'active'", (req.exam_id,))
    exam = cursor.fetchone()
    if not exam:
        db.close()
        raise HTTPException(status_code=400, detail="Ujian tidak ditemukan atau telah ditutup/diselesaikan oleh pihak sekolah.")

    exam = dict(exam)

    # Validasi Pembukaan Sesi (Sistem Hybrid Cerdas)
    target_subject = None
    active_subject_id = None

    if req.subject_id:
        cursor.execute("SELECT * FROM cbt_exam_subjects WHERE id = %s AND exam_id = %s", (req.subject_id, req.exam_id))
        s_row = cursor.fetchone()
        if not s_row:
            db.close()
            raise HTTPException(status_code=404, detail="Mata pelajaran jadwal tidak ditemukan dalam ujian ini.")
        target_subject = dict(s_row)
        active_subject_id = target_subject["id"]
        is_active = (target_subject.get("session_status") == "active" or target_subject["id"] == exam.get("active_subject_id"))
        if not is_active:
            db.close()
            raise HTTPException(
                status_code=400,
                detail=f"Sesi ujian untuk mata pelajaran '{target_subject['subject_name']}' belum dibuka oleh pengawas ruangan atau guru pengampu. Silakan tunggu instruksi pengawas."
            )
    else:
        cursor.execute("SELECT * FROM cbt_exam_subjects WHERE exam_id = %s", (req.exam_id,))
        subjects = [dict(s) for s in cursor.fetchall()]
        if subjects:
            if exam.get("active_subject_id"):
                target_subject = next((s for s in subjects if s["id"] == exam["active_subject_id"]), None)
            if not target_subject:
                target_subject = next((s for s in subjects if s.get("session_status") == "active"), None)

            if not target_subject:
                db.close()
                raise HTTPException(
                    status_code=400, 
                    detail="Sesi ujian untuk mata pelajaran ini belum dibuka oleh pengawas ruangan atau guru pengampu. Silakan tunggu instruksi pengawas."
                )
            active_subject_id = target_subject["id"]
        else:
            if exam.get("status") != "active":
                db.close()
                raise HTTPException(
                    status_code=400, 
                    detail="Ujian ini belum dibuka oleh guru atau pengawas ruangan."
                )

    # 2. Cek Sesi Ujian Siswa
    ua_header = request.headers.get("user-agent", "")
    parsed_ua = parse_user_agent(ua_header)
    device_info = req.device_info or parsed_ua["device"]
    browser_info = req.browser_info or parsed_ua["browser"]

    if active_subject_id:
        cursor.execute("""
            SELECT * FROM cbt_exam_sessions 
            WHERE exam_id = %s AND student_id = %s AND (subject_id = %s OR subject_id IS NULL)
            ORDER BY CASE WHEN subject_id = %s THEN 0 ELSE 1 END, id DESC
            LIMIT 1
        """, (req.exam_id, student_id, active_subject_id, active_subject_id))
    else:
        cursor.execute("""
            SELECT * FROM cbt_exam_sessions 
            WHERE exam_id = %s AND student_id = %s AND (subject_id IS NULL OR subject_id = 0)
            ORDER BY id DESC
            LIMIT 1
        """, (req.exam_id, student_id))
    session = cursor.fetchone()

    # Validasi Token: HANYA jika siswa BELUM memiliki sesi aktif (baru pertama kali masuk ujian)!
    # Jika sesi sudah ada (in_progress atau locked), siswa sedang me-resume ujian sehingga tidak perlu token lagi.
    if not session and exam.get("is_token_active"):
        input_token = (req.token or "").strip().upper()
        valid_tokens = []
        if exam.get("token"):
            valid_tokens.append(exam["token"].strip().upper())
        if exam.get("previous_token"):
            valid_tokens.append(exam["previous_token"].strip().upper())

        if not input_token or input_token not in valid_tokens:
            db.close()
            raise HTTPException(status_code=400, detail="Token ujian salah! Silakan minta token ke pengawas ruangan.")

    sys_settings = get_system_settings(include_secrets=False)
    anticheat_cfg = {
        "anticheat_enabled": bool(sys_settings.get("anticheat_enabled", 1)),
        "anticheat_fullscreen": bool(sys_settings.get("anticheat_fullscreen", 1)),
        "anticheat_tab_switch": bool(sys_settings.get("anticheat_tab_switch", 1)),
        "anticheat_window_blur": bool(sys_settings.get("anticheat_window_blur", 1)),
        "anticheat_block_right_click": bool(sys_settings.get("anticheat_block_right_click", 1)),
        "anticheat_block_shortcuts": bool(sys_settings.get("anticheat_block_shortcuts", 1)),
        "anticheat_block_copy_paste": bool(sys_settings.get("anticheat_block_copy_paste", 1)),
        "anticheat_single_device": bool(sys_settings.get("anticheat_single_device", 1)),
        "anticheat_auto_lock": bool(sys_settings.get("anticheat_auto_lock", 1)),
        "anticheat_max_violations": int(sys_settings.get("anticheat_max_violations", 3)),
        "anticheat_time_away_seconds": int(sys_settings.get("anticheat_time_away_seconds", 5)),
    }

    exam_duration = (target_subject.get("duration_minutes") or exam.get("duration_minutes") or 60) if target_subject else (exam.get("duration_minutes") or 60)

    if session:
        session = dict(session)
        # Jika sudah selesai, tidak boleh ujian lagi
        if session["status"] == "submitted":
            db.close()
            raise HTTPException(status_code=400, detail="Anda telah menyelesaikan dan mengumpulkan ujian ini.")

        # Proteksi Single Device (Hanya aktif jika fitur Anti-Cheating & Single Device dihidupkan di Pengaturan Sistem)
        if anticheat_cfg["anticheat_enabled"] and anticheat_cfg["anticheat_single_device"]:
            is_localhost = client_ip in ("127.0.0.1", "::1", "localhost") and (session.get("ip_address") in ("127.0.0.1", "::1", "localhost", None) or not session.get("ip_address"))
            if session.get("device_id") and req.device_id and session["device_id"] != req.device_id and not is_localhost:
                db.close()
                raise HTTPException(
                    status_code=403, 
                    detail="Akun Anda sedang aktif di perangkat lain. Minta Pengawas untuk melakukan 'Reset Device' jika perangkat Anda bermasalah."
                )

        session_id = session["id"]
        remaining_seconds = session["remaining_seconds"] or (exam_duration * 60)
        # Perbarui metadata perangkat, sinkronkan subject_id jika sebelumnya NULL, dan catat detak jantung
        new_device_id = req.device_id if (not session.get("device_id") or is_localhost) else session.get("device_id")
        cursor.execute("""
            UPDATE cbt_exam_sessions
            SET device_id = %s,
                device_info = COALESCE(%s, device_info),
                browser_info = COALESCE(%s, browser_info),
                ip_address = %s,
                subject_id = COALESCE(subject_id, %s),
                last_heartbeat = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (new_device_id, device_info, browser_info, client_ip, active_subject_id, session_id))
        current_status = session["status"]
    else:
        # Buat sesi baru
        remaining_seconds = exam_duration * 60
        cursor.execute("""
            INSERT INTO cbt_exam_sessions (
                exam_id, subject_id, student_id, student_name, class_name, nisn,
                start_time, remaining_seconds, status, device_id, ip_address,
                device_info, browser_info, connection_quality, ping_ms, last_heartbeat
            ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s, 'in_progress', %s, %s, %s, %s, 'stabil', 25, CURRENT_TIMESTAMP)
            RETURNING id
        """, (req.exam_id, active_subject_id, student_id, student_name, class_name, nisn, remaining_seconds, req.device_id, client_ip, device_info, browser_info))
        session_id = cursor.fetchone()[0]
        current_status = "in_progress"

    # 3. Ambil Butir Soal dari Bank Soal (Mendukung Ujian Tunggal & Paket Multi-Mapel Berdasarkan Rombel)
    bank_ids = []
    if target_subject and target_subject.get("bank_id"):
        bank_ids.append(target_subject["bank_id"])
    elif active_subject_id:
        cursor.execute("""
            SELECT bank_id, target_classes 
            FROM cbt_exam_subjects 
            WHERE exam_id = %s AND id = %s AND bank_id IS NOT NULL
        """, (req.exam_id, active_subject_id))
        for s_row in cursor.fetchall():
            try:
                s_targets = json.loads(s_row["target_classes"] or "[]")
            except Exception:
                s_targets = []
            if not s_targets or "all" in s_targets or class_name in s_targets:
                if s_row["bank_id"]:
                    bank_ids.append(s_row["bank_id"])
    elif exam.get("bank_id"):
        bank_ids.append(exam["bank_id"])

    active_bank_info = None
    if bank_ids:
        cursor.execute("SELECT * FROM cbt_question_banks WHERE id = ?", (bank_ids[0],))
        b_r = cursor.fetchone()
        if b_r:
            active_bank_info = dict(b_r)

    bank_rand_opts = active_bank_info.get("randomize_options") if active_bank_info else None
    bank_rand_qs = active_bank_info.get("randomize_questions") if active_bank_info else None
    subj_rand_opts = target_subject.get("randomize_options") if target_subject else None
    subj_rand_qs = target_subject.get("randomize_questions") if target_subject else None

    # Prioritaskan setting mapel dari bank atau subject, fallback ke setting ujian
    if bank_rand_opts is not None:
        exam_rand_opts = bool(bank_rand_opts)
    elif subj_rand_opts is not None:
        exam_rand_opts = bool(subj_rand_opts)
    else:
        exam_rand_opts = bool(exam.get("randomize_options", 1))

    if bank_rand_qs is not None:
        exam_rand_qs = bool(bank_rand_qs)
    elif subj_rand_qs is not None:
        exam_rand_qs = bool(subj_rand_qs)
    else:
        exam_rand_qs = bool(exam.get("randomize_questions", 1))

    question_rows = []
    if bank_ids:
        placeholders = ",".join("?" for _ in bank_ids)
        cursor.execute(f"""
            SELECT id, question_number, question_type, content, image_url, audio_url, points, options,
                   COALESCE(lock_order, 0) as lock_order,
                   COALESCE(randomize_options_mode, 'default') as randomize_options_mode,
                   COALESCE(difficulty, 'sedang') as difficulty,
                   COALESCE(layout, 'vertical') as layout,
                   COALESCE(is_required, 0) as is_required
            FROM cbt_questions
            WHERE bank_id IN ({placeholders})
            ORDER BY bank_id, question_number ASC
        """, tuple(bank_ids))
        question_rows = cursor.fetchall()

    raw_questions = []
    for row in question_rows:
        q = dict(row)
        q["question_text"] = q.get("content") or ""
        try:
            opts = json.loads(q["options"])
            opt_mode = q.get("randomize_options_mode") or "default"
            if opt_mode == "disabled":
                should_shuffle_opts = False
            elif opt_mode == "enabled":
                should_shuffle_opts = True
            else:
                should_shuffle_opts = exam_rand_opts

            if should_shuffle_opts and isinstance(opts, list):
                random.seed(f"{session_id}_{q['id']}") # Deterministic shuffle per student
                random.shuffle(opts)
            if isinstance(opts, list):
                for idx, opt in enumerate(opts):
                    if isinstance(opt, dict):
                        opt["display_key"] = chr(65 + idx)
            q["options"] = opts
        except Exception:
            q["options"] = []
        raw_questions.append(q)

    # Acak urutan nomor soal jika diaktifkan (tetap konsisten untuk siswa ini)
    # Butir soal yang lock_order == 1 posisinya dipertahankan di nomor/slot aslinya
    if exam_rand_qs:
        random.seed(f"exam_{session_id}")
        unlocked = [q for q in raw_questions if not q.get("lock_order")]
        random.shuffle(unlocked)

        shuffled_result = []
        unlocked_idx = 0
        for q in raw_questions:
            if q.get("lock_order"):
                shuffled_result.append(q)
            else:
                shuffled_result.append(unlocked[unlocked_idx])
                unlocked_idx += 1
        raw_questions = shuffled_result

    # 4. Ambil Jawaban yang Sudah Tersimpan (jika resume ujian)
    cursor.execute("SELECT question_id, student_answer, is_doubtful FROM cbt_student_answers WHERE session_id = ?", (session_id,))
    saved_answers = {row["question_id"]: {"answer": row["student_answer"], "is_doubtful": bool(row["is_doubtful"])} for row in cursor.fetchall()}

    # Ambil butir soal yang terakhir kali dijawab/diubah oleh siswa
    cursor.execute("""
        SELECT question_id 
        FROM cbt_student_answers 
        WHERE session_id = ? AND student_answer IS NOT NULL AND student_answer != ''
        ORDER BY answered_at DESC 
        LIMIT 1
    """, (session_id,))
    last_ans_row = cursor.fetchone()
    last_answered_qid = last_ans_row[0] if last_ans_row else None

    db.commit()
    db.close()

    return {
        "success": True,
        "session_id": session_id,
        "subject_id": active_subject_id,
        "status": current_status,
        "remaining_seconds": remaining_seconds,
        "duration_minutes": exam_duration,
        "max_violations": anticheat_cfg["anticheat_max_violations"] if anticheat_cfg["anticheat_enabled"] else 0,
        "anticheat": anticheat_cfg,
        "exam_title": exam["title"],
        "subject_name": (target_subject["subject_name"] if target_subject else exam["subject_name"]),
        "questions": raw_questions,
        "saved_answers": saved_answers,
        "last_answered_question_id": last_answered_qid
    }

@router.post("/save-answer")
def save_answer(req: SaveAnswerRequest, current_user: dict = Depends(get_current_user)):
    """
    Autosave jawaban: menyimpan langsung ke database SQLite dalam hitungan <2 milidetik.
    """
    student_id = current_user.get("student_id") or current_user.get("id")
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        INSERT INTO cbt_student_answers (session_id, exam_id, student_id, question_id, student_answer, is_doubtful)
        SELECT s.id, s.exam_id, s.student_id, ?, ?, ?
        FROM cbt_exam_sessions s
        WHERE s.id = ? AND s.student_id = ? AND s.status != 'submitted'
        ON CONFLICT(session_id, question_id) DO UPDATE SET
            student_answer = excluded.student_answer,
            is_doubtful = excluded.is_doubtful,
            answered_at = CURRENT_TIMESTAMP
    """, (req.question_id, req.student_answer, 1 if req.is_doubtful else 0, req.session_id, student_id))

    # Update hitungan total_answered dan segarkan detak jantung di sesi
    cursor.execute("""
        UPDATE cbt_exam_sessions
        SET total_answered = (SELECT COUNT(*) FROM cbt_student_answers WHERE session_id = ? AND student_answer != ''),
            last_heartbeat = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (req.session_id, req.session_id))

    db.commit()
    db.close()

    return {"success": True}

@router.post("/report-violation")
def report_violation(req: ReportViolationRequest, current_user: dict = Depends(get_current_user)):
    """
    Mendeteksi & mengunci layar saat siswa berpindah tab (visibilitychange),
    membuka aplikasi lain (blur), atau keluar dari mode fullscreen!
    Menghormati toggle Anti-Cheating di Pengaturan Sistem CBT.
    """
    sys_settings = get_system_settings(include_secrets=False)
    if not bool(sys_settings.get("anticheat_enabled", 1)):
        return {
            "success": True,
            "is_locked": False,
            "lock_count": 0,
            "max_violations": 0,
            "message": "Sistem anti-cheating sedang dinonaktifkan oleh administrator."
        }

    student_id = current_user.get("student_id") or current_user.get("id")
    db = get_db()
    cursor = db.cursor()

    # Catat ke log pelanggaran
    cursor.execute("""
        INSERT INTO cbt_violations (session_id, exam_id, student_id, violation_type, details)
        SELECT s.id, s.exam_id, s.student_id, ?, ?
        FROM cbt_exam_sessions s
        WHERE s.id = ? AND s.student_id = ?
    """, (req.violation_type, req.details or "Terdeteksi keluar dari jendela ujian", req.session_id, student_id))

    # Cek pengaturan max_violations dari sistem & ujian terkait
    cursor.execute("""
        SELECT e.max_violations, s.lock_count
        FROM cbt_exam_sessions s
        JOIN cbt_exams e ON s.exam_id = e.id
        WHERE s.id = ? AND s.student_id = ?
    """, (req.session_id, student_id))
    session_info = cursor.fetchone()

    sys_max = int(sys_settings.get("anticheat_max_violations", 3))
    auto_lock_enabled = bool(sys_settings.get("anticheat_auto_lock", 1))
    exam_max = session_info["max_violations"] if (session_info and session_info["max_violations"] is not None) else sys_max
    max_violations = sys_max if sys_max >= 0 else exam_max
    current_locks = session_info["lock_count"] if session_info else 0
    new_locks = current_locks + 1

    time_away_limit = int(sys_settings.get("anticheat_time_away_seconds", 5))
    is_time_away_timeout = (req.violation_type == "time_away_timeout")

    # Kunci jika anticheat_auto_lock ON dan (mencapai batas pelanggaran ATAU durasi time-away habis)
    should_lock = auto_lock_enabled and (
        (max_violations > 0 and new_locks >= max_violations) or is_time_away_timeout
    )

    reason_map = {
        "tab_switch": "Terdeteksi membuka tab atau jendela browser lain",
        "window_blur": "Terdeteksi membuka aplikasi lain di luar browser",
        "fullscreen_exit": "Terdeteksi keluar dari mode layar penuh (Fullscreen)",
        "time_away_timeout": f"Meninggalkan lembar ujian melebihi batas waktu toleransi ({time_away_limit} detik)"
    }
    lock_reason = reason_map.get(req.violation_type, "Pelanggaran aturan ujian")

    if should_lock:
        unlock_code = str(random.randint(100000, 999999))
        cursor.execute("""
            UPDATE cbt_exam_sessions
            SET status = 'locked',
                lock_count = lock_count + 1,
                lock_reason = ?,
                unlock_code = ?
            WHERE id = ? AND student_id = ? AND status != 'submitted'
        """, (lock_reason, unlock_code, req.session_id, student_id))
    else:
        cursor.execute("""
            UPDATE cbt_exam_sessions
            SET lock_count = lock_count + 1
            WHERE id = ? AND student_id = ? AND status != 'submitted'
        """, (req.session_id, student_id))

    db.commit()
    db.close()

    if should_lock:
        if is_time_away_timeout:
            lock_msg = f"Ujian terkunci otomatis karena Anda meninggalkan jendela ujian lebih dari {time_away_limit} detik. Hubungi pengawas ruangan untuk mendapatkan kode buka kunci."
        else:
            lock_msg = f"Ujian terkunci karena Anda melanggar aturan ({new_locks}/{max_violations} pelanggaran). Hubungi pengawas ruangan untuk mendapatkan kode buka kunci."

        return {
            "success": True,
            "is_locked": True,
            "lock_reason": lock_reason,
            "lock_count": new_locks,
            "message": lock_msg
        }
    else:
        return {
            "success": True,
            "is_locked": False,
            "lock_count": new_locks,
            "max_violations": max_violations,
            "message": f"Peringatan {new_locks}/{max_violations}: Anda keluar dari layar ujian. Jangan ulangi atau ujian Anda akan terkunci!"
        }

@router.post("/unlock-with-code")
def unlock_with_code(req: UnlockWithCodeRequest, current_user: dict = Depends(get_current_user)):
    """
    Siswa memasukkan 6-digit kode buka kunci yang diberikan oleh Pengawas Ruangan.
    Jika kode cocok, status sesi dikembalikan ke 'in_progress'.
    """
    student_id = current_user.get("student_id") or current_user.get("id")
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        SELECT id, status, unlock_code
        FROM cbt_exam_sessions
        WHERE id = ? AND student_id = ?
    """, (req.session_id, student_id))
    session = cursor.fetchone()

    if not session:
        db.close()
        raise HTTPException(status_code=404, detail="Sesi ujian tidak ditemukan.")

    if session["status"] != "locked":
        db.close()
        return {"success": True, "message": "Ujian Anda tidak sedang terkunci."}

    clean_code = (req.unlock_code or "").strip()
    saved_code = (session["unlock_code"] or "").strip()

    if not saved_code or clean_code != saved_code:
        db.close()
        raise HTTPException(status_code=400, detail="Kode buka kunci salah atau tidak valid. Silakan minta kode terbaru kepada Pengawas Ruangan.")

    cursor.execute("""
        UPDATE cbt_exam_sessions
        SET status = 'in_progress', lock_reason = NULL, unlock_code = NULL
        WHERE id = ?
    """, (req.session_id,))
    db.commit()
    db.close()

    return {
        "success": True,
        "message": "Kode valid! Kunci ujian Anda berhasil dibuka. Silakan lanjutkan pengerjaan."
    }

@router.post("/heartbeat")
def heartbeat(req: HeartbeatRequest, current_user: dict = Depends(get_current_user)):
    """
    Heartbeat berkala (tiap 15 detik): menyinkronkan sisa waktu, ping latency,
    kualitas koneksi, dan mengecek apakah status siswa telah di-unlock oleh pengawas secara remote!
    """
    student_id = current_user.get("student_id") or current_user.get("id")
    db = get_db()
    cursor = db.cursor()

    ping = req.ping_ms if req.ping_ms is not None else 25
    conn_q = req.connection_quality or ("stabil" if ping < 60 else "sedang" if ping < 180 else "lemah")

    cursor.execute("""
        UPDATE cbt_exam_sessions
        SET remaining_seconds = %s,
            ping_ms = %s,
            connection_quality = %s,
            device_info = COALESCE(%s, device_info),
            browser_info = COALESCE(%s, browser_info),
            last_heartbeat = CURRENT_TIMESTAMP
        WHERE id = %s AND student_id = %s AND status != 'submitted'
    """, (req.remaining_seconds, ping, conn_q, req.device_info, req.browser_info, req.session_id, student_id))

    cursor.execute("SELECT status, lock_reason, lock_count, ping_ms, connection_quality FROM cbt_exam_sessions WHERE id = %s", (req.session_id,))
    session = cursor.fetchone()
    db.commit()
    db.close()

    if not session:
        return {"success": False, "status": "unknown"}

    return {
        "success": True,
        "status": session["status"],
        "lock_reason": session["lock_reason"],
        "lock_count": session["lock_count"],
        "ping_ms": session.get("ping_ms", 25),
        "connection_quality": session.get("connection_quality", "stabil")
    }

@router.post("/submit-exam")
def submit_exam(req: SubmitExamRequest, current_user: dict = Depends(get_current_user)):
    """
    Mengumpulkan lembar ujian & melakukan penilaian otomatis (Auto-Grading) instan.
    """
    student_id = current_user.get("student_id") or current_user.get("id")
    db = get_db()
    cursor = db.cursor()

    # Ambil sesi & bank_id
    cursor.execute("""
        SELECT s.*, e.bank_id as exam_bank_id, e.show_results
        FROM cbt_exam_sessions s
        JOIN cbt_exams e ON s.exam_id = e.id
        WHERE s.id = ? AND s.student_id = ?
    """, (req.session_id, student_id))
    session = cursor.fetchone()

    if not session:
        db.close()
        raise HTTPException(status_code=404, detail="Sesi ujian tidak ditemukan.")

    if session["status"] == "submitted":
        db.close()
        return {"success": True, "message": "Ujian sudah berhasil dikumpulkan sebelumnya.", "score": session["score"]}

    bank_id = None
    if session.get("subject_id"):
        cursor.execute("SELECT bank_id FROM cbt_exam_subjects WHERE id = ?", (session["subject_id"],))
        subj_row = cursor.fetchone()
        if subj_row and subj_row["bank_id"]:
            bank_id = subj_row["bank_id"]
    if not bank_id:
        bank_id = session.get("exam_bank_id") or session.get("bank_id")

    # Ambil kunci jawaban asli
    cursor.execute("SELECT id, correct_answer, points FROM cbt_questions WHERE bank_id = ?", (bank_id,))
    questions = {row["id"]: {"correct": row["correct_answer"].strip().upper(), "points": row["points"] or 1.0} for row in cursor.fetchall()}

    # Ambil jawaban siswa
    cursor.execute("SELECT id, question_id, student_answer FROM cbt_student_answers WHERE session_id = ?", (req.session_id,))
    student_answers = cursor.fetchall()

    total_correct = 0
    total_earned_points = 0.0
    total_max_points = sum(q["points"] for q in questions.values()) or 1.0

    for ans in student_answers:
        q_id = ans["question_id"]
        q_info = questions.get(q_id)
        if q_info:
            is_correct = 1 if (ans["student_answer"] or "").strip().upper() == q_info["correct"] else 0
            points = q_info["points"] if is_correct else 0.0
            if is_correct:
                total_correct += 1
                total_earned_points += points

            cursor.execute("""
                UPDATE cbt_student_answers
                SET is_correct = ?, points_earned = ?
                WHERE id = ?
            """, (is_correct, points, ans["id"]))

    final_score = round((total_earned_points / total_max_points) * 100, 2)

    cursor.execute("""
        UPDATE cbt_exam_sessions
        SET status = 'submitted',
            score = ?,
            total_correct = ?,
            total_answered = ?,
            submitted_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (final_score, total_correct, len(student_answers), req.session_id))

    bank_info = None
    if bank_id:
        cursor.execute("SELECT * FROM cbt_question_banks WHERE id = ?", (bank_id,))
        b_row = cursor.fetchone()
        if b_row:
            bank_info = dict(b_row)

    show_score = bool(bank_info["show_score"]) if (bank_info and bank_info.get("show_score") is not None) else bool(session.get("show_results", 1))
    show_explanation = bool(bank_info.get("show_explanation", 0)) if bank_info else False

    review_questions = []
    if show_explanation and bank_id:
        cursor.execute("""
            SELECT q.id, q.question_number, q.question_type, q.content, q.explanation, q.correct_answer, q.options,
                   sa.student_answer, sa.is_correct
            FROM cbt_questions q
            LEFT JOIN cbt_student_answers sa ON sa.question_id = q.id AND sa.session_id = ?
            WHERE q.bank_id = ?
            ORDER BY q.question_number ASC
        """, (req.session_id, bank_id))
        for r_row in cursor.fetchall():
            rq = dict(r_row)
            try:
                rq["options"] = json.loads(rq["options"])
            except Exception:
                rq["options"] = []
            rq["question_text"] = rq.get("content") or ""
            review_questions.append(rq)

    db.commit()
    db.close()

    return {
        "success": True,
        "message": "Ujian berhasil dikumpulkan!",
        "score": final_score if show_score else None,
        "total_correct": total_correct if show_score else None,
        "total_questions": len(questions),
        "show_explanation": show_explanation,
        "review_questions": review_questions
    }
