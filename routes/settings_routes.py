import os
import io
import glob
import time
import shutil
import zipfile
import tempfile
import subprocess
from datetime import datetime
from typing import Optional
import httpx
import psycopg2
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from database import get_db, get_system_settings, CBT_DB_CONFIG
from auth import get_current_user

router = APIRouter(prefix="/api/cbt/settings", tags=["System Settings"])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

UPDATABLE_FIELDS = {
    "app_name",
    "app_tagline",
    "app_description",
    "logo_url",
    "favicon_url",
    "copyright_text",
    "timezone",
    "maintenance_mode",
    "maintenance_message",
    "academic_year",
    "semester",
    "default_duration_minutes",
    "allow_dual_login",
    "show_score_after_submit",
    "anticheat_enabled",
    "anticheat_fullscreen",
    "anticheat_tab_switch",
    "anticheat_window_blur",
    "anticheat_block_right_click",
    "anticheat_block_shortcuts",
    "anticheat_block_copy_paste",
    "anticheat_single_device",
    "anticheat_auto_lock",
    "anticheat_max_violations",
    "anticheat_time_away_seconds",
    "siak_api_url",
    "siak_pg_host",
    "siak_pg_port",
    "siak_pg_user",
    "siak_pg_password",
    "siak_pg_dbname",
    "sync_preserve_exam_passwords",
    "sync_include_students",
    "sync_include_teachers",
    "sync_include_classes",
    "sync_include_school_profile",
}

INT_BOOL_FIELDS = {
    "maintenance_mode",
    "allow_dual_login",
    "show_score_after_submit",
    "anticheat_enabled",
    "anticheat_fullscreen",
    "anticheat_tab_switch",
    "anticheat_window_blur",
    "anticheat_block_right_click",
    "anticheat_block_shortcuts",
    "anticheat_block_copy_paste",
    "anticheat_single_device",
    "anticheat_auto_lock",
    "sync_preserve_exam_passwords",
    "sync_include_students",
    "sync_include_teachers",
    "sync_include_classes",
    "sync_include_school_profile",
}

INT_NUMERIC_FIELDS = {
    "default_duration_minutes",
    "anticheat_max_violations",
    "siak_pg_port",
}


def _find_pg_tool(tool_name: str) -> str:
    """Mencari executable pg_dump / psql dari PATH atau direktori instalasi PostgreSQL Windows."""
    found = shutil.which(tool_name)
    if found:
        return found
    candidates = sorted(
        glob.glob(rf"C:\Program Files\PostgreSQL\*\bin\{tool_name}.exe"),
        reverse=True,
    )
    if candidates:
        return candidates[0]
    raise HTTPException(
        status_code=500,
        detail=f"Utilitas PostgreSQL '{tool_name}' tidak ditemukan di server. Pastikan PostgreSQL client tools terinstal.",
    )


def _require_admin(current_user: dict):
    role = str(current_user.get("role") or "").lower()
    if role in ("student", "siswa"):
        raise HTTPException(status_code=403, detail="Akses ditolak. Hanya Administrator yang dapat mengubah pengaturan sistem.")
    if role in ("teacher", "guru"):
        raise HTTPException(status_code=403, detail="Akses ditolak. Pengaturan sistem hanya dapat diakses oleh Administrator.")


def _format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


def _attach_school_info(settings_dict: dict) -> dict:
    """Melampirkan ringkasan profil sekolah tersinkron dari SIAK."""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM cbt_synced_school_profile ORDER BY id ASC LIMIT 1")
        row = cur.fetchone()
        if row:
            sch = dict(row)
            settings_dict["school_name"] = sch.get("school_name") or ""
            settings_dict["npsn"] = sch.get("npsn") or ""
            settings_dict["siak_logo"] = sch.get("logo") or ""
            settings_dict["school_address"] = sch.get("address") or ""
            settings_dict["school_phone"] = sch.get("phone") or ""
            settings_dict["school_email"] = sch.get("email") or ""
            settings_dict["district"] = sch.get("district") or ""
            settings_dict["regency"] = sch.get("regency") or ""
            settings_dict["province"] = sch.get("province") or ""
            settings_dict["postal_code"] = sch.get("postal_code") or ""
            settings_dict["accreditation"] = sch.get("accreditation") or ""
            settings_dict["headmaster_name"] = sch.get("headmaster_name") or ""
            settings_dict["headmaster_nip"] = sch.get("headmaster_nip") or ""
            settings_dict["letterhead"] = sch.get("letterhead") or ""
            settings_dict["headmaster_signature"] = sch.get("headmaster_signature") or ""
            settings_dict["school_synced_at"] = str(sch.get("synced_at")) if sch.get("synced_at") else None
    except Exception as e:
        print("Info: gagal melampirkan profil sekolah pada settings:", e)
    finally:
        conn.close()
    return settings_dict


