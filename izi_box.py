import random
import re
import sqlite3
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from vk_api.keyboard import VkKeyboard, VkKeyboardColor


DB_PATH = os.getenv("IZI_BOX_DB_PATH", "/root/fleet/izi_box.db")
MOSCOW = ZoneInfo("Europe/Moscow")
ORDER_TARGET = 80

RULE_15 = "0d4e04da8f234d70ba9d614ad0da68a5"
RULE_ZERO = "ba272ae44a2c4f589465a497f108f5bc"

BOX_BUTTONS = {
    "📦 коробка 1": 1,
    "📦 коробка 2": 2,
    "📦 коробка 3": 3,
}

IZI_BOX_TEXTS = {
    "🎁 изи бокс",
    "изи бокс",
    "изибокс",
    "easy box",
    "игра с коробками",
    "открыть коробку",
    "выбрать коробку",
    "призовая коробка",
}

MENU_TEXTS = {
    "📲 подключение",
    "🧾 самозанятость / ип",
    "💰 оплата и вывод",
    "🚴 работа с заказами",
    "⚠️ проблемы",
    "🧊 термокороб",
    "🚲 аренда и ремонт",
    "👨‍💻 оператор",
}

sessions = {}
secure_random = random.SystemRandom()


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS courier_cache (
                contractor_id TEXT PRIMARY KEY,
                phone TEXT,
                full_name TEXT NOT NULL,
                work_rule_id TEXT,
                work_status TEXT,
                fire_date TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                synced_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_courier_cache_phone
            ON courier_cache(phone);

            CREATE TABLE IF NOT EXISTS bindings (
                vk_user_id INTEGER PRIMARY KEY,
                contractor_id TEXT NOT NULL UNIQUE,
                phone TEXT NOT NULL,
                bound_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS phone_lookups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vk_user_id INTEGER NOT NULL,
                phone TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                contractor_id TEXT,
                full_name TEXT,
                requested_at TEXT NOT NULL,
                checked_at TEXT,
                next_try_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_phone_lookups_queue
            ON phone_lookups(status, next_try_at, requested_at);

            CREATE TABLE IF NOT EXISTS weekly_progress (
                contractor_id TEXT NOT NULL,
                week_start TEXT NOT NULL,
                completed_orders INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (contractor_id, week_start)
            );

            CREATE TABLE IF NOT EXISTS order_scan_items (
                week_start TEXT NOT NULL,
                contractor_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                PRIMARY KEY (week_start, contractor_id, order_id)
            );

            CREATE TABLE IF NOT EXISTS bridge_suppression (
                vk_user_id INTEGER PRIMARY KEY,
                expires_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contractor_id TEXT NOT NULL,
                vk_user_id INTEGER NOT NULL,
                week_start TEXT NOT NULL,
                box_number INTEGER NOT NULL,
                reward_code TEXT NOT NULL,
                reward_title TEXT NOT NULL,
                target_rule_id TEXT NOT NULL,
                duration_days INTEGER NOT NULL,
                original_rule_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                drawn_at TEXT NOT NULL,
                applied_at TEXT,
                expires_at TEXT,
                restored_at TEXT,
                last_error TEXT,
                UNIQUE (contractor_id, week_start)
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                contractor_id TEXT,
                vk_user_id INTEGER,
                event TEXT NOT NULL,
                details TEXT
            );

            CREATE TABLE IF NOT EXISTS izi_box_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )


def now_moscow():
    return datetime.now(MOSCOW)


def week_start_for(moment=None):
    moment = moment or now_moscow()
    return (moment - timedelta(days=moment.weekday())).date().isoformat()


def normalize_phone(value):
    digits = re.sub(r"\D", "", str(value or ""))

    if len(digits) == 11 and digits[0] in "78":
        return "+7" + digits[1:]

    if len(digits) == 10 and digits[0] == "9":
        return "+7" + digits

    return None


def mask_phone(phone):
    digits = re.sub(r"\D", "", str(phone or ""))
    return "+7 *** ***-" + digits[-4:] if len(digits) >= 4 else "номер скрыт"


def suppress_bridge(vk_user_id, seconds=1800):
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO bridge_suppression(vk_user_id, expires_at)
            VALUES (?, ?)
            ON CONFLICT(vk_user_id) DO UPDATE SET expires_at = excluded.expires_at
            """,
            (int(vk_user_id), time.time() + int(seconds)),
        )


def clear_bridge_suppression(vk_user_id):
    with connect() as conn:
        conn.execute(
            "DELETE FROM bridge_suppression WHERE vk_user_id = ?",
            (int(vk_user_id),),
        )


def phone_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("↩️ В меню")
    return keyboard.get_keyboard()


def confirm_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("✅ Да, это я", VkKeyboardColor.POSITIVE)
    keyboard.add_button("❌ Нет")
    keyboard.add_line()
    keyboard.add_button("↩️ В меню")
    return keyboard.get_keyboard()


def boxes_keyboard():
    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("📦 Коробка 1", VkKeyboardColor.PRIMARY)
    keyboard.add_button("📦 Коробка 2", VkKeyboardColor.PRIMARY)
    keyboard.add_button("📦 Коробка 3", VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button("↩️ В меню")
    return keyboard.get_keyboard()


def get_binding(vk_user_id):
    with connect() as conn:
        return conn.execute(
            """
            SELECT b.*, c.full_name
            FROM bindings b
            LEFT JOIN courier_cache c USING (contractor_id)
            WHERE b.vk_user_id = ?
            """,
            (int(vk_user_id),),
        ).fetchone()


def find_courier(phone):
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM courier_cache
            WHERE phone = ? AND active = 1
            ORDER BY synced_at DESC
            """,
            (phone,),
        ).fetchall()

    unique = {row["contractor_id"]: row for row in rows}
    return list(unique.values())


