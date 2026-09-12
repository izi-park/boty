import sys
sys.path.insert(0, "/root/fleet")
import return_campaign_core as return_core
import os
import random
import time
import threading
import json
import re
import sqlite3
import urllib.request
import urllib.parse
import urllib.error
import transfer_form
from datetime import datetime, timedelta, timezone

import vk_api

from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.longpoll import VkEventType, VkLongPoll

import izi_box

TOKEN = os.getenv("VK_TOKEN")

if not TOKEN:
    raise RuntimeError("VK_TOKEN не найден")

vk_session = vk_api.VkApi(token=TOKEN)
vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)

ADMINS = [8302706, 526574493]

SUPPORT_APP_URL = os.getenv("SUPPORT_APP_URL", "http://127.0.0.1:8001/api/vk/message")
SUPPORT_APP_SECRET = os.getenv("SUPPORT_APP_SECRET", "izi_test_2026")

# === RETURN 7% CAMPAIGN ===
RETURN_CAMPAIGN_DB = "/root/fleet/churn_return.db"
RETURN_CODE_RE = re.compile(r"\bR7-[A-Z0-9]{5}\b", re.IGNORECASE)

# Сообщение похоже на промокод, но мы НЕ исправляем его автоматически.
# Нужна только для того, чтобы ошибочный код не уходил оператору.
RETURN_CODE_LIKE_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"[A-Za-z0-9]{1,6}(?:-|–|—)[A-Za-z0-9]{3,12}"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE
)


def looks_like_return_code(text):
    raw = str(text or "").strip()

    # Телефон может содержать дефисы:
    # 8-913-642-16-80
    # Из-за этого он внешне похож на промокод.
    # Если в сообщении 10+ цифр — промокодом его не считаем.
    digits = re.sub(r"\D", "", raw)

    if len(digits) >= 10:
        return False

    return bool(
        RETURN_CODE_LIKE_RE.search(raw)
    )

RETURN_ORDER_CACHE = {}
RETURN_ORDER_CACHE_SECONDS = 300
RETURN_FLEET_LIMIT_UNTIL = None



operator_mode = {}
operator_started_at = {}
operator_has_question = {}
operator_warned = {}
last_event = set()

dialog_history = {}
user_name_cache = {}

OPERATOR_WARNING_TIME = 120
OPERATOR_CLOSE_TIME = 1200
HISTORY_LIMIT = 30

def main_keyboard():
    keyboard = VkKeyboard()

    keyboard.add_button("📲 Подключение", VkKeyboardColor.PRIMARY)
    keyboard.add_button("🧾 Самозанятость / ИП")
    keyboard.add_line()

    keyboard.add_button("💰 Оплата и вывод", VkKeyboardColor.POSITIVE)
    keyboard.add_button("🚴 Работа с заказами", VkKeyboardColor.PRIMARY)
    keyboard.add_line()

    keyboard.add_button("⚠️ Проблемы", VkKeyboardColor.NEGATIVE)
    keyboard.add_button("🧊 Термокороб")
    keyboard.add_line()

    keyboard.add_button("🚲 Аренда и ремонт")
    keyboard.add_line()

    keyboard.add_button("🎁 Изи Бокс", VkKeyboardColor.POSITIVE)
    keyboard.add_line()

    keyboard.add_button("👨‍💻 Оператор")

    return keyboard.get_keyboard()

MAIN_KB = main_keyboard()

MENU_BUTTONS = [
    "📲 подключение",
    "🧾 самозанятость / ип",
    "💰 оплата и вывод",
    "🚴 работа с заказами",
    "⚠️ проблемы",
    "🧊 термокороб",
    "🚲 аренда и ремонт",
    "🎁 изи бокс"
]

URGENT_WORDS = [
    "не помогло",
    "не работает",
    "не получается",
    "срочно",
    "ошибка",
    "помогите",
    "не могу",
    "деньги не пришли",
    "не пришли деньги",
    "заказы недоступны",
    "заказы ограничены",
    "заблокировали",
    "штраф",
    "пропал заказ",
    "не выходит на линию",
    "не могу выйти на линию"
]