@router.get("")
def get_settings():
    """Mengambil pengaturan sistem CBT (publik-aman untuk branding, login, & aturan anti-cheat ujian)."""
    data = get_system_settings(include_secrets=False)
    data = _attach_school_info(data)
    return {
        "success": True,
        "settings": data,
    }


@router.put("")
def update_settings(payload: dict, current_user: dict = Depends(get_current_user)):
    """Memperbarui pengaturan sistem CBT (Branding, Operasional, Anti-Cheating, Sinkronisasi SIAK)."""
    _require_admin(current_user)

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Format data pengaturan tidak valid.")

    updates = {}
    for key, val in payload.items():
        if key not in UPDATABLE_FIELDS:
            continue

        if key == "siak_pg_password":
            if val is None or str(val).strip() == "" or str(val).strip() == "••••••••":
                continue
            updates[key] = str(val)
            continue

        if key in INT_BOOL_FIELDS:
            updates[key] = 1 if bool(int(val) if isinstance(val, (int, float, str)) and str(val).isdigit() else val) else 0
        elif key in INT_NUMERIC_FIELDS:
            try:
                num = int(val)
                if key == "default_duration_minutes":
                    num = max(5, min(600, num))
                elif key == "anticheat_max_violations":
                    num = max(0, min(50, num))
                elif key == "siak_pg_port":
                    num = max(1, min(65535, num))
                updates[key] = num
            except (ValueError, TypeError):
                continue
        else:
            updates[key] = "" if val is None else str(val).strip()

    if not updates:
        data = _attach_school_info(get_system_settings(include_secrets=False))
        return {"success": True, "message": "Tidak ada perubahan yang disimpan.", "settings": data}

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO cbt_system_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
        set_clauses = [f"{col} = %s" for col in updates.keys()]
        set_clauses.append("updated_at = CURRENT_TIMESTAMP")
        values = list(updates.values())
        cur.execute(f"UPDATE cbt_system_settings SET {', '.join(set_clauses)} WHERE id = 1", tuple(values))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Gagal menyimpan pengaturan sistem: {str(e)}")
    finally:
        conn.close()

    data = _attach_school_info(get_system_settings(include_secrets=False))
    return {
        "success": True,
        "message": "Pengaturan sistem CBT berhasil diperbarui.",
        "settings": data,
    }


class TestSiakRequest(BaseModel):
    siak_api_url: Optional[str] = None
    siak_pg_host: Optional[str] = None
    siak_pg_port: Optional[int] = None
    siak_pg_user: Optional[str] = None
    siak_pg_password: Optional[str] = None
    siak_pg_dbname: Optional[str] = None


