import io
import re
import json
import math
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from database import get_db
from auth import get_current_user

router = APIRouter(prefix="/api/cbt/results", tags=["Exam Results & Analysis"])


def _strip_html(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", str(text))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _safe_filename(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_\-]+", "_", str(text or "export")).strip("_")
    return cleaned[:80] or "export"


def _grade_to_roman(grade: Optional[int]) -> str:
    mapping = {10: "X", 11: "XI", 12: "XII", 7: "VII", 8: "VIII", 9: "IX"}
    if grade in mapping:
        return mapping[grade]
    return str(grade) if grade else "-"


def _get_school_profile(cursor) -> dict:
    cursor.execute("SELECT * FROM cbt_synced_school_profile ORDER BY id ASC LIMIT 1")
    row = cursor.fetchone()
    if row:
        return dict(row)
    return {
        "school_name": "SEKOLAH MENENGAH ATAS",
        "address": "",
        "headmaster_name": "",
        "headmaster_nip": "",
    }


def _get_exam_and_subjects(cursor, exam_id: int):
    cursor.execute("SELECT * FROM cbt_exams WHERE id = %s", (exam_id,))
    exam_row = cursor.fetchone()
    if not exam_row:
        raise HTTPException(status_code=404, detail="Paket ujian tidak ditemukan.")
    exam = dict(exam_row)
    try:
        exam["target_classes"] = json.loads(exam.get("target_classes") or "[]")
    except Exception:
        exam["target_classes"] = []

    cursor.execute(
        """
        SELECT s.*, b.title as bank_title, b.total_questions as bank_total_questions
        FROM cbt_exam_subjects s
        LEFT JOIN cbt_question_banks b ON s.bank_id = b.id
        WHERE s.exam_id = %s
        ORDER BY s.grade ASC, s.subject_name ASC, s.id ASC
        """,
        (exam_id,),
    )
    subjects = []
    for r in cursor.fetchall():
        d = dict(r)
        try:
            d["target_classes"] = json.loads(d.get("target_classes") or "[]")
        except Exception:
            d["target_classes"] = []
        subjects.append(d)

    # Jika ujian tunggal (tidak punya baris di cbt_exam_subjects), buat representasi 1 mapel
    if not subjects:
        bank_q_count = 0
        if exam.get("bank_id"):
            cursor.execute("SELECT COUNT(*) FROM cbt_questions WHERE bank_id = %s", (exam["bank_id"],))
            bank_q_count = cursor.fetchone()[0]
        subjects.append(
            {
                "id": 0,
                "exam_id": exam["id"],
                "subject_name": exam.get("subject_name") or exam.get("title"),
                "grade": exam.get("grade") or 10,
                "teacher_id": exam.get("created_by"),
                "teacher_name": exam.get("created_by_name") or "-",
                "duration_minutes": exam.get("duration_minutes") or 60,
                "total_questions": bank_q_count,
                "bank_total_questions": bank_q_count,
                "passing_score": 75.0,
                "max_score": 100.0,
                "bank_id": exam.get("bank_id"),
                "exam_date": exam.get("start_date"),
                "start_time": None,
                "end_time": None,
                "target_classes": exam["target_classes"],
                "status": "ready" if exam.get("bank_id") else "pending_questions",
            }
        )

    return exam, subjects


def _load_target_students(cursor, exam: dict, subject: Optional[dict], scope: str, grade: Optional[int], class_name: Optional[str]):
    """
    Mengambil seluruh siswa tersinkron yang masuk dalam ruang lingkup (kelas atau angkatan)
    serta cocok dengan target kelas paket ujian / mata pelajaran.
    """
    cursor.execute(
        """
        SELECT id, nis, nisn, name, class_name, grade, major_code, gender
        FROM cbt_synced_students
        ORDER BY grade ASC, class_name ASC, name ASC
        """
    )
    all_students = [dict(r) for r in cursor.fetchall()]

    # Tentukan target classes dari mapel (jika spesifik) atau paket ujian
    subj_targets = (subject or {}).get("target_classes") or []
    exam_targets = exam.get("target_classes") or []
    effective_targets = subj_targets if (subj_targets and "all" not in subj_targets) else (
        exam_targets if (exam_targets and "all" not in exam_targets) else []
    )
    effective_target_set = {str(c).strip() for c in effective_targets if c}

    filtered = []
    for stu in all_students:
        stu_cls = (stu.get("class_name") or "").strip()
        stu_grade = stu.get("grade")

        # Filter target kelas mapel/ujian jika terdefinisi
        if effective_target_set and stu_cls not in effective_target_set:
            continue

        # Jika mapel spesifik punya grade dan tidak ada target_classes eksplisit
        if not effective_target_set and subject and subject.get("grade") and stu_grade:
            if int(stu_grade) != int(subject["grade"]):
                continue

        # Filter scope user (per kelas vs per angkatan)
        if scope == "kelas" and class_name and class_name != "all":
            if stu_cls != class_name.strip():
                continue
        elif scope == "angkatan" and grade is not None and grade > 0:
            if stu_grade is not None and int(stu_grade) != int(grade):
                continue

        filtered.append(stu)

    return filtered