def send(user_id, message, keyboard=True, remember=True):
    if keyboard is True:
        outgoing_keyboard = MAIN_KB
    elif keyboard:
        outgoing_keyboard = keyboard
    else:
        outgoing_keyboard = None

    vk.messages.send(
        user_id=user_id,
        message=message,
        random_id=random.randint(1, 2**63),
        keyboard=outgoing_keyboard
    )
    if remember:
        remember_message(user_id, "bot", message, [])


def send_izi_box(user_id, message, keyboard=True):
    # Игровые сообщения не относятся к обращениям оператору.
    send(user_id, message, keyboard=keyboard, remember=False)

def normalize_text(text):
    return text.lower().strip()

def extract_return_code(text):
    match = RETURN_CODE_RE.search(str(text or ""))
    if not match:
        return None

    return match.group(0).upper()


def load_return_fleet_config():
    with open("/root/fleet/config.json", "r", encoding="utf-8") as f:
        return json.load(f)


def return_api_json(method, url, headers, payload=None):
    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(
            f"[RETURN FLEET HTTP] {e.code} {body[:1000]}",
            flush=True
        )
        return e.code, None
    except Exception as e:
        print(
            f"[RETURN FLEET ERROR] {e!r}",
            flush=True
        )
        return 0, None


def parse_return_dt(value):
    if not value:
        return None

    try:
        value = str(value).strip()

        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception as e:
        print(
            f"[RETURN DATE ERROR] value={value!r} error={e!r}",
            flush=True
        )
        return None


def get_return_window(row):
    """
    Реальная акция:
    сначала используем подтверждённое время доставки SMS,
    если его нет — время отправки.

    Для наших текущих preview-тестов SMS ещё не отправлялась,
    поэтому временно используем created_at только для тестирования.
    """

    start = (
        parse_return_dt(row["sms_delivered_at"])
        or parse_return_dt(row["sms_sent_at"])
    )

    test_preview = False

    if start is None and row["status"] == "preview":
        start = parse_return_dt(row["created_at"])
        test_preview = True

    if start is None:
        return None, None, False

    deadline = start + timedelta(hours=24)

    return start, deadline, test_preview


def get_return_orders_for_window(contractor_id, start_dt, deadline_dt):
    global RETURN_FLEET_LIMIT_UNTIL

    now_utc = datetime.now(timezone.utc)

    # Если Яндекс недавно дал 429 — временно вообще не стучимся.
    if (
        RETURN_FLEET_LIMIT_UNTIL is not None
        and now_utc < RETURN_FLEET_LIMIT_UNTIL
    ):
        print(
            f"[RETURN FLEET COOLDOWN] until="
            f"{RETURN_FLEET_LIMIT_UNTIL.isoformat()}",
            flush=True
        )
        return "RATE_LIMIT"

    cache_key = (
        str(contractor_id),
        start_dt.isoformat(),
        deadline_dt.isoformat()
    )

    cached = RETURN_ORDER_CACHE.get(cache_key)

    if cached:
        cached_at, cached_orders = cached
        age = (now_utc - cached_at).total_seconds()

        if age < RETURN_ORDER_CACHE_SECONDS:
            print(
                f"[RETURN ORDER CACHE] "
                f"{contractor_id} age={int(age)}s "
                f"orders={len(cached_orders)}",
                flush=True
            )
            return cached_orders

    cfg = load_return_fleet_config()

    query_to = min(now_utc, deadline_dt)

    headers = {
        "X-Client-ID": cfg["FLEET_CLIENT_ID"],
        "X-API-Key": cfg["FLEET_API_KEY"],
        "X-Park-ID": cfg["FLEET_PARK_ID"],
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "query": {
            "park": {
                "id": cfg["FLEET_PARK_ID"],
                "driver_profile": {
                    "id": contractor_id
                },
                "order": {
                    "ended_at": {
                        "from": start_dt.isoformat(),
                        "to": query_to.isoformat()
                    },
                    "statuses": [
                        "complete"
                    ]
                }
            }
        },
        "limit": 50
    }

    status, data = return_api_json(
        "POST",
        "https://fleet-api.taxi.yandex.net/v1/parks/orders/list",
        headers,
        payload
    )

    if status == 429:
        RETURN_FLEET_LIMIT_UNTIL = (
            datetime.now(timezone.utc)
            + timedelta(minutes=2)
        )

        print(
            f"[RETURN FLEET RATE LIMIT] cooldown until "
            f"{RETURN_FLEET_LIMIT_UNTIL.isoformat()}",
            flush=True
        )

        return "RATE_LIMIT"

    if status != 200 or data is None:
        return None

    orders = data.get("orders", [])

    RETURN_ORDER_CACHE[cache_key] = (
        datetime.now(timezone.utc),
        orders
    )

    return orders



