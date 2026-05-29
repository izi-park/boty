import os
import random
import time
import threading
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

operator_mode = {}
operator_started_at = {}
operator_has_question = {}
operator_warned = {}
last_event = set()

OPERATOR_WARNING_TIME = 120
OPERATOR_CLOSE_TIME = 1200

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

def send(user_id, message, keyboard=True):
    vk.messages.send(
        user_id=user_id,
        message=message,
        random_id=random.randint(1, 2**63),
        keyboard=MAIN_KB if keyboard else None
    )

def notify_admins(user_id, text):
    for admin_id in ADMINS:
        try:
            vk.messages.send(
                user_id=admin_id,
                message=(
                    f"🔔 Новый вопрос оператору\n\n"
                    f"👤 USER ID: {user_id}\n\n"
                    f"💬 Сообщение:\n{text}"
                ),
                random_id=random.randint(1, 2**63)
            )
        except Exception as e:
            print(f"[ADMIN ERROR] {e}")

def normalize_text(text):
    return text.lower().strip()

def close_operator(user_id):
    operator_mode.pop(user_id, None)
    operator_started_at.pop(user_id, None)
    operator_has_question.pop(user_id, None)
    operator_warned.pop(user_id, None)

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

        # Игнорируем групповые чаты/беседы
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
        text = normalize_text(event.text or "")

        # Бот не отвечает админам как обычным пользователям
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
            notify_admins(user_id, text)
            continue

        if text in ("👨‍💻 оператор", "оператор"):
            operator_mode[user_id] = True
            operator_started_at[user_id] = time.time()
            operator_has_question[user_id] = False
            operator_warned[user_id] = False

            send(
                user_id,
                "👨‍💻 Вы подключены к оператору.\n\n"
                "✍️ Напишите свой вопрос — оператор его увидит.\n\n"
                "⏳ Ожидайте ответа.\n\n"
                "❗ Чтобы снова пользоваться кнопками бота:\n"
                "👉 Напишите СТОП ОПЕРАТОР"
            )

            continue

        detected = detect_topic(text)

        if detected:
            answer = get_answer(detected)
        else:
            answer = get_answer(text)

        send(user_id, answer)

if __name__ == "__main__":
    main()
