import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database import init_db
from routes.auth_routes import router as auth_router
from routes.sync_routes import router as sync_router
from routes.bank_routes import router as bank_router
from routes.exam_routes import router as exam_router
from routes.student_routes import router as student_router
from routes.proctor_routes import router as proctor_router
from routes.schedule_routes import router as schedule_router
from routes.settings_routes import router as settings_router
from routes.results_routes import router as results_router
from routes.notification_routes import router as notification_router

# Inisialisasi database SQLite saat aplikasi dimulai
init_db()

app = FastAPI(
    title="CBT High-Concurrency Service API",
    description="Layanan API Mandiri untuk Ujian Komputer (Ulangan Harian & SAS) dengan Proteksi Anti-Curang",
    version="1.0.0"
)

# Konfigurasi CORS agar frontend port 3005 dan port 3000 dapat mengakses API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3005",
        "http://127.0.0.1:3005",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Folder statis untuk upload gambar/audio soal
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/static/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# Registrasi Router Modul
app.include_router(auth_router)
app.include_router(sync_router)
app.include_router(bank_router)
app.include_router(exam_router)
app.include_router(student_router)
app.include_router(proctor_router)
app.include_router(schedule_router)
app.include_router(settings_router)
app.include_router(results_router)
app.include_router(notification_router)

@app.get("/")
def root():
    return {
        "service": "CBT Microservice API",
        "status": "online",
        "port": 5005,
        "docs": "/docs"
    }

if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    uvicorn.run("main:app", host="0.0.0.0", port=5005, reload=True, app_dir=current_dir)