def format_time_left(deadline):
    now_utc = datetime.now(timezone.utc)

    seconds = int((deadline - now_utc).total_seconds())

    if seconds <= 0:
        return "0 мин"

    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60

    if hours > 0:
        return f"{hours} ч {minutes} мин"

    return f"{minutes} мин"


def handle_return_code(user_id, raw_text):
    code = extract_return_code(raw_text)

    if not code:
        if looks_like_return_code(raw_text):
            send(
                user_id,
                "❌ Код не найден или введён неверно.\n\n"
                "Проверьте код в полученном сообщении "
                "и отправьте его ещё раз полностью, без изменений."
            )
            return True

        return False

    print(
        f"[RETURN CODE] VK user={user_id} code={code}",
        flush=True
    )

    try:
        registration = return_core.register_return_code(
            code,
            user_id
        )
    except Exception as e:
        print(
            f"[RETURN REGISTER ERROR] {e!r}",
            flush=True
        )

        send(
            user_id,
            "❌ Сейчас не удалось проверить код. "
            "Попробуйте немного позже."
        )
        return True

    reg_reason = registration.get("reason")

    if reg_reason == "code_claim_expired":
        send(
            user_id,
            "⏱ Срок действия предложения истёк.\n\n"
            "Код можно отправить в течение 3 дней "
            "после получения SMS."
        )
        return True

    if reg_reason in (
        "code_not_found",
        "not_found",
        "unknown_code",
        "invalid_code",
    ):
        send(
            user_id,
            "❌ Код не найден или введён неверно.\n\n"
            "Проверьте код в полученном сообщении "
            "и отправьте его ещё раз полностью, без изменений."
        )
        return True

    print(
        f"[RETURN REGISTER] code={code} "
        f"reason={reg_reason}",
        flush=True
    )

    # --------------------------------------------------------
    # PREVIEW
    # Никакой привязки VK и никакой смены комиссии.
    # --------------------------------------------------------

    if reg_reason == "preview_test":
        send(
            user_id,
            "✅ Код акции распознан.\n\n"
            "Это тестовая запись. "
            "VK не привязан, заказы и комиссия не изменялись."
        )
        return True

    if reg_reason == "code_not_found":
        send(
            user_id,
            "❌ Такой код акции не найден. "
            "Проверьте код из SMS и отправьте его ещё раз."
        )
        return True

    if reg_reason == "sms_not_started":
        send(
            user_id,
            "❌ Код найден, но отправка SMS "
            "ещё не зарегистрирована системой. "
            "Попробуйте немного позже."
        )
        return True

    if reg_reason == "offer_expired":
        send(
            user_id,
            "Срок действия этого кода уже закончился."
        )
        return True

    if reg_reason == "bound_to_other_vk":
        send(
            user_id,
            "❌ Этот код уже привязан "
            "к другому аккаунту VK."
        )
        return True

    if reg_reason != "registered":
        send(
            user_id,
            "❌ Сейчас не удалось обработать код. "
            "Попробуйте немного позже."
        )
        return True

    first_name = (
        registration.get("first_name")
        or "Курьер"
    )

    # --------------------------------------------------------
    # Код зарегистрирован.
    # Теперь ядро САМО проверяет:
    # SMS -> 24 часа -> заказ -> 7% -> PUT -> GET 1.5.
    # --------------------------------------------------------

    try:
        result = return_core.activate_discount(
            code,
            execute=True
        )
    except Exception as e:
        print(
            f"[RETURN ACTIVATE ERROR] {e!r}",
            flush=True
        )

        send(
            user_id,
            "❌ Сейчас не удалось проверить выполнение акции. "
            "Код уже сохранён, повторно отправлять его не нужно."
        )
        return True

    reason = result.get("reason")

    if reason == "offer_expired":
        send(
            user_id,
            f"{first_name}, 24 часа с момента отправки "
            "кода уже истекли. "
            "Срок действия предложения завершён."
        )
        return True

    print(
        f"[RETURN ACTIVATE] code={code} "
        f"reason={reason} "
        f"changed={result.get('changed')}",
        flush=True
    )

    if reason == "waiting_order":
        seconds = result.get("seconds_left") or 0
        left = return_core.format_left(seconds)

        send(
            user_id,
            f"{first_name}, код принят 👍\n\n"
            "Для активации комиссии 1,5% выполните "
            "хотя бы 1 заказ в Яндекс Доставке "
            "через Изи Парк в течение 24 часов "
            "с момента отправки кода.\n\n"
            f"Осталось: {left}.\n\n"
            "Повторно отправлять код не нужно — "
            "система уже сохранила его. "
            "После завершения заказа скидка "
            "активируется автоматически."
        )
        return True

    if reason == "activated":
        expires = return_core.parse_dt(
            result.get("expires_at")
        )

        expires_text = (
            expires.strftime("%d.%m.%Y")
            if expires
            else "через 3 месяца"
        )

        send(
            user_id,
            f"{first_name}, условие акции выполнено 🎉\n\n"
            "Комиссия в Изи Парк успешно снижена "
            "до 1,5% на 3 месяца.\n"
            f"Действует до {expires_text}."
        )
        return True

    if reason == "already_activated":
        expires = return_core.parse_dt(
            result.get("expires_at")
        )

        expires_text = (
            expires.strftime("%d.%m.%Y")
            if expires
            else "указанной даты"
        )

        send(
            user_id,
            f"{first_name}, комиссия 1,5% "
            "уже активирована ✅\n"
            f"Действует до {expires_text}."
        )
        return True

    if reason == "offer_expired":
        send(
            user_id,
            f"{first_name}, срок акции закончился.\n\n"
            "В течение 24 часов не был найден "
            "выполненный заказ через Изи Парк."
        )
        return True

    if reason == "orders_rate_limited":
        send(
            user_id,
            f"{first_name}, код принят 👍\n\n"
            "Сейчас Яндекс временно ограничил "
            "проверку заказов. "
            "Повторно отправлять код не нужно — "
            "заявка уже сохранена."
        )
        return True

    if reason == "orders_check_failed":
        send(
            user_id,
            f"{first_name}, код принят 👍\n\n"
            "Сейчас не удалось обновить данные по заказам. "
            "Повторно отправлять код не нужно — "
            "заявка сохранена."
        )
        return True

    if reason in (
        "wrong_rule",
        "rule_changed_before_put",
        "already_15",
    ):
        send(
            user_id,
            "⚠️ Условия вашего профиля уже отличаются "
            "от условий этой акции. "
            "Автоматически менять комиссию не буду. "
            "Обратитесь к оператору."
        )
        return True

    if reason in (
        "put_failed",
        "verify_get_failed",
        "verify_rule_failed",
        "profile_read_failed",
        "fleet_error",
    ):
        print(
            f"[RETURN FLEET CHANGE FAILED] {result}",
            flush=True
        )

        send(
            user_id,
            "❌ Автоматическая активация сейчас не завершилась.\n\n"
            "Комиссия не считается активированной, "
            "пока Fleet не подтвердит значение 1,5%. "
            "Обратитесь к оператору."
        )
        return True

    send(
        user_id,
        "❌ Сейчас не удалось завершить проверку акции. "
        "Код уже сохранён."
    )
    return True