def _compute_subject_evaluation(
    cursor,
    exam: dict,
    subject: dict,
    scope: str = "angkatan",
    grade: Optional[int] = None,
    class_name: Optional[str] = None,
) -> dict:
    """
    Menghitung hasil nilai peserta, rekap per kelas, statistik ringkasan,
    dan analisis butir soal (Tingkat Kesukaran P, Daya Pembeda D, Distribusi Opsi A-E)
    untuk satu mata pelajaran berdasarkan ruang lingkup (Per Kelas / Per Angkatan).
    """
    exam_id = exam["id"]
    bank_id = subject.get("bank_id")
    passing_score = float(subject.get("passing_score") or 75.0)
    max_score_cfg = float(subject.get("max_score") or 100.0)

    # 1. Ambil daftar butir soal dari bank soal terkait
    questions: List[dict] = []
    if bank_id:
        cursor.execute(
            """
            SELECT id, question_number, question_type, content, points, options, correct_answer
            FROM cbt_questions
            WHERE bank_id = %s
            ORDER BY question_number ASC, id ASC
            """,
            (bank_id,),
        )
        for q_row in cursor.fetchall():
            qd = dict(q_row)
            try:
                qd["options_parsed"] = json.loads(qd.get("options") or "[]")
            except Exception:
                qd["options_parsed"] = []
            qd["points"] = float(qd.get("points") or 1.0)
            qd["correct_answer_norm"] = (qd.get("correct_answer") or "").strip().upper()
            questions.append(qd)

    q_by_id = {q["id"]: q for q in questions}
    q_ids = list(q_by_id.keys())
    total_questions = len(questions)
    total_max_points = sum(q["points"] for q in questions) or 1.0

    # 2. Ambil daftar siswa target berdasarkan scope
    target_students = _load_target_students(cursor, exam, subject, scope, grade, class_name)
    student_map = {s["id"]: s for s in target_students}

    # 3. Ambil sesi ujian siswa pada exam_id ini (khusus subject_id terkait jika ada)
    subj_id = subject.get("id")
    if subj_id and subj_id > 0:
        cursor.execute(
            """
            SELECT * FROM cbt_exam_sessions
            WHERE exam_id = %s AND (subject_id = %s OR subject_id IS NULL)
            ORDER BY id ASC
            """,
            (exam_id, subj_id),
        )
    else:
        cursor.execute(
            """
            SELECT * FROM cbt_exam_sessions
            WHERE exam_id = %s
            ORDER BY id ASC
            """,
            (exam_id,),
        )
    sessions_by_student: Dict[int, dict] = {}
    for s_row in cursor.fetchall():
        sd = dict(s_row)
        sessions_by_student[sd["student_id"]] = sd
        # Jika ada siswa yang sudah ikut sesi tapi tidak ada di synced_students, tetap ikutkan jika cocok filter
        if sd["student_id"] not in student_map:
            s_cls = (sd.get("class_name") or "").strip()
            include_extra = True
            if scope == "kelas" and class_name and class_name != "all" and s_cls != class_name.strip():
                include_extra = False
            if include_extra and scope != "angkatan":
                extra_stu = {
                    "id": sd["student_id"],
                    "nis": sd.get("nisn") or "-",
                    "nisn": sd.get("nisn") or "-",
                    "name": sd.get("student_name") or "Peserta",
                    "class_name": s_cls or "-",
                    "grade": subject.get("grade") or exam.get("grade") or 10,
                    "major_code": None,
                    "gender": None,
                }
                target_students.append(extra_stu)
                student_map[sd["student_id"]] = extra_stu

    # 4. Ambil seluruh jawaban siswa untuk soal-soal di bank_id ini
    answers_by_student: Dict[int, Dict[int, dict]] = {}
    if q_ids:
        placeholders = ",".join(["%s"] * len(q_ids))
        cursor.execute(
            f"""
            SELECT student_id, question_id, student_answer, is_correct, points_earned
            FROM cbt_student_answers
            WHERE exam_id = %s AND question_id IN ({placeholders})
            """,
            tuple([exam_id] + q_ids),
        )
        for a_row in cursor.fetchall():
            ad = dict(a_row)
            answers_by_student.setdefault(ad["student_id"], {})[ad["question_id"]] = ad

    # 5. Hitung hasil tiap siswa
    student_results: List[dict] = []
    for stu in target_students:
        sid = stu["id"]
        sess = sessions_by_student.get(sid)
        stu_ans_map = answers_by_student.get(sid, {})

        has_answers = len(stu_ans_map) > 0
        raw_status = sess["status"] if sess else "not_started"
        # Untuk paket multi-mapel: anggap siswa sudah mengerjakan mapel ini jika punya jawaban pada soal bank ini
        # atau (untuk ujian tunggal) punya sesi submitted/in_progress
        is_single_exam = (subject.get("id") == 0) or (exam.get("bank_id") == bank_id and bank_id is not None)
        participated = has_answers or (sess is not None and (is_single_exam or raw_status == "submitted"))

        correct_count = 0
        wrong_count = 0
        blank_count = total_questions
        earned_points = 0.0
        answer_matrix: Dict[int, dict] = {}

        if total_questions > 0 and participated:
            blank_count = 0
            for q in questions:
                qid = q["id"]
                ans_rec = stu_ans_map.get(qid)
                ans_val = (ans_rec.get("student_answer") or "").strip() if ans_rec else ""
                if not ans_val:
                    blank_count += 1
                    answer_matrix[qid] = {"answer": "", "is_correct": False}
                else:
                    # Evaluasi kebenaran (gunakan is_correct tersimpan atau bandingkan kunci)
                    if ans_rec and ans_rec.get("is_correct") in (0, 1) and raw_status == "submitted":
                        is_ok = bool(ans_rec["is_correct"])
                    else:
                        is_ok = ans_val.upper() == q["correct_answer_norm"]
                    if is_ok:
                        correct_count += 1
                        earned_points += q["points"]
                    else:
                        wrong_count += 1
                    answer_matrix[qid] = {"answer": ans_val.upper(), "is_correct": is_ok}

            if has_answers:
                score_val = round((earned_points / total_max_points) * max_score_cfg, 2)
            elif sess and sess.get("score") is not None and raw_status == "submitted":
                score_val = round(float(sess["score"]), 2)
                correct_count = int(sess.get("total_correct") or 0)
                total_ans = int(sess.get("total_answered") or 0)
                wrong_count = max(0, total_ans - correct_count)
                blank_count = max(0, total_questions - total_ans)
            else:
                score_val = 0.0
        elif sess and raw_status == "submitted":
            score_val = round(float(sess.get("score") or 0.0), 2)
            correct_count = int(sess.get("total_correct") or 0)
            total_ans = int(sess.get("total_answered") or 0)
            wrong_count = max(0, total_ans - correct_count)
            blank_count = 0
        else:
            score_val = None

        status_label = {
            "submitted": "Selesai",
            "in_progress": "Mengerjakan",
            "locked": "Terkunci",
            "not_started": "Belum Mengerjakan",
        }.get(raw_status if participated else "not_started", "Belum Mengerjakan")

        passed = (score_val >= passing_score) if (score_val is not None) else None

        submitted_at = None
        if sess and sess.get("submitted_at"):
            submitted_at = (
                sess["submitted_at"].strftime("%d/%m/%Y %H:%M")
                if isinstance(sess["submitted_at"], datetime)
                else str(sess["submitted_at"])[:16]
            )

        student_results.append(
            {
                "student_id": sid,
                "nis": stu.get("nis") or "-",
                "nisn": stu.get("nisn") or "-",
                "name": stu.get("name") or "-",
                "class_name": stu.get("class_name") or "-",
                "grade": stu.get("grade") or subject.get("grade") or 10,
                "status": raw_status if participated else "not_started",
                "status_label": status_label,
                "participated": participated,
                "correct": correct_count if participated else 0,
                "wrong": wrong_count if participated else 0,
                "unanswered": blank_count if participated else total_questions,
                "score": score_val,
                "passed": passed,
                "lock_count": int(sess.get("lock_count") or 0) if sess else 0,
                "submitted_at": submitted_at,
                "room_name": (sess.get("room_name") if sess else None) or "-",
                "_answers": answer_matrix,
            }
        )

    # 6. Hitung Peringkat (hanya bagi peserta yang punya nilai)
    scored_students = [r for r in student_results if r["score"] is not None]
    scored_sorted = sorted(scored_students, key=lambda x: (-x["score"], -x["correct"], x["name"]))
    rank_map: Dict[int, int] = {}
    prev_score = None
    current_rank = 0
    for idx, sr in enumerate(scored_sorted, 1):
        if sr["score"] != prev_score:
            current_rank = idx
            prev_score = sr["score"]
        rank_map[sr["student_id"]] = current_rank

    for r in student_results:
        r["rank"] = rank_map.get(r["student_id"])

    # Urutkan tampilan default: Kelas ASC, Nama ASC
    student_results.sort(key=lambda x: (x["class_name"], x["name"]))

    # 7. Statistik Keseluruhan
    scores_list = [r["score"] for r in scored_students if r["score"] is not None]
    total_target = len(student_results)
    submitted_count = sum(1 for r in student_results if r["status"] == "submitted")
    participated_count = len(scored_students)
    not_started_count = total_target - participated_count
    passed_count = sum(1 for r in scored_students if r["passed"])
    failed_count = participated_count - passed_count

    if scores_list:
        avg_score = round(sum(scores_list) / len(scores_list), 2)
        highest_score = round(max(scores_list), 2)
        lowest_score = round(min(scores_list), 2)
        variance = sum((x - avg_score) ** 2 for x in scores_list) / len(scores_list)
        std_dev = round(math.sqrt(variance), 2)
        pass_rate = round((passed_count / len(scores_list)) * 100, 1)
    else:
        avg_score = 0.0
        highest_score = 0.0
        lowest_score = 0.0
        std_dev = 0.0
        pass_rate = 0.0

    stats = {
        "total_students": total_target,
        "participated_count": participated_count,
        "submitted_count": submitted_count,
        "not_started_count": not_started_count,
        "passing_score": passing_score,
        "max_score": max_score_cfg,
        "total_questions": total_questions,
        "avg_score": avg_score,
        "highest_score": highest_score,
        "lowest_score": lowest_score,
        "std_dev": std_dev,
        "passed_count": passed_count,
        "failed_count": failed_count,
        "pass_rate": pass_rate,
    }

    # 8. Rekap Per Kelas (berguna untuk scope Angkatan)
    cls_groups: Dict[str, List[dict]] = {}
    for r in student_results:
        cls_groups.setdefault(r["class_name"], []).append(r)

    class_breakdown = []
    for cname in sorted(cls_groups.keys()):
        grp = cls_groups[cname]
        grp_scored = [g for g in grp if g["score"] is not None]
        grp_scores = [g["score"] for g in grp_scored]
        grp_passed = sum(1 for g in grp_scored if g["passed"])
        class_breakdown.append(
            {
                "class_name": cname,
                "total_students": len(grp),
                "participated_count": len(grp_scored),
                "not_started_count": len(grp) - len(grp_scored),
                "avg_score": round(sum(grp_scores) / len(grp_scores), 2) if grp_scores else 0.0,
                "highest_score": round(max(grp_scores), 2) if grp_scores else 0.0,
                "lowest_score": round(min(grp_scores), 2) if grp_scores else 0.0,
                "passed_count": grp_passed,
                "failed_count": len(grp_scored) - grp_passed,
                "pass_rate": round((grp_passed / len(grp_scored)) * 100, 1) if grp_scored else 0.0,
            }
        )

    # 9. Analisis Butir Soal (Item Analysis Klasik: P, D Kelley 27%, Distractor A-E)
    # Tentukan Kelompok Atas (27%) dan Kelompok Bawah (27%) dari peserta yang mengerjakan
    n_eval = len(scored_sorted)
    group_size = max(1, round(n_eval * 0.27)) if n_eval >= 2 else 0
    upper_ids = {s["student_id"] for s in scored_sorted[:group_size]} if group_size > 0 else set()
    lower_ids = {s["student_id"] for s in scored_sorted[-group_size:]} if group_size > 0 else set()

    item_analysis: List[dict] = []
    difficulty_summary = {"mudah": 0, "sedang": 0, "sukar": 0, "belum_ada_data": 0}

    for q in questions:
        qid = q["id"]
        c_cnt = 0
        w_cnt = 0
        b_cnt = 0
        upper_correct = 0
        lower_correct = 0
        option_counts = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0, "LAINNYA": 0}

        for sr in scored_sorted:
            sid = sr["student_id"]
            ans_entry = sr["_answers"].get(qid, {"answer": "", "is_correct": False})
            ans_txt = ans_entry["answer"]
            if not ans_txt:
                b_cnt += 1
            else:
                if ans_txt in option_counts:
                    option_counts[ans_txt] += 1
                else:
                    option_counts["LAINNYA"] += 1

                if ans_entry["is_correct"]:
                    c_cnt += 1
                    if sid in upper_ids:
                        upper_correct += 1
                    if sid in lower_ids:
                        lower_correct += 1
                else:
                    w_cnt += 1

        if n_eval > 0:
            p_val = round(c_cnt / n_eval, 3)
            pct_correct = round((c_cnt / n_eval) * 100, 1)
            if p_val > 0.70:
                diff_label = "Mudah"
                difficulty_summary["mudah"] += 1
            elif p_val >= 0.30:
                diff_label = "Sedang"
                difficulty_summary["sedang"] += 1
            else:
                diff_label = "Sukar"
                difficulty_summary["sukar"] += 1
        else:
            p_val = None
            pct_correct = 0.0
            diff_label = "Belum Ada Data"
            difficulty_summary["belum_ada_data"] += 1

        if group_size > 0 and n_eval >= 4:
            p_upper = upper_correct / group_size
            p_lower = lower_correct / group_size
            d_val = round(p_upper - p_lower, 3)
            if d_val >= 0.40:
                disc_label = "Sangat Baik"
            elif d_val >= 0.30:
                disc_label = "Baik"
            elif d_val >= 0.20:
                disc_label = "Cukup"
            else:
                disc_label = "Jelek"
        else:
            d_val = None
            disc_label = "Peserta < 4" if n_eval > 0 else "Belum Ada Data"

        # Rekomendasi tindak lanjut
        if p_val is None:
            rekomendasi = "Menunggu peserta mengerjakan"
        elif d_val is not None:
            if d_val >= 0.30 and 0.25 <= p_val <= 0.80:
                rekomendasi = "Pertahankan (Baik)"
            elif d_val < 0.20 and (p_val < 0.20 or p_val > 0.85):
                rekomendasi = "Ganti / Revisi Total"
            elif d_val < 0.20:
                rekomendasi = "Revisi Pengecoh / Soal"
            else:
                rekomendasi = "Layak (Perlu Evaluasi Ringan)"
        else:
            if 0.30 <= p_val <= 0.70:
                rekomendasi = "Baik (Tingkat Sedang)"
            elif p_val > 0.70:
                rekomendasi = "Terlalu Mudah (Tinjau)"
            else:
                rekomendasi = "Terlalu Sukar (Tinjau)"

        preview_text = _strip_html(q.get("content") or "")
        if len(preview_text) > 120:
            preview_text = preview_text[:117] + "..."

        item_analysis.append(
            {
                "question_id": qid,
                "question_number": q["question_number"],
                "question_type": q.get("question_type") or "multiple_choice",
                "content_preview": preview_text,
                "correct_answer": q["correct_answer_norm"],
                "points": q["points"],
                "total_attempted": n_eval,
                "correct_count": c_cnt,
                "wrong_count": w_cnt,
                "blank_count": b_cnt,
                "pct_correct": pct_correct,
                "option_counts": option_counts,
                "difficulty_index": p_val,
                "difficulty_label": diff_label,
                "discrimination_index": d_val,
                "discrimination_label": disc_label,
                "recommendation": rekomendasi,
            }
        )

    return {
        "exam": exam,
        "subject": subject,
        "stats": stats,
        "class_breakdown": class_breakdown,
        "students": student_results,
        "questions": questions,
        "item_analysis": item_analysis,
        "difficulty_summary": difficulty_summary,
    }


