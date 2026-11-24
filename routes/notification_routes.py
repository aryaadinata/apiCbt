from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from database import get_db
from auth import get_current_user

router = APIRouter(prefix="/api/cbt/notifications", tags=["Notifications"])

@router.get("")
def list_notifications(current_user: dict = Depends(get_current_user)):
    """
    Mengambil daftar notifikasi untuk user saat ini (guru atau admin)
    """
    db = get_db()
    cursor = db.cursor()
    
    user_id = current_user.get("id")
    teacher_id = current_user.get("teacher_id") or current_user.get("id")
    user_name = (current_user.get("name") or "").strip()

    # Ambil notifikasi yang relevan untuk user/teacher ini atau umum
    cursor.execute("""
        SELECT id, user_id, teacher_id, teacher_name, title, message, type, link, is_read, created_at
        FROM cbt_notifications
        WHERE (user_id = %s OR teacher_id = %s OR (teacher_name IS NOT NULL AND LOWER(teacher_name) = LOWER(%s)) OR (user_id IS NULL AND teacher_id IS NULL))
        ORDER BY id DESC
        LIMIT 50
    """, (user_id, teacher_id, user_name))
    
    rows = cursor.fetchall()
    notifications = []
    unread_count = 0
    for r in rows:
        item = dict(r)
        if item.get("created_at") and isinstance(item["created_at"], datetime):
            item["created_at"] = item["created_at"].strftime("%Y-%m-%d %H:%M:%S")
        is_read = bool(item.get("is_read"))
        item["is_read"] = 1 if is_read else 0
        if not is_read:
            unread_count += 1
        notifications.append(item)
        
    db.close()
    return {
        "success": True,
        "notifications": notifications,
        "unread_count": unread_count
    }

@router.put("/read-all")
def mark_all_notifications_read(current_user: dict = Depends(get_current_user)):
    """
    Menandai seluruh notifikasi user saat ini telah dibaca
    """
    db = get_db()
    cursor = db.cursor()
    user_id = current_user.get("id")
    teacher_id = current_user.get("teacher_id") or current_user.get("id")
    user_name = (current_user.get("name") or "").strip()
    
    cursor.execute("""
        UPDATE cbt_notifications 
        SET is_read = 1 
        WHERE is_read = 0 AND (user_id = %s OR teacher_id = %s OR (teacher_name IS NOT NULL AND LOWER(teacher_name) = LOWER(%s)))
    """, (user_id, teacher_id, user_name))
    db.commit()
    db.close()
    return {"success": True, "message": "Semua notifikasi ditandai dibaca."}

@router.put("/{notif_id}/read")
def mark_notification_read(notif_id: int, current_user: dict = Depends(get_current_user)):
    """
    Menandai satu notifikasi telah dibaca
    """
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE cbt_notifications SET is_read = 1 WHERE id = %s", (notif_id,))
    db.commit()
    db.close()
    return {"success": True, "message": "Notifikasi ditandai dibaca."}