def close_operator(user_id):
    operator_mode.pop(user_id, None)
    operator_started_at.pop(user_id, None)
    operator_has_question.pop(user_id, None)
    operator_warned.pop(user_id, None)

def get_user_name(user_id):
    if user_id in user_name_cache:
        return user_name_cache[user_id]

    try:
        data = vk.users.get(user_ids=user_id)
        if data:
            name = f"{data[0].get('first_name', '')} {data[0].get('last_name', '')}".strip()
            if name:
                user_name_cache[user_id] = name
                return name
    except Exception as e:
        print(f"[USER NAME ERROR] {e}")

    fallback = f"Курьер {user_id}"
    user_name_cache[user_id] = fallback
    return fallback

def post_to_app(*args, **kwargs):
    # Отключено: приложение теперь получает VK-события только через vk-incoming-bridge.
    return False


def remember_message(user_id, sender, text="", attachments=None):
    if attachments is None:
        attachments = []

    if user_id not in dialog_history:
        dialog_history[user_id] = []

    items = []

    if text:
        items.append({
            "sender": sender,
            "text": text,
            "attachment_type": "",
            "attachment_text": "",
            "attachment_url": "",
            "sent_to_app": False
        })

    for att in attachments:
        items.append({
            "sender": sender,
            "text": "",
            "attachment_type": att.get("type", ""),
            "attachment_text": att.get("text", ""),
            "attachment_url": att.get("url", ""),
            "sent_to_app": False
        })

    dialog_history[user_id].extend(items)
    dialog_history[user_id] = dialog_history[user_id][-HISTORY_LIMIT:]

