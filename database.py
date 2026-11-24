import os
import re
import psycopg2
from psycopg2 import pool
from psycopg2.extras import DictCursor

# Konfigurasi Database CBT (PostgreSQL terpisah 100% dari db_sekolah SIAK)
CBT_DB_CONFIG = {
    "host": os.environ.get("CBT_DB_HOST", "localhost"),
    "port": int(os.environ.get("CBT_DB_PORT", "5432")),
    "user": os.environ.get("CBT_DB_USER", "postgres"),
    "password": os.environ.get("CBT_DB_PASSWORD", "root"),
    "dbname": os.environ.get("CBT_DB_NAME", "db_cbt"),
}

_connection_pool: pool.ThreadedConnectionPool | None = None


def _convert_qmark_to_pyformat(sql: str) -> str:
    """Konversi placeholder '?' menjadi '%s' di luar string literal SQL secara aman."""
    if "?" not in sql:
        return sql
    out = []
    in_single = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            out.append(ch)
            if in_single and i + 1 < n and sql[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            in_single = not in_single
        elif ch == "?" and not in_single:
            out.append("%s")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


class PGCursorWrapper:
    """Wrapper DictCursor agar kompatibel penuh dengan akses row[0], row['col'], dict(row), dan ?/%s."""

    def __init__(self, raw_cursor):
        self._cur = raw_cursor
        self.lastrowid = None

    def execute(self, query: str, params=None):
        pg_query = _convert_qmark_to_pyformat(query)
        if params is None:
            self._cur.execute(pg_query)
        else:
            self._cur.execute(pg_query, params)
        return self

    def executemany(self, query: str, seq_of_params):
        pg_query = _convert_qmark_to_pyformat(query)
        self._cur.executemany(pg_query, seq_of_params)
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def fetchmany(self, size=None):
        return self._cur.fetchmany(size)

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def close(self):
        self._cur.close()

    def __iter__(self):
        return iter(self._cur)


class PGConnectionWrapper:
    """Wrapper koneksi Pooled PostgreSQL yang mengembalikan koneksi ke pool saat close()."""

    def __init__(self, raw_conn, conn_pool: pool.ThreadedConnectionPool):
        self._conn = raw_conn
        self._pool = conn_pool
        self._closed = False

    def cursor(self):
        return PGCursorWrapper(self._conn.cursor(cursor_factory=DictCursor))

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                # Pastikan tidak ada transaksi menggantung sebelum dikembalikan ke pool
                if self._conn.status != psycopg2.extensions.STATUS_READY:
                    self._conn.rollback()
            except Exception:
                pass
            try:
                self._pool.putconn(self._conn)
            except Exception:
                try:
                    self._conn.close()
                except Exception:
                    pass


def ensure_database_exists():
    """Memastikan database terpisah 'db_cbt' sudah ada di server PostgreSQL."""
    target_db = CBT_DB_CONFIG["dbname"]
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", target_db):
        raise ValueError(f"Nama database CBT tidak valid: {target_db}")

    admin_conn = psycopg2.connect(
        host=CBT_DB_CONFIG["host"],
        port=CBT_DB_CONFIG["port"],
        user=CBT_DB_CONFIG["user"],
        password=CBT_DB_CONFIG["password"],
        dbname="postgres",
    )
    admin_conn.autocommit = True
    try:
        cur = admin_conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
        if not cur.fetchone():
            cur.execute(f'CREATE DATABASE "{target_db}"')
            print(f"Database PostgreSQL terpisah '{target_db}' berhasil dibuat!")
        cur.close()
    finally:
        admin_conn.close()


def _get_pool() -> pool.ThreadedConnectionPool:
    global _connection_pool
    if _connection_pool is None:
        ensure_database_exists()
        _connection_pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=50,
            host=CBT_DB_CONFIG["host"],
            port=CBT_DB_CONFIG["port"],
            user=CBT_DB_CONFIG["user"],
            password=CBT_DB_CONFIG["password"],
            dbname=CBT_DB_CONFIG["dbname"],
        )
    return _connection_pool


