import os
import random
import time
import threading
import json
import urllib.request
import urllib.parse
import urllib.error

import vk_api

from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.longpoll import VkEventType, VkLongPoll

TOKEN = os.getenv("VK_TOKEN")

if not TOKEN:
    raise RuntimeError("VK_TOKEN не найден")

vk_session = vk_api.VkApi(token=TOKEN)
vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)

ADMINS = [8302706, 526574493]

SUPPORT_APP_URL = os.getenv("SUPPORT_APP_URL", "http://127.0.0.1:8001/api/vk/message")
SUPPORT_APP_SECRET = os.getenv("SUPPORT_APP_SECRET", "izi_test_2026")

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
    "🚲 аренда и ремонт"
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

def send(user_id, message, keyboard=True):
    vk.messages.send(
        user_id=user_id,
        message=message,
        random_id=random.randint(1, 2**63),
        keyboard=MAIN_KB if keyboard else None
    )
    remember_message(user_id, "bot", message, [])

def normalize_text(text):
    return text.lower().strip()

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

def post_to_app(user_id, text="", reason="Сообщение из ВК", attachment_type="", attachment_text="", attachment_url="", sender="courier"):
    payload = {
        "vk_id": str(user_id),
        "courier": get_user_name(user_id),
        "text": text or "",
        "reason": reason or "Сообщение из ВК",
        "attachment_type": attachment_type or "",
        "attachment_text": attachment_text or "",
        "attachment_url": attachment_url or "",
        "sender": sender if sender in ["courier", "bot", "admin"] else "courier"
    }

    url = SUPPORT_APP_URL + "?" + urllib.parse.urlencode({"secret": SUPPORT_APP_SECRET})
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        url=url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            print(f"[APP OK] {body}")
            return True
    except Exception as e:
        print(f"[APP ERROR] {e}")
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

def send_unsent_history_to_app(user_id, reason):
    history = dialog_history.get(user_id, [])

    sent_any = False

    for item in history:
        if item.get("sent_to_app"):
            continue

        ok = post_to_app(
            user_id=user_id,
            text=item.get("text", ""),
            reason=reason,
            attachment_type=item.get("attachment_type", ""),
            attachment_text=item.get("attachment_text", ""),
            attachment_url=item.get("attachment_url", ""),
            sender=item.get("sender", "courier")
        )

        if ok:
            item["sent_to_app"] = True
            sent_any = True

    return sent_any

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

        if user_id in ADMINS:
            continue

        raw_text = event.text or ""
        text = normalize_text(raw_text)
        attachments = extract_attachments(event_id)

        remember_message(user_id, "courier", raw_text, attachments)

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