def send_unsent_history_to_app(*args, **kwargs):
    # Отключено: приложение теперь получает VK-события только через vk-incoming-bridge.
    return False


def extract_attachments(message_id):
    attachments = []

    if not message_id:
        return attachments

    try:
        result = vk.messages.getById(message_ids=message_id)
        items = result.get("items", [])
        if not items:
            return attachments

        for att in items[0].get("attachments", []):
            att_type = att.get("type")

            if att_type == "photo":
                photo = att.get("photo", {})
                sizes = photo.get("sizes", [])
                if sizes:
                    best = max(
                        sizes,
                        key=lambda s: int(s.get("width", 0)) * int(s.get("height", 0))
                    )
                    url = best.get("url", "")
                    if url:
                        attachments.append({
                            "type": "image",
                            "text": "Фото / скриншот от курьера",
                            "url": url
                        })

            elif att_type == "audio_message":
                audio = att.get("audio_message", {})
                url = audio.get("link_mp3") or audio.get("link_ogg") or ""
                duration = audio.get("duration")
                label = "Голосовое сообщение"
                if duration:
                    label += f" · {duration} сек"
                attachments.append({
                    "type": "voice",
                    "text": label,
                    "url": url
                })

            elif att_type == "doc":
                doc = att.get("doc", {})
                title = doc.get("title") or "Файл от курьера"
                url = doc.get("url", "")
                ext = (doc.get("ext") or "").lower()

                if ext in ["jpg", "jpeg", "png", "webp"]:
                    attachments.append({
                        "type": "image",
                        "text": title,
                        "url": url
                    })
                elif "audio_message" in str(doc).lower():
                    attachments.append({
                        "type": "voice",
                        "text": title,
                        "url": url
                    })
                else:
                    attachments.append({
                        "type": "doc",
                        "text": title,
                        "url": url
                    })

    except Exception as e:
        print(f"[ATTACHMENTS ERROR] {e}")

    return attachments

