"""
Script migrasi satu kali dari SQLite (cbt.db) ke PostgreSQL database terpisah (db_cbt).
Aman: tidak menyentuh db_sekolah milik SIAK, dan tidak menghapus cbt.db asli.
"""
import os
import sqlite3
from database import init_db, get_db, CBT_DB_CONFIG

SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cbt.db")

TABLES_IN_ORDER = [
    "cbt_synced_classes",
    "cbt_synced_students",
    "cbt_synced_teachers",
    "cbt_synced_school_profile",
    "cbt_question_banks",
    "cbt_questions",
    "cbt_exams",
    "cbt_exam_subjects",
    "cbt_exam_sessions",
    "cbt_student_answers",
    "cbt_violations",
    "cbt_rooms",
    "cbt_sessions",
    "cbt_student_allocations",
    "cbt_supervisor_assignments",
    "cbt_backup_supervisors",
    "cbt_selected_supervisors",
    "cbt_sas_schedules",
    "cbt_system_settings",
]

SERIAL_ID_TABLES = [
    "cbt_question_banks",
    "cbt_questions",
    "cbt_exams",
    "cbt_exam_subjects",
    "cbt_exam_sessions",
    "cbt_student_answers",
    "cbt_violations",
    "cbt_rooms",
    "cbt_sessions",
    "cbt_student_allocations",
    "cbt_supervisor_assignments",
    "cbt_backup_supervisors",
    "cbt_selected_supervisors",
    "cbt_sas_schedules",
]


def migrate():
    assert CBT_DB_CONFIG["dbname"] != "db_sekolah", "SAFETY ABORT: database CBT harus terpisah dari db_sekolah!"
    if not os.path.isfile(SQLITE_PATH):
        print("File cbt.db tidak ditemukan. Hanya menginisialisasi skema PostgreSQL db_cbt.")
        init_db()
        return

    print(f"1. Menginisialisasi database PostgreSQL terpisah '{CBT_DB_CONFIG['dbname']}'...")
    init_db()

    sq_conn = sqlite3.connect(SQLITE_PATH)
    sq_conn.row_factory = sqlite3.Row
    sq_cur = sq_conn.cursor()

    pg_conn = get_db()
    pg_cur = pg_conn.cursor()

    try:
        # Kosongkan tabel target (dalam urutan terbalik FK) agar migrasi idempotent & bersih
        for tbl in reversed(TABLES_IN_ORDER):
            pg_cur.execute(f'DELETE FROM "{tbl}"')

        print("2. Memindahkan seluruh data tabel dari SQLite cbt.db -> PostgreSQL db_cbt:")
        for tbl in TABLES_IN_ORDER:
            # Cek apakah tabel ada di SQLite
            sq_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,))
            if not sq_cur.fetchone():
                print(f"   - {tbl}: tidak ada di SQLite (dilewati)")
                continue

            # Ambil kolom yang ada di PostgreSQL untuk tabel ini
            pg_cur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s",
                (tbl,),
            )
            pg_cols = {r[0] for r in pg_cur.fetchall()}

            sq_cur.execute(f'SELECT * FROM "{tbl}"')
            rows = sq_cur.fetchall()
            if not rows:
                print(f"   - {tbl}: 0 baris")
                continue

            sq_cols = [c for c in rows[0].keys() if c in pg_cols]
            col_list = ", ".join(f'"{c}"' for c in sq_cols)
            placeholders = ", ".join(["%s"] * len(sq_cols))

            inserted = 0
            for row in rows:
                vals = []
                for c in sq_cols:
                    v = row[c]
                    # String kosong pada kolom timestamp ubah ke None agar valid di PostgreSQL
                    if v == "" and c in ("start_time", "end_time", "submitted_at", "synced_at", "created_at", "updated_at", "answered_at", "occurred_at", "assigned_at"):
                        v = None
                    vals.append(v)
                pg_cur.execute(f'INSERT INTO "{tbl}" ({col_list}) VALUES ({placeholders})', tuple(vals))
                inserted += 1

            print(f"   - {tbl}: {inserted} baris berhasil dipindahkan")

        # Pastikan cbt_system_settings minimal memiliki baris id=1
        pg_cur.execute("INSERT INTO cbt_system_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")

        # Sinkronisasi semua SERIAL sequence agar INSERT baru tidak bentrok ID
        print("3. Menyelaraskan PostgreSQL SERIAL sequences...")
        for tbl in SERIAL_ID_TABLES:
            pg_cur.execute(f'SELECT COALESCE(MAX(id), 0) FROM "{tbl}"')
            max_id = pg_cur.fetchone()[0]
            if max_id > 0:
                pg_cur.execute(f"SELECT setval(pg_get_serial_sequence('{tbl}', 'id'), %s, true)", (max_id,))
            else:
                pg_cur.execute(f"SELECT setval(pg_get_serial_sequence('{tbl}', 'id'), 1, false)")

        pg_conn.commit()
        print(f"SUKSES! Migrasi selesai 100% ke PostgreSQL database '{CBT_DB_CONFIG['dbname']}'.")
    except Exception as e:
        pg_conn.rollback()
        print("ERROR saat migrasi:", e)
        raise
    finally:
        sq_conn.close()
        pg_conn.close()


if __name__ == "__main__":
    migrate()
