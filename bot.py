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
# 🧠 ПАМЯТЬ
# =====================
last_event = set()
operator_mode = {}

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

# =====================
# 📤 ОТПРАВКА
# =====================
def send(user_id, message):
    vk.messages.send(
        user_id=user_id,
        message=message,
        random_id=random.randint(1, 2**31),
        keyboard=main_keyboard(),
    )

# =====================
# 🧠 ОТВЕТЫ
# =====================
def get_answer(text, user_id):
    text = text.lower()

    if "подключение" in text:
        return (
            "📲 Подключение:\n\n"
            "⚠️ Если нет самозанятости — оформите в приложении «Мой налог»\n"
            "📌 Если уже есть самозанятость — заполните форму:\n"
            "https://forms.fleet.yandex.ru/forms?ref_id=9b19cd7f604441c7abbb312cb9fb6160\n\n"
            "📌 Если у вас ИП — откройте ОКВЭД 53.20 и свяжитесь с парком по номеру +79339922926 с 7ч до 15ч по МСК"
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
            "1. Включить «на линии»\n"
            "2. Принять заказ\n"
            "3. Забрать и доставить\n\n"
            "📌 Важно соблюдать правила, чтобы избежать штрафов"
        )

    if "проблем" in text:
        return (
            "⚠️ Если возникли проблемы:\n"
            "— проверьте заказ\n"
            "— обратитесь в поддержку\n"
            "— или напишите оператору"
        )

    if "самозанятость" in text or "ип" in text:
        return (
            "🧾 Подтверждение самозанятости/ИП:\n\n"
            "📌 Самозанятые:\n"
            "Напишите ФИО, номер, дату рождения и адрес проживания\n\n"
            "📌 ИП:\n"
            "Откройте ОКВЭД 53.20 и свяжитесь с оператором"
        )

    if "термокороб" in text or "короб" in text:
        return "🧊 Термокороб:\nИнвентарь → Получить инвентарь"

    if text == "👨‍💻 оператор" or text == "оператор":
        operator_mode[user_id] = True
        return (
            "👨‍💻 Вы подключены к оператору.\n\n"
            "✍️ Напишите свой вопрос — вам ответит человек.\n\n"
            "❗ Чтобы вернуться к боту и кнопкам, напишите:\n"
            "👉 СТОП ОПЕРАТОР"
        )

    return "👇 Выберите раздел или напишите вопрос подробнее"

# =====================
# 🚀 ЗАПУСК
# =====================
def main():
    print("Бот запущен...")

    for event in longpoll.listen():

        if event.type != VkEventType.MESSAGE_NEW:
            continue

        # защита от дублей
        event_id = getattr(event, "message_id", None)
        if event_id:
            if event_id in last_event:
                continue
            last_event.add(event_id)

        user_id = event.user_id
        text = event.text.strip().lower()

        # если пишешь ты (оператор)
        if event.from_me:
            operator_mode[user_id] = True
            continue

        # выход из оператора
        if text == "стоп оператор":
            operator_mode[user_id] = False
            send(user_id, "✅ Бот снова активен\n\n👇 Можете снова пользоваться кнопками")
            continue

        # если включён оператор — подсказываем
        if operator_mode.get(user_id):
            send(
                user_id,
                "👨‍💻 Вы сейчас в режиме оператора.\n\n"
                "✍️ Напишите вопрос — вам ответит человек.\n\n"
                "❗ Чтобы вернуться к боту, напишите:\n"
                "👉 СТОП ОПЕРАТОР"
            )
            continue

        # ответ бота
        answer = get_answer(text, user_id)
        send(user_id, answer)

if __name__ == "__main__":
    main()