def notify_app_about_current_message(user_id, text, attachments, reason):
    if text:
        post_to_app(user_id=user_id, text=text, reason=reason, sender="courier")

        for item in reversed(dialog_history.get(user_id, [])):
            if item.get("sender") == "courier" and item.get("text") == text and not item.get("attachment_type"):
                item["sent_to_app"] = True
                break

    for att in attachments:
        post_to_app(
            user_id=user_id,
            reason=reason,
            attachment_type=att.get("type", ""),
            attachment_text=att.get("text", ""),
            attachment_url=att.get("url", ""),
            sender="courier"
        )

        for item in reversed(dialog_history.get(user_id, [])):
            if (
                item.get("sender") == "courier"
                and item.get("attachment_type") == att.get("type", "")
                and item.get("attachment_url") == att.get("url", "")
            ):
                item["sent_to_app"] = True
                break

def operator_watchdog():
    while True:
        now = time.time()

        for user_id in list(operator_mode.keys()):
            if operator_has_question.get(user_id):
                continue

            started_at = operator_started_at.get(user_id)
            if not started_at:
                continue

            elapsed = now - started_at

            if elapsed >= OPERATOR_CLOSE_TIME:
                close_operator(user_id)
                send(
                    user_id,
                    "⏳ Режим оператора закрыт, так как вы не написали вопрос.\n\n"
                    "👇 Вы можете снова пользоваться кнопками меню."
                )
                continue

            if elapsed >= OPERATOR_WARNING_TIME and not operator_warned.get(user_id):
                operator_warned[user_id] = True
                send(
                    user_id,
                    "❗ Вы нажали кнопку оператора, но не написали вопрос.\n\n"
                    "Напишите ваш вопрос, иначе режим оператора будет закрыт."
                )

        time.sleep(10)

def detect_topic(text):
    text = normalize_text(text)

    if any(word in text for word in [
        "подключение", "подключиться", "регистрация", "зарегистрироваться",
        "устроиться", "работать курьером", "хочу работать",
        "стать курьером", "оформление", "оформиться"
    ]):
        return "подключение"

    if any(word in text for word in [
        "оплата", "комиссия", "деньги", "зарплата",
        "доход", "заработок", "выплата", "выплаты"
    ]):
        return "оплата"

    if any(word in text for word in [
        "вывод", "вывести деньги", "реквизиты", "карта",
        "деньги не пришли", "не пришли деньги"
    ]):
        return "вывод"

    if any(word in text for word in [
        "заказ", "заказы", "работа", "линия", "доставка",
        "посылка", "мультизаказ", "штраф", "штрафы", "дтп"
    ]):
        return "работа"

    if any(word in text for word in [
        "проблема", "проблемы", "корректировка",
        "не работает", "не получается", "помогите", "сбой"
    ]):
        return "проблемы"

    if any(word in text for word in [
        "самозанятость", "самозанятый", "ип", "оквэд",
        "заказы ограничены", "заказы недоступны",
        "ограничены заказы", "недоступны заказы",
        "заказ ограничен", "заказ недоступен"
    ]):
        return "самозанятость"

    if any(word in text for word in [
        "термокороб", "термо короб", "короб", "инвентарь"
    ]):
        return "термокороб"

    if any(word in text for word in [
        "велосипед", "велосипеды", "велик", "велики",
        "электровелосипед", "электровелик", "электровелики",
        "электровел", "аренда", "аренда велосипеда",
        "аренда электровелика", "продление аренды",
        "продлить аренду", "ремонт", "ремонт велосипеда",
        "ремонт велика", "сломался велосипед", "сломался велик",
        "пробило колесо"
    ]):
        return "аренда"

    if any(word in text for word in [
        "оператор", "человек", "живой оператор", "поддержка", "админ"
    ]):
        return "оператор"

    return None

def needs_operator_attention(text, attachments):
    text = normalize_text(text)

    if attachments:
        return True

    if any(word in text for word in URGENT_WORDS):
        return True

    return False