def latest_lookup(vk_user_id):
    with connect() as conn:
        return conn.execute(
            """
            SELECT * FROM phone_lookups
            WHERE vk_user_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(vk_user_id),),
        ).fetchone()


def queue_phone_lookup(vk_user_id, phone):
    requested_at = now_moscow().isoformat()

    with connect() as conn:
        conn.execute(
            """
            UPDATE phone_lookups
            SET status = 'cancelled'
            WHERE vk_user_id = ? AND status = 'pending'
            """,
            (int(vk_user_id),),
        )
        conn.execute(
            """
            INSERT INTO phone_lookups(
                vk_user_id, phone, status, requested_at, next_try_at
            ) VALUES (?, ?, 'pending', ?, ?)
            """,
            (int(vk_user_id), phone, requested_at, requested_at),
        )


def bind(vk_user_id, courier):
    now = now_moscow().isoformat()

    try:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO bindings(vk_user_id, contractor_id, phone, bound_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    int(vk_user_id),
                    courier["contractor_id"],
                    courier["phone"],
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO audit_log(created_at, contractor_id, vk_user_id, event, details)
                VALUES (?, ?, ?, 'phone_bound', ?)
                """,
                (now, courier["contractor_id"], int(vk_user_id), mask_phone(courier["phone"])),
            )
        return True, None
    except sqlite3.IntegrityError:
        return False, "Этот профиль уже привязан к другому аккаунту VK. Напишите оператору."


def choose_reward():
    value = secure_random.randrange(100)

    if value < 70:
        return {
            "code": "commission_15_7d",
            "title": "1,5% комиссии парка на 7 дней",
            "rule_id": RULE_15,
            "days": 7,
        }

    if value < 95:
        return {
            "code": "commission_zero_1d",
            "title": "0% комиссии парка на 1 день",
            "rule_id": RULE_ZERO,
            "days": 1,
        }

    return {
        "code": "commission_zero_3d",
        "title": "0% комиссии парка на 3 дня",
        "rule_id": RULE_ZERO,
        "days": 3,
    }


def latest_available_week(contractor_id):
    earliest = (now_moscow().date() - timedelta(days=13)).isoformat()

    with connect() as conn:
        return conn.execute(
            """
            SELECT p.*
            FROM weekly_progress p
            LEFT JOIN rewards r
              ON r.contractor_id = p.contractor_id
             AND r.week_start = p.week_start
            WHERE p.contractor_id = ?
              AND p.completed_orders >= ?
              AND p.week_start >= ?
              AND r.id IS NULL
            ORDER BY p.week_start DESC
            LIMIT 1
            """,
            (contractor_id, ORDER_TARGET, earliest),
        ).fetchone()


def current_progress(contractor_id):
    current_week = week_start_for()

    with connect() as conn:
        return conn.execute(
            """
            SELECT * FROM weekly_progress
            WHERE contractor_id = ? AND week_start = ?
            """,
            (contractor_id, current_week),
        ).fetchone()


