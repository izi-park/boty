import os
import sqlite3
import time


DB_PATH = os.getenv("IZI_BOX_DB_PATH", "/root/fleet/izi_box.db")

IZI_BOX_BUTTONS = {
    "🎁 изи бокс",
    "изи бокс",
    "изибокс",
    "easy box",
    "игра с коробками",
    "открыть коробку",
    "выбрать коробку",
    "призовая коробка",
    "📦 коробка 1",
    "📦 коробка 2",
    "📦 коробка 3",
    "✅ да, это я",
    "❌ нет",
    "↩️ в меню",
}

OPERATOR_TEXTS = {
    "оператор",
    "👨‍💻 оператор",
}


def normalize_text(value):
    return " ".join(str(value or "").strip().lower().split())


def suppression_active(user_id):
    if not user_id or not os.path.exists(DB_PATH):
        return False

    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=2)
        try:
            row = conn.execute(
                "SELECT expires_at FROM bridge_suppression WHERE vk_user_id = ?",
                (int(user_id),),
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        # Если база недоступна, настоящее обращение курьера не теряем.
        return False

    return bool(row and float(row[0]) > time.time())


def should_skip_izi_box(out, peer_id, from_id, text):
    low = normalize_text(text)

    if low in OPERATOR_TEXTS:
        return False

    if low in IZI_BOX_BUTTONS:
        return True

    courier_id = peer_id if int(out or 0) == 1 else from_id
    return suppression_active(courier_id)