def get_answer(text):
    text = text.lower()

    if "подключение" in text:
        return (
            "📲 Подключение:\n\n"
            "⚠️ Если нет самозанятости — оформите в приложении «Мой налог»\n"
            "📌 Если уже есть самозанятость — заполните форму:\n"
            "https://forms.fleet.yandex.ru/forms?ref_id=bc65abb3022140639ece9b33d42cdb64\n\n"
            "📌 Если у вас ИП, вы можете быть только курьером на авто — откройте ОКВЭД 53.20 и по готовности в меню нажмите кнопку → 👨‍💻оператор"
        )

    if "оплата" in text or "комис" in text:
        return (
            "💰 Оплата и комиссия:\n"
            "— комиссия парка с заказа: 7%\n"
            "— вывод средств: 1% (но комиссия не меньше 30₽)"
        )

    if "вывод" in text:
        return (
            "💳 Вывод средств:\n"
            "Деньги → баланс → ещё → реквизиты\n\n"
            "⚡ Вывод моментальный, максимум до 15 000₽ в день"
        )

    if "работа" in text:
        return (
            "🚴 Работа с заказами:\n"
            "1. Включить «на линии».\n"
            "2. Принять заказ.\n"
            "3. Забрать и доставить.\n\n"
            "📌 ВАЖНО ЗНАТЬ❗️:\n"
            "Список советов, которые помогут избежать штрафов или оспорить уже выставленную корректировку:\n"
            "1️⃣ При получении заказа, ВНИМАТЕЛЬНО сверьте номер в приложении и на самой посылке.\n"
            "2️⃣ Обратите внимание, СКОЛЬКО ТОЧЕК у вас в заказе. В мультизаказе получение нескольких посылок в одном месте.\n"
            "3️⃣ НИ В КОЕМ СЛУЧАЕ, не нажимайте статус ПОСЫЛКА ПОЛУЧЕНА если Вы не забрали посылку(будет штраф).\n"
            "4️⃣ Дозвониться в поддержку можно только с номера, указанного в профиле Яндекс Про при регистрациии.\n"
            "5️⃣ Если торговая точка закрыта или заказа нет в магазине-отменяйте заказ! (-7 баллов можно восполнить).\n"
            "6️⃣ Если вы завершили заказ по причине поломки автомобиля или ДТП, ОБЯЗАТЕЛЬНО сохраните чеки оплаты, извещение о ДТП.\n"
            "7️⃣ Если заказ с опцией ОТ ДВЕРИ ДО ДВЕРИ, не отдавайте его на улице, нужно вручить заказ в квартиру.\n\n"
            "Эти простые правила, помогут вам обойти стороной штрафы, и неприятности на заказах."
        )

    if "проблем" in text:
        return (
            "⚠️ Если возникли проблемы:\n"
            "— проверьте заказ\n"
            "— обратитесь в поддержку Яндекс про в приложении\n"
            "— или напишите оператору, для этого выберете кнопку в меню →👨‍💻оператор"
        )

    if "самозанятость" in text or "ип" in text:
        return (
            "🧾 Подтверждение самозанятости/ИП:\n\n"
            "📌 Самозанятые:\n"
            "В меню нажмите кнопку →👨‍💻оператор и напишите ФИО, номер, дату рождения и адрес проживания в формате: город, улица, дом. Ожидайте ответа.\n\n"
            "📌 ИП:\n"
            "Откройте ОКВЭД 53.20 и по готовности свяжитесь с 👨‍💻оператором по кнопке в меню"
        )

    if "термокороб" in text or "короб" in text:
        return (
            "🧊 Термокороб:\n"
            "в Яндекс про → Профиль → Инвентарь → Получить инвентарь.\n\n"
            "Что бы добавить свой короб, в приложении выберите → "
            "Опции для тарифов → Термокороб"
        )

    if "аренда" in text:
        return (
            "🚲 Аренда электровеликов и ремонт:\n\n"
            "По вопросам аренды в Омске, продления аренды, ремонта велосипеда или электровелика:\n\n"
            "📞 Свяжитесь с парком по номеру:\n"
            "+79339922926\n\n"
            "или напишите оператору через кнопку меню → 👨‍💻оператор"
        )

    return (
        "👇 Я не совсем понял вопрос.\n\n"
        "Попробуйте нажать кнопку в меню или написать подробнее.\n\n"
        "Для связи с оператором нажмите кнопку 👨‍💻оператор"
    )