def latest_reward(contractor_id):
    with connect() as conn:
        return conn.execute(
            """
            SELECT * FROM rewards
            WHERE contractor_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (contractor_id,),
        ).fetchone()


def create_reward(binding, week_start, box_number):
    reward = choose_reward()
    now = now_moscow().isoformat()

    try:
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            progress = conn.execute(
                """
                SELECT completed_orders FROM weekly_progress
                WHERE contractor_id = ? AND week_start = ?
                """,
                (binding["contractor_id"], week_start),
            ).fetchone()

            if not progress or progress["completed_orders"] < ORDER_TARGET:
                return None, "Недостаточно выполненных заказов."

            conn.execute(
                """
                INSERT INTO rewards(
                    contractor_id, vk_user_id, week_start, box_number,
                    reward_code, reward_title, target_rule_id,
                    duration_days, status, drawn_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    binding["contractor_id"],
                    int(binding["vk_user_id"]),
                    week_start,
                    int(box_number),
                    reward["code"],
                    reward["title"],
                    reward["rule_id"],
                    reward["days"],
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO audit_log(created_at, contractor_id, vk_user_id, event, details)
                VALUES (?, ?, ?, 'box_opened', ?)
                """,
                (
                    now,
                    binding["contractor_id"],
                    int(binding["vk_user_id"]),
                    f"box={box_number}; reward={reward['code']}",
                ),
            )
        return reward, None
    except sqlite3.IntegrityError:
        return None, "Коробка за эту неделю уже была открыта."


def reward_status_text(row):
    status = row["status"]

    if status == "pending":
        suffix = "Приз поставлен в очередь и скоро включится автоматически."
    elif status == "active":
        expires = row["expires_at"] or ""
        suffix = f"Приз активен до {expires[:16].replace('T', ' ')} МСК."
    elif status == "completed":
        suffix = "Срок приза завершён, прежняя комиссия восстановлена."
    elif status == "manual_review":
        suffix = "Нужна проверка администратора — комиссия автоматически не менялась."
    else:
        suffix = "Приз обрабатывается."

    return f"🎉 Ваш приз: {row['reward_title']}\n\n{suffix}"


def show_home(vk_user_id, send):
    # Короткого окна хватает, чтобы мост пропустил кнопку и ответ бота.
    # Если дальше ожидается ввод, ниже окно продлевается.
    suppress_bridge(vk_user_id, seconds=20)
    binding = get_binding(vk_user_id)

    if not binding:
        lookup = latest_lookup(vk_user_id)

        if lookup and lookup["status"] == "found" and lookup["contractor_id"]:
            sessions[vk_user_id] = {
                "state": "confirming",
                "contractor_id": lookup["contractor_id"],
            }
            suppress_bridge(vk_user_id)
            send(
                vk_user_id,
                f"Нашёл профиль:\n\n{lookup['full_name']}\n{mask_phone(lookup['phone'])}\n\nЭто вы?",
                keyboard=confirm_keyboard(),
            )
            return

        if lookup and lookup["status"] == "pending":
            sessions.pop(vk_user_id, None)
            send(
                vk_user_id,
                "🔎 Проверяю номер. Подождите пару минут.\n\n"
                "Затем снова нажмите «Изи Бокс» — найденный профиль появится автоматически."
            )
            return

        sessions[vk_user_id] = {"state": "waiting_phone"}
        suppress_bridge(vk_user_id)
        previous_error = ""

        if lookup and lookup["status"] == "not_found":
            previous_error = "Предыдущий номер не найден во Fleet. Проверьте его ещё раз.\n\n"
        elif lookup and lookup["status"] == "ambiguous":
            previous_error = (
                "По предыдущему номеру найдено несколько карточек. Можно попробовать другой номер "
                "или написать оператору.\n\n"
            )
        elif lookup and lookup["status"] == "inactive":
            previous_error = "Карточка с этим номером найдена, но она не активна во Fleet.\n\n"
        elif lookup and lookup["status"] == "error":
            previous_error = "Fleet временно не ответил. Можно отправить номер ещё раз.\n\n"

        send(
            vk_user_id,
            "🎁 Изи Бокс\n\n"
            "Выполните 80 заказов за календарную неделю и откройте одну из трёх коробок.\n\n"
            "📅 Считаем с понедельника 00:00 до воскресенья 23:59 по Москве.\n\n"
            + previous_error
            +
            "Для входа отправьте номер телефона, который указан в Яндекс Про.\n"
            "Можно написать через +7 или 8, со скобками, пробелами или дефисами.\n"
            "Пример: +7 999 123-45-67",
            keyboard=phone_keyboard(),
        )
        return

    available = latest_available_week(binding["contractor_id"])

    if available:
        sessions[vk_user_id] = {
            "state": "choosing_box",
            "week_start": available["week_start"],
        }
        suppress_bridge(vk_user_id)
        send(
            vk_user_id,
            f"🎉 Цель выполнена: {available['completed_orders']} из {ORDER_TARGET} заказов!\n\n"
            "Выберите одну коробку. После выбора переиграть результат нельзя.",
            keyboard=boxes_keyboard(),
        )
        return

    progress = current_progress(binding["contractor_id"])
    reward = latest_reward(binding["contractor_id"])

    if progress:
        count = progress["completed_orders"]
        remaining = max(0, ORDER_TARGET - count)
        updated = progress["updated_at"][:16].replace("T", " ")
        message = (
            f"🎁 Изи Бокс\n\n"
            f"Выполнено: {count} из {ORDER_TARGET}\n"
            f"Осталось: {remaining}\n"
            f"Обновлено: {updated} МСК"
        )
    else:
        message = (
            "🎁 Изи Бокс\n\n"
            "Номер привязан. Счётчик заказов обновляется — загляните сюда через несколько минут."
        )

    if reward and reward["status"] in ("pending", "active", "manual_review"):
        message += "\n\n" + reward_status_text(reward)

    send(vk_user_id, message)


def handle_message(vk_user_id, raw_text, send):
    text = str(raw_text or "").strip().lower()

    if text in MENU_TEXTS:
        sessions.pop(vk_user_id, None)
        clear_bridge_suppression(vk_user_id)
        return False

    if text in IZI_BOX_TEXTS:
        sessions.pop(vk_user_id, None)
        show_home(vk_user_id, send)
        return True

    if text == "↩️ в меню":
        sessions.pop(vk_user_id, None)
        clear_bridge_suppression(vk_user_id)
        send(vk_user_id, "Вы вернулись в главное меню 👇")
        return True

    session = sessions.get(vk_user_id)

    if not session:
        return False

    suppress_bridge(vk_user_id)

    if session["state"] == "waiting_phone":
        phone = normalize_phone(raw_text)

        if not phone:
            send(
                vk_user_id,
                "Не получилось распознать номер. Отправьте российский номер в формате +7 999 123-45-67.",
                keyboard=phone_keyboard(),
            )
            return True

        queue_phone_lookup(vk_user_id, phone)
        sessions.pop(vk_user_id, None)
        suppress_bridge(vk_user_id, seconds=20)
        send(
            vk_user_id,
            "🔎 Номер принят. Подождите пару минут.\n\n"
            "Затем снова нажмите «Изи Бокс»."
        )
        return True

    if session["state"] == "confirming":
        if text == "❌ нет":
            sessions[vk_user_id] = {"state": "waiting_phone"}
            send(
                vk_user_id,
                "Хорошо. Отправьте правильный номер из Яндекс Про.",
                keyboard=phone_keyboard(),
            )
            return True

        if text != "✅ да, это я":
            send(vk_user_id, "Подтвердите профиль кнопкой ниже.", keyboard=confirm_keyboard())
            return True

        with connect() as conn:
            courier = conn.execute(
                "SELECT * FROM courier_cache WHERE contractor_id = ? AND active = 1",
                (session["contractor_id"],),
            ).fetchone()

        if not courier:
            sessions.pop(vk_user_id, None)
            send(vk_user_id, "Карточка курьера обновилась. Откройте «Изи Бокс» ещё раз.")
            return True

        ok, error = bind(vk_user_id, courier)
        sessions.pop(vk_user_id, None)

        if not ok:
            send(vk_user_id, error)
            return True

        send(
            vk_user_id,
            "✅ Профиль привязан. Заказы считаются за всю текущую неделю, включая дни до привязки."
        )
        show_home(vk_user_id, send)
        return True

    if session["state"] == "choosing_box":
        box_number = BOX_BUTTONS.get(text)

        if not box_number:
            send(vk_user_id, "Выберите одну из трёх коробок кнопкой ниже.", keyboard=boxes_keyboard())
            return True

        binding = get_binding(vk_user_id)

        if not binding:
            sessions.pop(vk_user_id, None)
            send(vk_user_id, "Сначала заново привяжите номер через раздел «Изи Бокс».")
            return True

        reward, error = create_reward(binding, session["week_start"], box_number)
        sessions.pop(vk_user_id, None)
        suppress_bridge(vk_user_id, seconds=20)

        if not reward:
            send(vk_user_id, error)
            return True

        send(
            vk_user_id,
            f"📦 Коробка {box_number} открыта!\n\n"
            f"🎉 Ваш приз: {reward['title']}\n\n"
            "Комиссия включится автоматически после контрольной проверки Fleet."
        )
        return True

    return False


init_db()