@router.post("/test-siak")
async def test_siak_connection(req: Optional[TestSiakRequest] = None, current_user: dict = Depends(get_current_user)):
    """Menguji koneksi live ke Server API SIAK (HTTP) dan Database SIAK (PostgreSQL)."""
    _require_admin(current_user)
    saved = get_system_settings(include_secrets=True)

    api_url = ((req.siak_api_url if req and req.siak_api_url else saved.get("siak_api_url")) or "http://127.0.0.1:5000").rstrip("/")
    pg_host = (req.siak_pg_host if req and req.siak_pg_host else saved.get("siak_pg_host")) or "localhost"
    pg_port = int((req.siak_pg_port if req and req.siak_pg_port else saved.get("siak_pg_port")) or 5432)
    pg_user = (req.siak_pg_user if req and req.siak_pg_user else saved.get("siak_pg_user")) or "postgres"
    pg_password = (
        req.siak_pg_password
        if (req and req.siak_pg_password and req.siak_pg_password != "••••••••")
        else saved.get("siak_pg_password", "root")
    )
    pg_dbname = (req.siak_pg_dbname if req and req.siak_pg_dbname else saved.get("siak_pg_dbname")) or "db_sekolah"

    api_status = {"online": False, "latency_ms": None, "status_code": None, "url": api_url, "error": None}
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{api_url}/")
            api_status["latency_ms"] = round((time.perf_counter() - t0) * 1000)
            api_status["status_code"] = resp.status_code
            api_status["online"] = resp.status_code < 500
    except Exception as e:
        api_status["error"] = str(e)

    db_status = {
        "online": False,
        "latency_ms": None,
        "host": pg_host,
        "port": pg_port,
        "dbname": pg_dbname,
        "students_count": None,
        "teachers_count": None,
        "classes_count": None,
        "error": None,
    }
    t1 = time.perf_counter()
    try:
        pg_conn = psycopg2.connect(
            host=pg_host,
            port=pg_port,
            user=pg_user,
            password=pg_password,
            dbname=pg_dbname,
            connect_timeout=3,
        )
        pg_cur = pg_conn.cursor()
        pg_cur.execute("SELECT COUNT(*) FROM students WHERE is_active = 1 OR status = 'aktif' OR status IS NULL")
        db_status["students_count"] = pg_cur.fetchone()[0]
        pg_cur.execute("SELECT COUNT(*) FROM teachers WHERE is_active = 1 OR is_active IS NULL")
        db_status["teachers_count"] = pg_cur.fetchone()[0]
        pg_cur.execute("SELECT COUNT(DISTINCT class_name) FROM classes WHERE class_name IS NOT NULL AND class_name != ''")
        db_status["classes_count"] = pg_cur.fetchone()[0]
        pg_cur.close()
        pg_conn.close()
        db_status["latency_ms"] = round((time.perf_counter() - t1) * 1000)
        db_status["online"] = True
    except Exception as e:
        db_status["error"] = str(e)

    return {
        "success": True,
        "api": api_status,
        "database": db_status,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


@router.get("/backup/status")
def get_backup_status():
    """Mengembalikan informasi status database PostgreSQL CBT (db_cbt) dan folder uploads."""
    db_size_str = "0 KB"
    tables_count = 0
    pg_version = "PostgreSQL"
    db_name = CBT_DB_CONFIG["dbname"]

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
        db_size_str = cur.fetchone()[0]
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """)
        tables_count = cur.fetchone()[0]
        cur.execute("SHOW server_version")
        ver_raw = cur.fetchone()[0]
        pg_version = f"PostgreSQL {ver_raw.split(' ')[0]}"
    except Exception as e:
        print("Gagal membaca status backup PostgreSQL CBT:", e)
    finally:
        conn.close()

    uploads_size = 0
    uploads_count = 0
    if os.path.isdir(UPLOAD_DIR):
        for root, _, files in os.walk(UPLOAD_DIR):
            for f in files:
                fp = os.path.join(root, f)
                if os.path.isfile(fp):
                    uploads_size += os.path.getsize(fp)
                    uploads_count += 1

    return {
        "success": True,
        "database_name": f"{db_name} (Terpisah dari db_sekolah)",
        "database_size": db_size_str,
        "tables_count": tables_count,
        "uploads_size": _format_size(uploads_size),
        "uploads_count": uploads_count,
        "engine_version": pg_version,
        "server_time": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
    }


@router.get("/backup/download")
def download_backup(current_user: dict = Depends(get_current_user)):
    """Membuat dump SQL PostgreSQL db_cbt via pg_dump + seluruh file uploads/ dalam satu arsip ZIP."""
    _require_admin(current_user)
    pg_dump_bin = _find_pg_tool("pg_dump")

    mem_zip = io.BytesIO()
    tmp_sql_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".sql") as tmp:
            tmp_sql_path = tmp.name

        env = os.environ.copy()
        env["PGPASSWORD"] = str(CBT_DB_CONFIG["password"])

        cmd = [
            pg_dump_bin,
            "-h", str(CBT_DB_CONFIG["host"]),
            "-p", str(CBT_DB_CONFIG["port"]),
            "-U", str(CBT_DB_CONFIG["user"]),
            "-d", str(CBT_DB_CONFIG["dbname"]),
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "-f", tmp_sql_path,
        ]
        res = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(res.stderr.strip() or "pg_dump gagal membuat dump SQL.")

        with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp_sql_path, arcname=f"{CBT_DB_CONFIG['dbname']}.sql")
            if os.path.isdir(UPLOAD_DIR):
                for root, _, files in os.walk(UPLOAD_DIR):
                    for f in files:
                        fp = os.path.join(root, f)
                        rel = os.path.relpath(fp, UPLOAD_DIR)
                        zf.write(fp, arcname=os.path.join("uploads", rel))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal membuat arsip cadangan CBT: {str(e)}")
    finally:
        if tmp_sql_path and os.path.isfile(tmp_sql_path):
            try:
                os.remove(tmp_sql_path)
            except Exception:
                pass

    mem_zip.seek(0)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return StreamingResponse(
        mem_zip,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="backup_cbt_{stamp}.zip"'},
    )


@router.post("/backup/restore")
async def restore_backup(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    """Memulihkan database PostgreSQL db_cbt (dan folder uploads/ bila berupa .zip) dari berkas cadangan."""
    _require_admin(current_user)
    psql_bin = _find_pg_tool("psql")

    filename = (file.filename or "").lower()
    if not (filename.endswith(".zip") or filename.endswith(".sql")):
        raise HTTPException(status_code=400, detail="Format file tidak didukung. Gunakan file cadangan .zip atau .sql.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Berkas cadangan kosong.")

    tmp_dir = tempfile.mkdtemp(prefix="cbt_restore_")
    try:
        restored_sql_src = None
        restored_uploads_count = 0

        if filename.endswith(".zip"):
            zip_path = os.path.join(tmp_dir, "backup.zip")
            with open(zip_path, "wb") as f:
                f.write(content)

            if not zipfile.is_zipfile(zip_path):
                raise HTTPException(status_code=400, detail="Berkas ZIP tidak valid atau rusak.")

            with zipfile.ZipFile(zip_path, "r") as zf:
                for member in zf.namelist():
                    if member.endswith("/") or ".." in member or member.startswith("/") or member.startswith("\\"):
                        continue
                    norm = member.replace("\\", "/")
                    if norm.lower().endswith(".sql") and not restored_sql_src:
                        out_sql = os.path.join(tmp_dir, "restore.sql")
                        with zf.open(member) as src, open(out_sql, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        restored_sql_src = out_sql
                    elif norm.startswith("uploads/"):
                        rel = norm[len("uploads/"):]
                        if rel:
                            target = os.path.join(UPLOAD_DIR, rel)
                            os.makedirs(os.path.dirname(target), exist_ok=True)
                            with zf.open(member) as src, open(target, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            restored_uploads_count += 1
        else:
            out_sql = os.path.join(tmp_dir, "restore.sql")
            with open(out_sql, "wb") as f:
                f.write(content)
            restored_sql_src = out_sql

        if not restored_sql_src or not os.path.isfile(restored_sql_src):
            raise HTTPException(status_code=400, detail="File SQL cadangan (.sql) tidak ditemukan di dalam arsip.")

        env = os.environ.copy()
        env["PGPASSWORD"] = str(CBT_DB_CONFIG["password"])

        cmd = [
            psql_bin,
            "-h", str(CBT_DB_CONFIG["host"]),
            "-p", str(CBT_DB_CONFIG["port"]),
            "-U", str(CBT_DB_CONFIG["user"]),
            "-d", str(CBT_DB_CONFIG["dbname"]),
            "-v", "ON_ERROR_STOP=0",
            "-f", restored_sql_src,
        ]
        res = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if res.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Gagal memulihkan SQL ke db_cbt: {res.stderr.strip()}")

        return {
            "success": True,
            "message": f"Pemulihan data PostgreSQL '{CBT_DB_CONFIG['dbname']}' berhasil! ({restored_uploads_count} file media ikut dipulihkan).",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal memulihkan data CBT: {str(e)}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