def main():
    print("Бот запущен...")

    transfer_form.configure(
        vk=vk,
        admins=ADMINS,
        get_user_name=get_user_name,
        get_info_answer=get_answer,
        close_operator=close_operator,
        main_keyboard=MAIN_KB,
    )

    threading.Thread(target=operator_watchdog, daemon=True).start()

    for event in longpoll.listen():

        if event.type != VkEventType.MESSAGE_NEW:
            continue

        if getattr(event, "from_chat", False):
            continue

        if not event.to_me:
            continue

        event_id = getattr(event, "message_id", None)

        if event_id and event_id in last_event:
            continue

        if event_id:
            last_event.add(event_id)

        user_id = event.user_id

        raw_text = event.text or ""
        text = normalize_text(raw_text)

        # Изи Бокс обрабатываем до истории поддержки и анкеты.
        if operator_mode.get(user_id) and text == "🎁 изи бокс":
            close_operator(user_id)

        if izi_box.handle_message(user_id, raw_text, send_izi_box):
            continue
        attachments = extract_attachments(event_id)

        form_was_active = transfer_form.is_active(user_id)

        if not form_was_active:
            remember_message(
                user_id,
                "courier",
                raw_text,
                attachments
            )

        # Если человек уже находится внутри анкеты,
        # его ответ сначала обрабатывает именно анкета.
        # Это важно для телефонов, дат и адресов:
        # они не должны случайно восприниматься как промокоды.
        if form_was_active:
            if transfer_form.handle(user_id, raw_text):
                continue

        # Акционный код обрабатываем до обычного меню.
        if handle_return_code(user_id, raw_text):
            continue

        # Если активной анкеты ещё не было,
        # здесь обрабатываются кнопки входа в неё.
        if transfer_form.handle(user_id, raw_text):
            continue

        if user_id in ADMINS:
            continue

        if operator_mode.get(user_id):

            if text == "стоп оператор":
                close_operator(user_id)
                send(
                    user_id,
                    "✅ Вы вышли из режима оператора.\n\n👇 Снова доступны кнопки меню."
                )
                continue

            if text in MENU_BUTTONS:
                close_operator(user_id)
                answer = get_answer(text)
                send(
                    user_id,
                    "ℹ️ Вы вышли из режима оператора и вернулись в меню бота.\n\n"
                    + answer
                )
                continue

            operator_has_question[user_id] = True
            notify_app_about_current_message(
                user_id=user_id,
                text=raw_text,
                attachments=attachments,
                reason="Новое сообщение в открытой заявке"
            )
            continue

        if text in ("👨‍💻 оператор", "оператор"):
            izi_box.clear_bridge_suppression(user_id)
            operator_mode[user_id] = True
            operator_started_at[user_id] = time.time()
            operator_has_question[user_id] = False
            operator_warned[user_id] = False

            send_unsent_history_to_app(user_id, "Вызвал оператора")

            send(
                user_id,
                "👨‍💻 Вы подключены к оператору.\n\n"
                "Я передала ваше обращение администратору.\n\n"
                "Если вы уже писали вопрос выше — оператор увидит историю переписки, фото и голосовые.\n\n"
                "⏳ Ожидайте ответа.\n\n"
                "❗ Чтобы снова пользоваться кнопками бота:\n"
                "👉 Напишите СТОП ОПЕРАТОР"
            )

            continue

        detected = detect_topic(text)

        if detected:
            answer = get_answer(detected)
            send(user_id, answer)

            if detected == "проблемы" or needs_operator_attention(text, attachments):
                send_unsent_history_to_app(user_id, "Требует внимания оператора")

            continue

        if not detected:
            send_unsent_history_to_app(user_id, "Бот не понял вопрос")

            send(
                user_id,
                "Я передала ваше сообщение администратору 👨‍💻\n\n"
                "Он ответит вам здесь, в сообщениях группы.\n\n"
                "Пока ожидаете, можете выбрать нужный раздел ниже — возможно, ответ уже есть в меню."
            )
            continue

if __name__ == "__main__":
    main()