def _scope_label(scope: str, grade: Optional[int], class_name: Optional[str]) -> str:
    if scope == "kelas" and class_name and class_name != "all":
        return f"Kelas {class_name}"
    if grade and grade > 0:
        return f"Angkatan Kelas {_grade_to_roman(grade)} (Tingkat {grade})"
    return "Seluruh Angkatan / Semua Kelas"


# -----------------------------------------------------------------------------
# API ENDPOINTS: SUMMARY & DETAIL PREVIEW
# -----------------------------------------------------------------------------
@router.get("/summary")
def get_results_summary(
    exam_id: Optional[int] = None,
    scope: str = Query("angkatan", pattern="^(angkatan|kelas)$"),
    grade: Optional[int] = None,
    class_name: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """
    Mengembalikan daftar paket ujian, opsi kelas/angkatan, dan ringkasan hasil tiap mata pelajaran
    berdasarkan filter Per Angkatan atau Per Kelas.
    """
    db = get_db()
    cursor = db.cursor()

    try:
        role = (current_user.get("role") or "").lower()
        is_admin = role in ("admin", "superadmin", "administrator", "staff")
        user_id = current_user.get("id")

        if is_admin:
            cursor.execute(
                """
                SELECT e.id, e.title, e.exam_type, e.grade, e.status, e.start_date, e.end_date,
                       (SELECT COUNT(*) FROM cbt_exam_sessions s WHERE s.exam_id = e.id AND s.status = 'submitted') AS submitted_count,
                       (SELECT COUNT(*) FROM cbt_exam_sessions s WHERE s.exam_id = e.id) AS session_count
                FROM cbt_exams e
                ORDER BY (SELECT COUNT(*) FROM cbt_exam_sessions s WHERE s.exam_id = e.id AND s.status = 'submitted') DESC,
                         (SELECT COUNT(*) FROM cbt_exam_sessions s WHERE s.exam_id = e.id) DESC,
                         e.id DESC
                """
            )
        else:
            cursor.execute(
                """
                SELECT e.id, e.title, e.exam_type, e.grade, e.status, e.start_date, e.end_date,
                       (SELECT COUNT(*) FROM cbt_exam_sessions s WHERE s.exam_id = e.id AND s.status = 'submitted') AS submitted_count,
                       (SELECT COUNT(*) FROM cbt_exam_sessions s WHERE s.exam_id = e.id) AS session_count
                FROM cbt_exams e
                WHERE e.created_by = %s
                   OR LOWER(COALESCE(e.exam_type, 'daily')) = 'daily'
                   OR EXISTS (SELECT 1 FROM cbt_exam_subjects sub WHERE sub.exam_id = e.id AND sub.teacher_id = %s)
                ORDER BY (SELECT COUNT(*) FROM cbt_exam_sessions s WHERE s.exam_id = e.id AND s.status = 'submitted') DESC,
                         (SELECT COUNT(*) FROM cbt_exam_sessions s WHERE s.exam_id = e.id) DESC,
                         e.id DESC
                """,
                (user_id, user_id),
            )
        exams_list = [dict(r) for r in cursor.fetchall()]

        if not exams_list:
            return {
                "success": True,
                "exams": [],
                "selected_exam": None,
                "available_grades": [],
                "available_classes": [],
                "subjects": [],
                "overview": {
                    "total_subjects": 0,
                    "total_students": 0,
                    "participated_count": 0,
                    "avg_score": 0.0,
                },
            }

        # Jika exam_id tidak diberikan secara eksplisit, prioritaskan paket ujian yang memiliki submission siswa
        selected_exam_id = exam_id
        if not selected_exam_id:
            exams_with_sub = [e for e in exams_list if (e.get("submitted_count") or 0) > 0]
            selected_exam_id = exams_with_sub[0]["id"] if exams_with_sub else exams_list[0]["id"]
        exam, subjects = _get_exam_and_subjects(cursor, selected_exam_id)

        # Ambil semua kelas & angkatan yang relevan dari siswa tersinkron
        cursor.execute(
            """
            SELECT DISTINCT class_name, grade
            FROM cbt_synced_students
            WHERE class_name IS NOT NULL AND class_name != '' AND class_name != '-'
            ORDER BY grade ASC, class_name ASC
            """
        )
        cls_rows = [dict(r) for r in cursor.fetchall()]
        available_grades = sorted({int(r["grade"]) for r in cls_rows if r.get("grade") is not None})
        # Tambahkan grade dari mapel jika belum ada
        for s in subjects:
            if s.get("grade") and int(s["grade"]) not in available_grades:
                available_grades.append(int(s["grade"]))
        available_grades.sort()

        available_classes = [
            {"class_name": r["class_name"], "grade": r.get("grade") or 10}
            for r in cls_rows
        ]

        # Hitung ringkasan untuk tiap mata pelajaran sesuai filter scope
        subject_summaries = []
        all_avgs = []
        max_students = 0
        max_participated = 0

        for subj in subjects:
            # Jika filter angkatan dipilih, hanya tampilkan mapel yang sesuai angkatan atau punya siswa di angkatan tsb
            if scope == "angkatan" and grade and grade > 0:
                if subj.get("grade") and int(subj["grade"]) != int(grade):
                    # Cek apakah ada target_classes di grade tsb
                    eval_check = _load_target_students(cursor, exam, subj, scope, grade, class_name)
                    if not eval_check:
                        continue
            elif scope == "kelas" and class_name and class_name != "all":
                s_targets = subj.get("target_classes") or []
                if s_targets and "all" not in s_targets and class_name.strip() not in s_targets:
                    continue

            ev = _compute_subject_evaluation(cursor, exam, subj, scope, grade, class_name)
            st = ev["stats"]
            if st["participated_count"] > 0:
                all_avgs.append(st["avg_score"])
            max_students = max(max_students, st["total_students"])
            max_participated = max(max_participated, st["participated_count"])

            subject_summaries.append(
                {
                    "id": subj["id"],
                    "exam_id": exam["id"],
                    "subject_name": subj["subject_name"],
                    "grade": subj.get("grade") or 10,
                    "teacher_name": subj.get("teacher_name") or "-",
                    "bank_id": subj.get("bank_id"),
                    "exam_date": subj.get("exam_date"),
                    "passing_score": st["passing_score"],
                    "total_questions": st["total_questions"],
                    "total_students": st["total_students"],
                    "participated_count": st["participated_count"],
                    "submitted_count": st["submitted_count"],
                    "avg_score": st["avg_score"],
                    "highest_score": st["highest_score"],
                    "lowest_score": st["lowest_score"],
                    "passed_count": st["passed_count"],
                    "pass_rate": st["pass_rate"],
                    "difficulty_summary": ev["difficulty_summary"],
                }
            )

        return {
            "success": True,
            "exams": exams_list,
            "selected_exam": {
                "id": exam["id"],
                "title": exam["title"],
                "exam_type": exam["exam_type"],
                "status": exam["status"],
                "start_date": exam.get("start_date"),
                "end_date": exam.get("end_date"),
            },
            "scope_label": _scope_label(scope, grade, class_name),
            "available_grades": available_grades,
            "available_classes": available_classes,
            "subjects": subject_summaries,
            "overview": {
                "total_subjects": len(subject_summaries),
                "total_students": max_students,
                "participated_count": max_participated,
                "avg_score": round(sum(all_avgs) / len(all_avgs), 2) if all_avgs else 0.0,
            },
        }
    finally:
        db.close()


@router.get("/detail")
def get_subject_result_detail(
    exam_id: int,
    subject_id: int = 0,
    scope: str = Query("angkatan", pattern="^(angkatan|kelas)$"),
    grade: Optional[int] = None,
    class_name: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Pratinjau lengkap Daftar Nilai Peserta dan Analisis Butir Soal untuk satu mata pelajaran."""
    db = get_db()
    cursor = db.cursor()
    try:
        exam, subjects = _get_exam_and_subjects(cursor, exam_id)
        subj = next((s for s in subjects if int(s["id"]) == int(subject_id)), None)
        if not subj:
            subj = subjects[0]

        ev = _compute_subject_evaluation(cursor, exam, subj, scope, grade, class_name)
        clean_students = [{k: v for k, v in s.items() if k != "_answers"} for s in ev["students"]]

        return {
            "success": True,
            "exam": {"id": exam["id"], "title": exam["title"], "exam_type": exam["exam_type"]},
            "subject": {
                "id": subj["id"],
                "subject_name": subj["subject_name"],
                "grade": subj.get("grade"),
                "teacher_name": subj.get("teacher_name") or "-",
                "bank_id": subj.get("bank_id"),
                "exam_date": subj.get("exam_date"),
                "passing_score": ev["stats"]["passing_score"],
            },
            "scope_label": _scope_label(scope, grade, class_name),
            "stats": ev["stats"],
            "class_breakdown": ev["class_breakdown"],
            "students": clean_students,
            "item_analysis": ev["item_analysis"],
            "difficulty_summary": ev["difficulty_summary"],
        }
    finally:
        db.close()


# -----------------------------------------------------------------------------
# EXCEL STYLING HELPERS (OPENPYXL)
# -----------------------------------------------------------------------------
THIN_SIDE = Side(border_style="thin", color="CBD5E1")
THIN_BORDER = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)
HEADER_FILL = PatternFill("solid", fgColor="1E3A8A")  # Navy/Blue 900
SUBHEADER_FILL = PatternFill("solid", fgColor="EFF6FF")  # Blue 50
ZEBRA_FILL = PatternFill("solid", fgColor="F8FAFC")
GREEN_FILL = PatternFill("solid", fgColor="DCFCE7")
RED_FILL = PatternFill("solid", fgColor="FEE2E2")
AMBER_FILL = PatternFill("solid", fgColor="FEF3C7")
GRAY_FILL = PatternFill("solid", fgColor="F1F5F9")

FONT_TITLE = Font(name="Calibri", size=13, bold=True, color="0F172A")
FONT_SUBTITLE = Font(name="Calibri", size=10, bold=True, color="1E3A8A")
FONT_META = Font(name="Calibri", size=9, color="334155")
FONT_HEADER = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
FONT_CELL = Font(name="Calibri", size=10, color="0F172A")
FONT_BOLD = Font(name="Calibri", size=10, bold=True, color="0F172A")
FONT_GREEN = Font(name="Calibri", size=10, bold=True, color="166534")
FONT_RED = Font(name="Calibri", size=10, bold=True, color="991B1B")
FONT_AMBER = Font(name="Calibri", size=10, bold=True, color="92400E")


def _auto_fit_columns(ws, min_width=8, max_width=48):
    for col_cells in ws.columns:
        col_letter = get_column_letter(col_cells[0].column)
        max_len = 0
        for cell in col_cells:
            val = "" if cell.value is None else str(cell.value)
            # Skip merged title rows (rows 1-3) for width calculation
            if cell.row <= 3:
                continue
            lines = val.split("\n")
            longest = max((len(l) for l in lines), default=0)
            if longest > max_len:
                max_len = longest
        ws.column_dimensions[col_letter].width = max(min_width, min(max_width, max_len + 3))


def _write_report_banner(ws, school: dict, title: str, meta_rows: List[tuple], total_cols: int) -> int:
    end_col = get_column_letter(max(total_cols, 6))
    ws.merge_cells(f"A1:{end_col}1")
    ws["A1"] = (school.get("school_name") or "SISTEM CBT SEKOLAH").upper()
    ws["A1"].font = FONT_TITLE
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 22

    ws.merge_cells(f"A2:{end_col}2")
    ws["A2"] = title
    ws["A2"].font = FONT_SUBTITLE
    ws["A2"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 19

    row_idx = 4
    for label, value in meta_rows:
        ws.cell(row=row_idx, column=1, value=label).font = FONT_BOLD
        ws.cell(row=row_idx, column=2, value=f": {value}").font = FONT_META
        ws.row_dimensions[row_idx].height = 16
        row_idx += 1

    return row_idx + 1


# -----------------------------------------------------------------------------
# EXCEL EXPORT 1: HASIL UJIAN PER MATA PELAJARAN (PER KELAS / PER ANGKATAN)
# -----------------------------------------------------------------------------
@router.get("/export/scores")
def export_scores_excel(
    exam_id: int,
    subject_id: int = 0,
    scope: str = Query("angkatan", pattern="^(angkatan|kelas)$"),
    grade: Optional[int] = None,
    class_name: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Download Hasil Ujian satu mata pelajaran (Per Kelas atau Per Angkatan) dalam format Excel (.xlsx)."""
    db = get_db()
    cursor = db.cursor()
    try:
        school = _get_school_profile(cursor)
        exam, subjects = _get_exam_and_subjects(cursor, exam_id)
        subj = next((s for s in subjects if int(s["id"]) == int(subject_id)), subjects[0])
        ev = _compute_subject_evaluation(cursor, exam, subj, scope, grade, class_name)
    finally:
        db.close()

    st = ev["stats"]
    scope_txt = _scope_label(scope, grade, class_name)

    wb = Workbook()
    ws = wb.active
    ws.title = "Hasil Ujian"

    headers = [
        "No", "NIS", "NISN", "Nama Peserta Didik", "Kelas",
        "Status", "Benar", "Salah", "Kosong", "Nilai",
        "Ketuntasan", "Peringkat", "Waktu Selesai"
    ]

    start_row = _write_report_banner(
        ws,
        school,
        f"DAFTAR HASIL UJIAN — {subj['subject_name'].upper()}",
        [
            ("Paket Ujian", exam["title"]),
            ("Mata Pelajaran", f"{subj['subject_name']} (Guru: {subj.get('teacher_name') or '-'})"),
            ("Ruang Lingkup", scope_txt),
            ("KKM / Total Soal", f"KKM {st['passing_score']}  |  {st['total_questions']} Butir Soal"),
            ("Statistik Ringkas", f"Peserta: {st['participated_count']}/{st['total_students']}  |  Rata-rata: {st['avg_score']}  |  Tertinggi: {st['highest_score']}  |  Terendah: {st['lowest_score']}  |  Tuntas: {st['passed_count']} ({st['pass_rate']}%)"),
            ("Dicetak Pada", datetime.now().strftime("%d/%m/%Y %H:%M")),
        ],
        len(headers),
    )

    # Header tabel
    ws.row_dimensions[start_row].height = 24
    for c_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=start_row, column=c_idx, value=h)
        cell.font = FONT_HEADER
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER

    # Baris data siswa
    cur_row = start_row + 1
    for idx, stu in enumerate(ev["students"], 1):
        ket = (
            "Tuntas" if stu["passed"] is True
            else "Belum Tuntas" if stu["passed"] is False
            else "-"
        )
        row_vals = [
            idx,
            stu["nis"],
            stu["nisn"],
            stu["name"],
            stu["class_name"],
            stu["status_label"],
            stu["correct"] if stu["participated"] else "-",
            stu["wrong"] if stu["participated"] else "-",
            stu["unanswered"] if stu["participated"] else "-",
            stu["score"] if stu["score"] is not None else "-",
            ket,
            stu["rank"] if stu["rank"] is not None else "-",
            stu["submitted_at"] or "-",
        ]
        ws.row_dimensions[cur_row].height = 19
        is_zebra = (idx % 2 == 0)
        for c_idx, val in enumerate(row_vals, 1):
            cell = ws.cell(row=cur_row, column=c_idx, value=val)
            cell.font = FONT_CELL
            cell.border = THIN_BORDER
            if is_zebra:
                cell.fill = ZEBRA_FILL

            if c_idx in (1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

            if c_idx == 10 and isinstance(val, (int, float)):
                cell.font = FONT_BOLD
                cell.number_format = "0.00"
            elif c_idx == 11:
                if val == "Tuntas":
                    cell.fill = GREEN_FILL
                    cell.font = FONT_GREEN
                elif val == "Belum Tuntas":
                    cell.fill = RED_FILL
                    cell.font = FONT_RED
        cur_row += 1

    # Baris Ringkasan Bawah
    cur_row += 1
    summary_pairs = [
        ("Rata-rata Nilai", st["avg_score"]),
        ("Nilai Tertinggi", st["highest_score"]),
        ("Nilai Terendah", st["lowest_score"]),
        ("Standar Deviasi", st["std_dev"]),
        ("Jumlah Tuntas", f"{st['passed_count']} siswa ({st['pass_rate']}%)"),
        ("Belum Tuntas", f"{st['failed_count']} siswa"),
    ]
    for s_label, s_val in summary_pairs:
        c1 = ws.cell(row=cur_row, column=4, value=s_label)
        c1.font = FONT_BOLD
        c1.fill = SUBHEADER_FILL
        c1.border = THIN_BORDER
        c2 = ws.cell(row=cur_row, column=5, value=s_val)
        c2.font = FONT_BOLD
        c2.alignment = Alignment(horizontal="center")
        c2.border = THIN_BORDER
        cur_row += 1

    _auto_fit_columns(ws)

    # Sheet 2: Rekap Per Kelas (jika lebih dari 1 kelas / scope angkatan)
    if len(ev["class_breakdown"]) > 1 or scope == "angkatan":
        ws2 = wb.create_sheet("Rekap Per Kelas")
        h2 = [
            "No", "Kelas", "Total Siswa", "Sudah Mengerjakan", "Belum Mengerjakan",
            "Rata-rata", "Tertinggi", "Terendah", "Tuntas", "Belum Tuntas", "% Ketuntasan"
        ]
        r2_start = _write_report_banner(
            ws2,
            school,
            f"REKAP PERBANDINGAN PER KELAS — {subj['subject_name'].upper()}",
            [
                ("Paket Ujian", exam["title"]),
                ("Ruang Lingkup", scope_txt),
                ("KKM", str(st["passing_score"])),
            ],
            len(h2),
        )
        ws2.row_dimensions[r2_start].height = 24
        for c_idx, h in enumerate(h2, 1):
            cell = ws2.cell(row=r2_start, column=c_idx, value=h)
            cell.font = FONT_HEADER
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = THIN_BORDER

        rr = r2_start + 1
        for i, cb in enumerate(ev["class_breakdown"], 1):
            vals = [
                i, cb["class_name"], cb["total_students"], cb["participated_count"],
                cb["not_started_count"], cb["avg_score"], cb["highest_score"], cb["lowest_score"],
                cb["passed_count"], cb["failed_count"], f"{cb['pass_rate']}%"
            ]
            ws2.row_dimensions[rr].height = 19
            for c_idx, v in enumerate(vals, 1):
                c = ws2.cell(row=rr, column=c_idx, value=v)
                c.font = FONT_BOLD if c_idx in (2, 6) else FONT_CELL
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.border = THIN_BORDER
                if i % 2 == 0:
                    c.fill = ZEBRA_FILL
            rr += 1
        _auto_fit_columns(ws2)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"Hasil_Ujian_{_safe_filename(subj['subject_name'])}_{_safe_filename(scope_txt)}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# -----------------------------------------------------------------------------
# EXCEL EXPORT 2: ANALISIS BUTIR SOAL + MATRIKS JAWABAN SISWA
# -----------------------------------------------------------------------------
@router.get("/export/analysis")
def export_analysis_excel(
    exam_id: int,
    subject_id: int = 0,
    scope: str = Query("angkatan", pattern="^(angkatan|kelas)$"),
    grade: Optional[int] = None,
    class_name: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Download Hasil Analisis Butir Soal (Tingkat Kesukaran, Daya Pembeda, Distractor & Matriks Jawaban) dalam Excel (.xlsx)."""
    db = get_db()
    cursor = db.cursor()
    try:
        school = _get_school_profile(cursor)
        exam, subjects = _get_exam_and_subjects(cursor, exam_id)
        subj = next((s for s in subjects if int(s["id"]) == int(subject_id)), subjects[0])
        ev = _compute_subject_evaluation(cursor, exam, subj, scope, grade, class_name)
    finally:
        db.close()

    st = ev["stats"]
    scope_txt = _scope_label(scope, grade, class_name)

    wb = Workbook()

    # ---------------- SHEET 1: ANALISIS BUTIR SOAL ----------------
    ws1 = wb.active
    ws1.title = "Analisis Butir Soal"
    h1 = [
        "No Soal", "Tipe", "Kunci", "Benar", "Salah", "Kosong", "% Benar",
        "Pilih A", "Pilih B", "Pilih C", "Pilih D", "Pilih E",
        "Indeks Kesukaran (P)", "Kategori Kesukaran",
        "Daya Pembeda (D)", "Kategori Daya Beda",
        "Rekomendasi", "Cuplikan Pertanyaan"
    ]
    r1_start = _write_report_banner(
        ws1,
        school,
        f"ANALISIS BUTIR SOAL — {subj['subject_name'].upper()}",
        [
            ("Paket Ujian", exam["title"]),
            ("Mata Pelajaran", f"{subj['subject_name']} (Guru: {subj.get('teacher_name') or '-'})"),
            ("Ruang Lingkup", scope_txt),
            ("Peserta Dianalisis", f"{st['participated_count']} peserta  |  Total Butir Soal: {st['total_questions']}"),
            ("Distribusi Kesukaran", f"Mudah: {ev['difficulty_summary']['mudah']}  |  Sedang: {ev['difficulty_summary']['sedang']}  |  Sukar: {ev['difficulty_summary']['sukar']}"),
            ("Dicetak Pada", datetime.now().strftime("%d/%m/%Y %H:%M")),
        ],
        len(h1),
    )

    ws1.row_dimensions[r1_start].height = 28
    for c_idx, h in enumerate(h1, 1):
        c = ws1.cell(row=r1_start, column=c_idx, value=h)
        c.font = FONT_HEADER
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = THIN_BORDER

    row_i = r1_start + 1
    for idx, item in enumerate(ev["item_analysis"], 1):
        oc = item["option_counts"]
        vals = [
            item["question_number"],
            item["question_type"],
            item["correct_answer"],
            item["correct_count"],
            item["wrong_count"],
            item["blank_count"],
            f"{item['pct_correct']}%",
            oc.get("A", 0),
            oc.get("B", 0),
            oc.get("C", 0),
            oc.get("D", 0),
            oc.get("E", 0),
            item["difficulty_index"] if item["difficulty_index"] is not None else "-",
            item["difficulty_label"],
            item["discrimination_index"] if item["discrimination_index"] is not None else "-",
            item["discrimination_label"],
            item["recommendation"],
            item["content_preview"],
        ]
        ws1.row_dimensions[row_i].height = 20
        for c_idx, v in enumerate(vals, 1):
            c = ws1.cell(row=row_i, column=c_idx, value=v)
            c.font = FONT_CELL
            c.border = THIN_BORDER
            if idx % 2 == 0:
                c.fill = ZEBRA_FILL
            c.alignment = Alignment(
                horizontal="left" if c_idx in (17, 18) else "center",
                vertical="center",
            )
            if c_idx == 3:
                c.font = FONT_BOLD
            elif c_idx == 14:
                if v == "Sedang":
                    c.fill = GREEN_FILL
                    c.font = FONT_GREEN
                elif v == "Mudah":
                    c.fill = SUBHEADER_FILL
                    c.font = FONT_SUBTITLE
                elif v == "Sukar":
                    c.fill = RED_FILL
                    c.font = FONT_RED
            elif c_idx == 16:
                if v in ("Sangat Baik", "Baik"):
                    c.fill = GREEN_FILL
                    c.font = FONT_GREEN
                elif v == "Cukup":
                    c.fill = AMBER_FILL
                    c.font = FONT_AMBER
                elif v == "Jelek":
                    c.fill = RED_FILL
                    c.font = FONT_RED
        row_i += 1

    _auto_fit_columns(ws1, min_width=7, max_width=52)

    # ---------------- SHEET 2: MATRIKS JAWABAN SISWA ----------------
    ws2 = wb.create_sheet("Matriks Jawaban Siswa")
    questions = ev["questions"]
    base_h = ["No", "NISN", "Nama Peserta", "Kelas"]
    q_h = [f"S{q['question_number']}" for q in questions]
    tail_h = ["Benar", "Salah", "Nilai", "Keterangan"]
    h2 = base_h + q_h + tail_h

    r2_start = _write_report_banner(
        ws2,
        school,
        f"MATRIKS JAWABAN PESERTA PER BUTIR SOAL — {subj['subject_name'].upper()}",
        [
            ("Paket Ujian", exam["title"]),
            ("Ruang Lingkup", scope_txt),
            ("Keterangan", "Hijau = Benar | Merah = Salah | Abu-abu = Kosong"),
        ],
        len(h2),
    )

    # Header kolom
    ws2.row_dimensions[r2_start].height = 22
    for c_idx, h in enumerate(h2, 1):
        c = ws2.cell(row=r2_start, column=c_idx, value=h)
        c.font = FONT_HEADER
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = THIN_BORDER

    # Baris Kunci Jawaban
    key_row = r2_start + 1
    ws2.row_dimensions[key_row].height = 19
    ws2.merge_cells(f"A{key_row}:D{key_row}")
    kc = ws2.cell(row=key_row, column=1, value="KUNCI JAWABAN")
    kc.font = FONT_BOLD
    kc.fill = SUBHEADER_FILL
    kc.alignment = Alignment(horizontal="right", vertical="center")
    for col_i in range(1, 5):
        ws2.cell(row=key_row, column=col_i).border = THIN_BORDER
        ws2.cell(row=key_row, column=col_i).fill = SUBHEADER_FILL

    for q_idx, q in enumerate(questions):
        c = ws2.cell(row=key_row, column=5 + q_idx, value=q["correct_answer_norm"])
        c.font = FONT_BOLD
        c.fill = SUBHEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = THIN_BORDER
    for col_i in range(5 + len(questions), len(h2) + 1):
        c = ws2.cell(row=key_row, column=col_i, value="-")
        c.fill = SUBHEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = THIN_BORDER

    # Baris setiap peserta yang berpartisipasi (atau semua peserta)
    cur_r = key_row + 1
    for idx, stu in enumerate(ev["students"], 1):
        ws2.row_dimensions[cur_r].height = 18
        base_vals = [idx, stu["nisn"], stu["name"], stu["class_name"]]
        for c_i, v in enumerate(base_vals, 1):
            c = ws2.cell(row=cur_r, column=c_i, value=v)
            c.font = FONT_CELL
            c.border = THIN_BORDER
            c.alignment = Alignment(horizontal="left" if c_i == 3 else "center", vertical="center")

        ans_map = stu["_answers"]
        for q_idx, q in enumerate(questions):
            c_col = 5 + q_idx
            if not stu["participated"]:
                cell = ws2.cell(row=cur_r, column=c_col, value="-")
                cell.fill = GRAY_FILL
                cell.font = FONT_META
            else:
                entry = ans_map.get(q["id"], {"answer": "", "is_correct": False})
                if not entry["answer"]:
                    cell = ws2.cell(row=cur_r, column=c_col, value="-")
                    cell.fill = GRAY_FILL
                    cell.font = FONT_META
                elif entry["is_correct"]:
                    cell = ws2.cell(row=cur_r, column=c_col, value=entry["answer"])
                    cell.fill = GREEN_FILL
                    cell.font = FONT_GREEN
                else:
                    cell = ws2.cell(row=cur_r, column=c_col, value=entry["answer"])
                    cell.fill = RED_FILL
                    cell.font = FONT_RED
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = THIN_BORDER

        tail_start = 5 + len(questions)
        ket = "Tuntas" if stu["passed"] is True else ("Belum Tuntas" if stu["passed"] is False else "-")
        tail_vals = [
            stu["correct"] if stu["participated"] else "-",
            stu["wrong"] if stu["participated"] else "-",
            stu["score"] if stu["score"] is not None else "-",
            ket,
        ]
        for t_i, v in enumerate(tail_vals):
            c = ws2.cell(row=cur_r, column=tail_start + t_i, value=v)
            c.font = FONT_BOLD if t_i == 2 else FONT_CELL
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = THIN_BORDER
            if t_i == 3:
                if v == "Tuntas":
                    c.fill = GREEN_FILL
                    c.font = FONT_GREEN
                elif v == "Belum Tuntas":
                    c.fill = RED_FILL
                    c.font = FONT_RED
        cur_r += 1

    # Baris Persentase Benar per Soal di bagian bawah
    ws2.row_dimensions[cur_r].height = 20
    ws2.merge_cells(f"A{cur_r}:D{cur_r}")
    pc = ws2.cell(row=cur_r, column=1, value="PERSENTASE BENAR (%)")
    pc.font = FONT_BOLD
    pc.alignment = Alignment(horizontal="right", vertical="center")
    for col_i in range(1, 5):
        ws2.cell(row=cur_r, column=col_i).fill = SUBHEADER_FILL
        ws2.cell(row=cur_r, column=col_i).border = THIN_BORDER
    for q_idx, item in enumerate(ev["item_analysis"]):
        c = ws2.cell(row=cur_r, column=5 + q_idx, value=f"{item['pct_correct']}%")
        c.font = FONT_BOLD
        c.fill = SUBHEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = THIN_BORDER

    _auto_fit_columns(ws2, min_width=6, max_width=34)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"Analisis_Butir_Soal_{_safe_filename(subj['subject_name'])}_{_safe_filename(scope_txt)}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# -----------------------------------------------------------------------------
# EXCEL EXPORT 3: LEGER REKAP SEMUA MATA PELAJARAN (PER KELAS / PER ANGKATAN)
# -----------------------------------------------------------------------------
@router.get("/export/leger")
def export_leger_excel(
    exam_id: int,
    scope: str = Query("angkatan", pattern="^(angkatan|kelas)$"),
    grade: Optional[int] = None,
    class_name: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Download Leger Rekap Nilai seluruh mata pelajaran (Per Kelas / Per Angkatan) dalam 1 file Excel (.xlsx)."""
    db = get_db()
    cursor = db.cursor()
    try:
        school = _get_school_profile(cursor)
        exam, subjects = _get_exam_and_subjects(cursor, exam_id)

        # Filter mapel sesuai scope
        active_subjects = []
        eval_per_subject = []
        for subj in subjects:
            if scope == "angkatan" and grade and grade > 0:
                if subj.get("grade") and int(subj["grade"]) != int(grade):
                    if not _load_target_students(cursor, exam, subj, scope, grade, class_name):
                        continue
            elif scope == "kelas" and class_name and class_name != "all":
                s_targets = subj.get("target_classes") or []
                if s_targets and "all" not in s_targets and class_name.strip() not in s_targets:
                    continue
            ev = _compute_subject_evaluation(cursor, exam, subj, scope, grade, class_name)
            active_subjects.append(subj)
            eval_per_subject.append(ev)
    finally:
        db.close()

    scope_txt = _scope_label(scope, grade, class_name)

    # Gabungkan semua siswa unik lintas mapel
    students_index: Dict[int, dict] = {}
    scores_matrix: Dict[int, Dict[int, Optional[float]]] = {}
    for subj, ev in zip(active_subjects, eval_per_subject):
        for stu in ev["students"]:
            sid = stu["student_id"]
            if sid not in students_index:
                students_index[sid] = {
                    "student_id": sid,
                    "nis": stu["nis"],
                    "nisn": stu["nisn"],
                    "name": stu["name"],
                    "class_name": stu["class_name"],
                }
            scores_matrix.setdefault(sid, {})[subj["id"]] = stu["score"]

    rows_data = []
    for sid, info in students_index.items():
        subj_scores = [scores_matrix.get(sid, {}).get(s["id"]) for s in active_subjects]
        valid = [v for v in subj_scores if v is not None]
        total_val = round(sum(valid), 2) if valid else None
        avg_val = round(sum(valid) / len(valid), 2) if valid else None
        rows_data.append({**info, "subj_scores": subj_scores, "total": total_val, "avg": avg_val})

    # Peringkat berdasarkan rata-rata
    ranked = sorted([r for r in rows_data if r["avg"] is not None], key=lambda x: (-x["avg"], -(x["total"] or 0), x["name"]))
    rank_map = {r["student_id"]: i for i, r in enumerate(ranked, 1)}
    rows_data.sort(key=lambda x: (x["class_name"], x["name"]))

    wb = Workbook()
    ws = wb.active
    ws.title = "Leger Nilai"

    headers = ["No", "NIS", "NISN", "Nama Peserta", "Kelas"] + [s["subject_name"] for s in active_subjects] + ["Jumlah", "Rata-rata", "Peringkat"]
    start_row = _write_report_banner(
        ws,
        school,
        f"LEGER HASIL UJIAN SEMUA MATA PELAJARAN",
        [
            ("Paket Ujian", exam["title"]),
            ("Ruang Lingkup", scope_txt),
            ("Jumlah Mata Pelajaran", str(len(active_subjects))),
            ("Dicetak Pada", datetime.now().strftime("%d/%m/%Y %H:%M")),
        ],
        len(headers),
    )

    ws.row_dimensions[start_row].height = 26
    for c_idx, h in enumerate(headers, 1):
        c = ws.cell(row=start_row, column=c_idx, value=h)
        c.font = FONT_HEADER
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = THIN_BORDER

    cur_row = start_row + 1
    for idx, r in enumerate(rows_data, 1):
        vals = (
            [idx, r["nis"], r["nisn"], r["name"], r["class_name"]]
            + [v if v is not None else "-" for v in r["subj_scores"]]
            + [r["total"] if r["total"] is not None else "-", r["avg"] if r["avg"] is not None else "-", rank_map.get(r["student_id"], "-")]
        )
        ws.row_dimensions[cur_row].height = 19
        for c_idx, v in enumerate(vals, 1):
            c = ws.cell(row=cur_row, column=c_idx, value=v)
            c.font = FONT_BOLD if c_idx >= len(headers) - 2 else FONT_CELL
            c.alignment = Alignment(horizontal="left" if c_idx == 4 else "center", vertical="center")
            c.border = THIN_BORDER
            if idx % 2 == 0:
                c.fill = ZEBRA_FILL
            if isinstance(v, float):
                c.number_format = "0.00"
        cur_row += 1

    _auto_fit_columns(ws)

    # Sheet 2: Rekap Per Mata Pelajaran
    ws2 = wb.create_sheet("Rekap Per Mapel")
    h2 = ["No", "Mata Pelajaran", "Guru", "Tingkat", "Total Soal", "Peserta Selesai", "KKM", "Rata-rata", "Tertinggi", "Terendah", "% Ketuntasan"]
    r2_start = _write_report_banner(
        ws2,
        school,
        "RINGKASAN STATISTIK PER MATA PELAJARAN",
        [("Paket Ujian", exam["title"]), ("Ruang Lingkup", scope_txt)],
        len(h2),
    )
    ws2.row_dimensions[r2_start].height = 24
    for c_idx, h in enumerate(h2, 1):
        c = ws2.cell(row=r2_start, column=c_idx, value=h)
        c.font = FONT_HEADER
        c.fill = HEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = THIN_BORDER

    rr = r2_start + 1
    for i, (subj, ev) in enumerate(zip(active_subjects, eval_per_subject), 1):
        st = ev["stats"]
        vals = [
            i, subj["subject_name"], subj.get("teacher_name") or "-", f"Kelas {_grade_to_roman(subj.get('grade'))}",
            st["total_questions"], f"{st['participated_count']}/{st['total_students']}",
            st["passing_score"], st["avg_score"], st["highest_score"], st["lowest_score"], f"{st['pass_rate']}%"
        ]
        ws2.row_dimensions[rr].height = 19
        for c_idx, v in enumerate(vals, 1):
            c = ws2.cell(row=rr, column=c_idx, value=v)
            c.font = FONT_BOLD if c_idx in (2, 8) else FONT_CELL
            c.alignment = Alignment(horizontal="left" if c_idx in (2, 3) else "center", vertical="center")
            c.border = THIN_BORDER
            if i % 2 == 0:
                c.fill = ZEBRA_FILL
        rr += 1
    _auto_fit_columns(ws2)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"Leger_Hasil_Ujian_{_safe_filename(exam['title'])}_{_safe_filename(scope_txt)}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