def get_db() -> PGConnectionWrapper:
    p = _get_pool()
    raw_conn = p.getconn()
    return PGConnectionWrapper(raw_conn, p)


def init_db():
    ensure_database_exists()
    conn = get_db()
    cursor = conn.cursor()

    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS cbt_synced_students (
            id INTEGER PRIMARY KEY,
            nis TEXT,
            nisn TEXT,
            nik TEXT,
            name TEXT NOT NULL,
            class_id INTEGER,
            class_name TEXT,
            grade INTEGER,
            major_code TEXT,
            gender TEXT,
            photo TEXT,
            exam_password TEXT,
            synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_synced_teachers (
            id INTEGER PRIMARY KEY,
            nip TEXT,
            name TEXT NOT NULL,
            email TEXT,
            synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_synced_classes (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            grade INTEGER,
            major_code TEXT,
            student_count INTEGER DEFAULT 0,
            synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_synced_teacher_classes (
            id SERIAL PRIMARY KEY,
            teacher_id INTEGER,
            teacher_name TEXT NOT NULL,
            nip TEXT,
            subject_id INTEGER,
            subject_name TEXT NOT NULL,
            class_id INTEGER,
            class_name TEXT NOT NULL,
            grade INTEGER DEFAULT 10,
            synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_synced_school_profile (
            id INTEGER PRIMARY KEY,
            school_name TEXT,
            npsn TEXT,
            logo TEXT,
            address TEXT,
            phone TEXT,
            email TEXT,
            district TEXT,
            regency TEXT,
            province TEXT,
            postal_code TEXT,
            accreditation TEXT,
            headmaster_name TEXT,
            headmaster_nip TEXT,
            letterhead TEXT,
            headmaster_signature TEXT,
            school_type TEXT,
            synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_question_banks (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            subject_name TEXT NOT NULL,
            grade INTEGER DEFAULT 10,
            teacher_id INTEGER,
            teacher_name TEXT,
            total_questions INTEGER DEFAULT 0,
            origin TEXT DEFAULT 'self',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_questions (
            id SERIAL PRIMARY KEY,
            bank_id INTEGER NOT NULL REFERENCES cbt_question_banks (id) ON DELETE CASCADE,
            question_number INTEGER NOT NULL,
            question_type TEXT DEFAULT 'multiple_choice',
            content TEXT NOT NULL,
            image_url TEXT,
            audio_url TEXT,
            points DOUBLE PRECISION DEFAULT 1.0,
            options TEXT NOT NULL,
            correct_answer TEXT NOT NULL,
            explanation TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_exams (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            exam_type TEXT NOT NULL,
            bank_id INTEGER REFERENCES cbt_question_banks (id) ON DELETE SET NULL,
            subject_name TEXT,
            grade INTEGER DEFAULT 10,
            target_classes TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            duration_minutes INTEGER DEFAULT 60,
            token TEXT NOT NULL,
            is_token_active INTEGER DEFAULT 1,
            token_refresh_interval INTEGER DEFAULT 15,
            token_updated_at TEXT,
            active_subject_id INTEGER,
            randomize_questions INTEGER DEFAULT 1,
            randomize_options INTEGER DEFAULT 1,
            show_results INTEGER DEFAULT 1,
            max_violations INTEGER DEFAULT 3,
            status TEXT DEFAULT 'draft',
            created_by INTEGER,
            created_by_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_exam_subjects (
            id SERIAL PRIMARY KEY,
            exam_id INTEGER NOT NULL REFERENCES cbt_exams (id) ON DELETE CASCADE,
            subject_name TEXT NOT NULL,
            grade INTEGER DEFAULT 10,
            teacher_id INTEGER,
            teacher_name TEXT,
            duration_minutes INTEGER DEFAULT 90,
            total_questions INTEGER DEFAULT 0,
            passing_score DOUBLE PRECISION DEFAULT 75.0,
            max_score DOUBLE PRECISION DEFAULT 100.0,
            bank_id INTEGER REFERENCES cbt_question_banks (id) ON DELETE SET NULL,
            exam_date TEXT,
            start_time TEXT,
            end_time TEXT,
            target_classes TEXT DEFAULT '[]',
            status TEXT DEFAULT 'pending_questions',
            session_status TEXT DEFAULT 'idle',
            session_started_at TEXT,
            session_ended_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_exam_sessions (
            id SERIAL PRIMARY KEY,
            exam_id INTEGER NOT NULL REFERENCES cbt_exams (id) ON DELETE CASCADE,
            student_id INTEGER NOT NULL,
            student_name TEXT NOT NULL,
            class_name TEXT,
            nisn TEXT,
            room_name TEXT DEFAULT 'Ruang 01',
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            remaining_seconds INTEGER,
            status TEXT DEFAULT 'not_started',
            lock_reason TEXT,
            lock_count INTEGER DEFAULT 0,
            device_id TEXT,
            ip_address TEXT,
            score DOUBLE PRECISION DEFAULT 0.0,
            total_correct INTEGER DEFAULT 0,
            total_answered INTEGER DEFAULT 0,
            subject_id INTEGER,
            submitted_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_student_answers (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES cbt_exam_sessions (id) ON DELETE CASCADE,
            exam_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL REFERENCES cbt_questions (id) ON DELETE CASCADE,
            student_answer TEXT,
            is_doubtful INTEGER DEFAULT 0,
            is_correct INTEGER DEFAULT 0,
            points_earned DOUBLE PRECISION DEFAULT 0.0,
            answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (session_id, question_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_violations (
            id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES cbt_exam_sessions (id) ON DELETE CASCADE,
            exam_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            violation_type TEXT NOT NULL,
            details TEXT,
            occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_rooms (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            capacity INTEGER DEFAULT 36,
            location TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_sessions (
            id SERIAL PRIMARY KEY,
            session_name TEXT NOT NULL UNIQUE,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_student_allocations (
            id SERIAL PRIMARY KEY,
            room_id INTEGER,
            student_id INTEGER NOT NULL UNIQUE REFERENCES cbt_synced_students (id) ON DELETE CASCADE,
            student_name TEXT NOT NULL,
            class_name TEXT,
            nisn TEXT,
            room_name TEXT NOT NULL,
            session_name TEXT NOT NULL,
            seat_number INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_supervisor_assignments (
            id SERIAL PRIMARY KEY,
            exam_date TEXT NOT NULL,
            room_name TEXT NOT NULL,
            session_name TEXT NOT NULL,
            supervisor1_name TEXT,
            supervisor2_name TEXT,
            supervisor3_name TEXT,
            proctor_name TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (exam_date, room_name, session_name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_backup_supervisors (
            id SERIAL PRIMARY KEY,
            exam_date TEXT NOT NULL,
            session_name TEXT NOT NULL,
            teacher_name TEXT NOT NULL,
            order_num INTEGER DEFAULT 1,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (exam_date, session_name, teacher_name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_selected_supervisors (
            id SERIAL PRIMARY KEY,
            teacher_id INTEGER NOT NULL UNIQUE,
            teacher_name TEXT NOT NULL,
            nip TEXT,
            email TEXT,
            is_active INTEGER DEFAULT 1,
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_sas_schedules (
            id SERIAL PRIMARY KEY,
            exam_date TEXT NOT NULL,
            day_name TEXT NOT NULL,
            period_number INTEGER NOT NULL,
            subject_name TEXT NOT NULL,
            grade INTEGER DEFAULT 10,
            bank_id INTEGER,
            duration_minutes INTEGER DEFAULT 90,
            start_time TEXT DEFAULT '07:30',
            end_time TEXT DEFAULT '09:00',
            token TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_system_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            app_name TEXT DEFAULT 'CBT SEKOLAH',
            app_tagline TEXT DEFAULT 'Ujian Mandiri & SAS',
            app_description TEXT DEFAULT 'Sistem CBT Mandiri Sekolah Terpadu dengan Fitur Anti-Kecurangan & Isolasi Server Mandiri.',
            logo_url TEXT DEFAULT '',
            favicon_url TEXT DEFAULT '',
            copyright_text TEXT DEFAULT 'Sistem CBT Ujian Sekolah Mandiri',
            timezone TEXT DEFAULT 'Asia/Makassar',
            maintenance_mode INTEGER DEFAULT 0,
            maintenance_message TEXT DEFAULT 'Sistem CBT sedang dalam pemeliharaan berkala. Silakan coba beberapa saat lagi.',
            academic_year TEXT DEFAULT '2025/2026',
            semester TEXT DEFAULT 'Genap',
            default_duration_minutes INTEGER DEFAULT 90,
            allow_dual_login INTEGER DEFAULT 1,
            show_score_after_submit INTEGER DEFAULT 1,
            anticheat_enabled INTEGER DEFAULT 1,
            anticheat_fullscreen INTEGER DEFAULT 1,
            anticheat_tab_switch INTEGER DEFAULT 1,
            anticheat_window_blur INTEGER DEFAULT 1,
            anticheat_block_right_click INTEGER DEFAULT 1,
            anticheat_block_shortcuts INTEGER DEFAULT 1,
            anticheat_block_copy_paste INTEGER DEFAULT 1,
            anticheat_single_device INTEGER DEFAULT 1,
            anticheat_auto_lock INTEGER DEFAULT 1,
            anticheat_max_violations INTEGER DEFAULT 3,
            anticheat_time_away_seconds INTEGER DEFAULT 5,
            siak_api_url TEXT DEFAULT 'http://127.0.0.1:5000',
            siak_pg_host TEXT DEFAULT 'localhost',
            siak_pg_port INTEGER DEFAULT 5432,
            siak_pg_user TEXT DEFAULT 'postgres',
            siak_pg_password TEXT DEFAULT 'root',
            siak_pg_dbname TEXT DEFAULT 'db_sekolah',
            sync_preserve_exam_passwords INTEGER DEFAULT 1,
            sync_include_students INTEGER DEFAULT 1,
            sync_include_teachers INTEGER DEFAULT 1,
            sync_include_classes INTEGER DEFAULT 1,
            sync_include_school_profile INTEGER DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_notifications (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            teacher_id INTEGER,
            teacher_name TEXT,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT DEFAULT 'assignment',
            link TEXT DEFAULT '/bank-soal',
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_room_attendance (
            id SERIAL PRIMARY KEY,
            exam_date TEXT NOT NULL,
            session_name TEXT NOT NULL,
            room_name TEXT NOT NULL,
            subject_name TEXT,
            student_id INTEGER NOT NULL,
            student_name TEXT NOT NULL,
            class_name TEXT,
            nisn TEXT,
            status TEXT DEFAULT 'H',
            notes TEXT,
            updated_by TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (exam_date, session_name, room_name, student_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cbt_room_berita_acara (
            id SERIAL PRIMARY KEY,
            exam_date TEXT NOT NULL,
            session_name TEXT NOT NULL,
            room_name TEXT NOT NULL,
            subject_name TEXT,
            total_registered INTEGER DEFAULT 0,
            total_present INTEGER DEFAULT 0,
            total_absent INTEGER DEFAULT 0,
            absent_students TEXT,
            supervisor1_name TEXT,
            supervisor2_name TEXT,
            proctor_name TEXT,
            notes TEXT,
            submitted_by TEXT,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (exam_date, session_name, room_name)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_sessions_exam_student ON cbt_exam_sessions (exam_id, student_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_status ON cbt_exam_sessions (status)",
        "CREATE INDEX IF NOT EXISTS idx_answers_session ON cbt_student_answers (session_id)",
        "CREATE INDEX IF NOT EXISTS idx_questions_bank ON cbt_questions (bank_id)",
        "CREATE INDEX IF NOT EXISTS idx_allocations_room_session ON cbt_student_allocations (room_name, session_name)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_teacher ON cbt_notifications (teacher_id, teacher_name)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_is_read ON cbt_notifications (is_read)",
        "CREATE INDEX IF NOT EXISTS idx_room_att_lookup ON cbt_room_attendance (exam_date, session_name, room_name)",
        "CREATE INDEX IF NOT EXISTS idx_room_ba_lookup ON cbt_room_berita_acara (exam_date, session_name, room_name)",
        "ALTER TABLE cbt_question_banks ADD COLUMN IF NOT EXISTS origin TEXT DEFAULT 'self'",
        "ALTER TABLE cbt_exam_sessions ADD COLUMN IF NOT EXISTS unlock_code TEXT",
        "ALTER TABLE cbt_exam_sessions ADD COLUMN IF NOT EXISTS device_info TEXT",
        "ALTER TABLE cbt_exam_sessions ADD COLUMN IF NOT EXISTS browser_info TEXT",
        "ALTER TABLE cbt_exam_sessions ADD COLUMN IF NOT EXISTS connection_quality TEXT DEFAULT 'stabil'",
        "ALTER TABLE cbt_exam_sessions ADD COLUMN IF NOT EXISTS ping_ms INTEGER DEFAULT 25",
        "ALTER TABLE cbt_exam_sessions ADD COLUMN IF NOT EXISTS last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE cbt_exam_sessions ADD COLUMN IF NOT EXISTS subject_id INTEGER",
        "ALTER TABLE cbt_exams ADD COLUMN IF NOT EXISTS previous_token TEXT",
        "ALTER TABLE cbt_exam_sessions DROP CONSTRAINT IF EXISTS cbt_exam_sessions_exam_id_student_id_key",
        "CREATE UNIQUE INDEX IF NOT EXISTS cbt_exam_sessions_exam_student_subject_idx ON cbt_exam_sessions (exam_id, student_id, COALESCE(subject_id, 0))",
        "ALTER TABLE cbt_system_settings ADD COLUMN IF NOT EXISTS anticheat_time_away_seconds INTEGER DEFAULT 5",
        "ALTER TABLE cbt_questions ADD COLUMN IF NOT EXISTS lock_order INTEGER DEFAULT 0",
        "ALTER TABLE cbt_questions ADD COLUMN IF NOT EXISTS randomize_options_mode TEXT DEFAULT 'default'",
        "ALTER TABLE cbt_questions ADD COLUMN IF NOT EXISTS difficulty TEXT DEFAULT 'sedang'",
        "ALTER TABLE cbt_questions ADD COLUMN IF NOT EXISTS topic TEXT DEFAULT ''",
        "ALTER TABLE cbt_questions ADD COLUMN IF NOT EXISTS layout TEXT DEFAULT 'vertical'",
        "ALTER TABLE cbt_questions ADD COLUMN IF NOT EXISTS is_required INTEGER DEFAULT 0",
        "ALTER TABLE cbt_exam_subjects ADD COLUMN IF NOT EXISTS randomize_questions INTEGER DEFAULT NULL",
        "ALTER TABLE cbt_exam_subjects ADD COLUMN IF NOT EXISTS randomize_options INTEGER DEFAULT NULL",
        "ALTER TABLE cbt_question_banks ADD COLUMN IF NOT EXISTS randomize_questions INTEGER DEFAULT 1",
        "ALTER TABLE cbt_question_banks ADD COLUMN IF NOT EXISTS randomize_options INTEGER DEFAULT 1",
        "ALTER TABLE cbt_question_banks ADD COLUMN IF NOT EXISTS show_score INTEGER DEFAULT 1",
        "ALTER TABLE cbt_question_banks ADD COLUMN IF NOT EXISTS show_explanation INTEGER DEFAULT 0",
        "ALTER TABLE cbt_question_banks ADD COLUMN IF NOT EXISTS duration_minutes INTEGER DEFAULT 90",
        "ALTER TABLE cbt_question_banks ADD COLUMN IF NOT EXISTS passing_score DOUBLE PRECISION DEFAULT 75.0",
        "ALTER TABLE cbt_question_banks ADD COLUMN IF NOT EXISTS max_violations INTEGER DEFAULT 3",
        "ALTER TABLE cbt_exam_subjects ADD COLUMN IF NOT EXISTS show_score INTEGER DEFAULT NULL",
        "ALTER TABLE cbt_exam_subjects ADD COLUMN IF NOT EXISTS show_explanation INTEGER DEFAULT NULL",
    ]

    for stmt in ddl_statements:
        cursor.execute(stmt)

    # Seed data default Ruangan & Sesi jika masih kosong
    cursor.execute("SELECT COUNT(*) FROM cbt_rooms")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO cbt_rooms (name, capacity, location) VALUES (%s, %s, %s) ON CONFLICT (name) DO NOTHING",
            [
                ("Lab Komputer 1", 36, "Gedung A Lantai 2"),
                ("Lab Komputer 2", 36, "Gedung A Lantai 2"),
                ("Lab Komputer 3", 36, "Gedung B Lantai 1"),
            ],
        )

    cursor.execute("SELECT COUNT(*) FROM cbt_sessions")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO cbt_sessions (session_name, start_time, end_time) VALUES (%s, %s, %s) ON CONFLICT (session_name) DO NOTHING",
            [
                ("Sesi 1", "07:30", "09:30"),
                ("Sesi 2", "10:00", "12:00"),
                ("Sesi 3", "13:00", "15:00"),
            ],
        )

    # Seed baris default Pengaturan Sistem CBT (id = 1)
    cursor.execute("INSERT INTO cbt_system_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")

    conn.commit()
    conn.close()
    print(f"Database CBT (PostgreSQL '{CBT_DB_CONFIG['dbname']}' - Terpisah dari db_sekolah) berhasil diinisialisasi!")


DEFAULT_SYSTEM_SETTINGS = {
    "id": 1,
    "app_name": "CBT SEKOLAH",
    "app_tagline": "Ujian Mandiri & SAS",
    "app_description": "Sistem CBT Mandiri Sekolah Terpadu dengan Fitur Anti-Kecurangan & Isolasi Server Mandiri.",
    "logo_url": "",
    "favicon_url": "",
    "copyright_text": "Sistem CBT Ujian Sekolah Mandiri",
    "timezone": "Asia/Makassar",
    "maintenance_mode": 0,
    "maintenance_message": "Sistem CBT sedang dalam pemeliharaan berkala. Silakan coba beberapa saat lagi.",
    "academic_year": "2025/2026",
    "semester": "Genap",
    "default_duration_minutes": 90,
    "allow_dual_login": 1,
    "show_score_after_submit": 1,
    "anticheat_enabled": 1,
    "anticheat_fullscreen": 1,
    "anticheat_tab_switch": 1,
    "anticheat_window_blur": 1,
    "anticheat_block_right_click": 1,
    "anticheat_block_shortcuts": 1,
    "anticheat_block_copy_paste": 1,
    "anticheat_single_device": 1,
    "anticheat_auto_lock": 1,
    "anticheat_max_violations": 3,
    "anticheat_time_away_seconds": 5,
    "siak_api_url": "http://127.0.0.1:5000",
    "siak_pg_host": "localhost",
    "siak_pg_port": 5432,
    "siak_pg_user": "postgres",
    "siak_pg_password": "root",
    "siak_pg_dbname": "db_sekolah",
    "sync_preserve_exam_passwords": 1,
    "sync_include_students": 1,
    "sync_include_teachers": 1,
    "sync_include_classes": 1,
    "sync_include_school_profile": 1,
}


def get_system_settings(include_secrets: bool = False) -> dict:
    """Membaca pengaturan sistem CBT dari PostgreSQL db_cbt dengan fallback nilai default yang aman."""
    result = dict(DEFAULT_SYSTEM_SETTINGS)
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM cbt_system_settings WHERE id = 1")
        row = cur.fetchone()
        conn.close()
        if row:
            for k, v in dict(row).items():
                if v is not None:
                    result[k] = v
    except Exception as e:
        print(f"Peringatan: Gagal membaca cbt_system_settings: {e}")

    if not include_secrets:
        result["siak_pg_password_set"] = bool(result.get("siak_pg_password"))
        result.pop("siak_pg_password", None)

    return result


if __name__ == "__main__":
    init_db()
