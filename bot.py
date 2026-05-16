import os
import random
import vk_api

from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.longpoll import VkEventType, VkLongPoll

# =====================
# 🔑 ТОКЕН
# =====================
TOKEN = os.getenv("VK_TOKEN")

if not TOKEN:
    raise RuntimeError("VK_TOKEN не найден")

vk_session = vk_api.VkApi(token=TOKEN)
vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)

# =====================
# 👨‍💻 АДМИНЫ
# =====================
ADMINS = [
    8302706,
    526574493
]

# =====================
# 🧠 ПАМЯТЬ (саппорт система)
# =====================
operator_mode = {}   # user_id -> bool
operator_queue = {}  # user_id -> True (в работе у оператора)
last_event = set()

# =====================
# 📌 КНОПКИ
# =====================
def main_keyboard():
    keyboard = VkKeyboard()

    keyboard.add_button("📲 Подключение", VkKeyboardColor.PRIMARY)
    keyboard.add_button("💰 Оплата и вывод", VkKeyboardColor.POSITIVE)
    keyboard.add_line()

    keyboard.add_button("🚴 Работа с заказами", VkKeyboardColor.PRIMARY)
    keyboard.add_button("⚠️ Проблемы", VkKeyboardColor.NEGATIVE)
    keyboard.add_line()

    keyboard.add_button("🧾 Как подтвердить самозанятость/ИП")
    keyboard.add_button("🧊 Термокороб")
    keyboard.add_line()

    keyboard.add_button("👨‍💻 Оператор")

    return keyboard.get_keyboard()

MAIN_KB = main_keyboard()

# =====================
# 📤 ОТПРАВКА
# =====================
def send(user_id, message, keyboard=True):
    vk.messages.send(
        user_id=user_id,
        message=message,
        random_id=random.randint(1, 2**63),
        keyboard=MAIN_KB if keyboard else None
    )

# =====================
# 🔔 УВЕДОМЛЕНИЕ АДМИНОВ
# =====================
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
            print(f"[ADMIN NOTIFY ERROR] {e}")

# =====================
# 🧠 ОТВЕТЫ БОТА
# =====================
def get_answer(text):
    text = text.lower()

    if "подключение" in text:
        return (
            "📲 Подключение:\n\n"
            "⚠️ Если нет самозанятости — оформите в приложении «Мой налог»\n"
            "📌 Если уже есть самозанятость — заполните форму:\n"
            "https://forms.fleet.yandex.ru/forms?ref_id=bc65abb3022140639ece9b33d42cdb64\n\n"
            "📌 Если у вас ИП — откройте ОКВЭД 53.20 и свяжитесь с парком по номеру +79339922926 с 7ч до 15ч по МСК или в меню нажмите кнопку → 👨‍💻оператор"
        )

    if "оплата" in text or "комис" in text:
        return (
            "💰 Оплата и комиссия:\n"
            "— комиссия парка с заказа: 4%\n"
            "— вывод средств: 1% (минимум 30₽)"
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
            "📌 ВАЖНО ЗНАТЬ❗️:\n" "Список советов, которые помогут избежать штрафов или оспорить уже выставленную корректировку:\n" 
            "1️⃣ При получении заказа, ВНИМАТЕЛЬНО сверьте номер в приложении и на самой посылке.\n" 
            "2️⃣ Обратите внимание, СКОЛЬКО ТОЧЕК у вас в заказе. В мультизаказе получение нескольких посылок в одном месте.\n" 
            "3️⃣НИ В КОЕМ СЛУЧАЕ, не нажимайте статус ПОСЫЛКА ПОЛУЧЕНА если Вы не забрали посылку(будет штраф).\n" 
            "4️⃣ Дозвониться в поддержку можно только с номера, указанного в профиле Яндекс Про при регистрациии.\n" 
            "5️⃣Если торговая точка закрыта или заказа нет в магазине-отменяйте заказ! (-7 баллов можно восполнить).\n" 
            "6️⃣Если вы завершили заказ по причине поломки автомобиля или ДТП, ОБЯЗАТЕЛЬНО сохраните чеки оплаты, извещение о ДТП.\n" 
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

    return (
        "👇 Выберите раздел или напишите вопрос подробнее.\n\n"
        "Для связи с оператором, выберите в меню кнопку 👨‍💻оператор и ожидайте ответа"
    )

# =====================
# 🚀 ЗАПУСК
# =====================
def main():
    print("Бот запущен...")

    for event in longpoll.listen():

        if event.type != VkEventType.MESSAGE_NEW:
            continue

        if not event.to_me:
            continue

        event_id = getattr(event, "message_id", None)

        if event_id and event_id in last_event:
            continue

        if event_id:
            last_event.add(event_id)

        user_id = event.user_id
        text = (event.text or "").strip().lower()

        # =====================
        # ❗ РЕЖИМ ОПЕРАТОРА
        # =====================
        if operator_mode.get(user_id):

            # выход из оператора
            if text == "стоп оператор":
                operator_mode[user_id] = False
                operator_queue.pop(user_id, None)

                send(
                    user_id,
                    "✅ Бот снова активен\n\n👇 Можете пользоваться кнопками"
                )

                continue

            # уведомление админов
            operator_queue[user_id] = True

            notify_admins(user_id, text)

            continue

        # =====================
        # 👨‍💻 ВКЛЮЧЕНИЕ ОПЕРАТОРА
        # =====================
        if text in ("👨‍💻 оператор", "оператор"):

            operator_mode[user_id] = True

            send(
                user_id,
                "👨‍💻 Вы подключены к оператору.\n\n"
                "✍️ Напишите свой вопрос — оператор его увидит.\n\n"
                "⏳ Ожидайте ответа.\n\n"
                "👉 Чтобы выйти: напишите СТОП ОПЕРАТОР"
            )

            # уведомляем админов о новом подключении
            notify_admins(
                user_id,
                "Пользователь подключился к оператору"
            )

            continue

        # =====================
        # 🤖 ОБЫЧНЫЙ БОТ
        # =====================
        answer = get_answer(text)

        send(user_id, answer)

if __name__ == "__main__":
    main()
