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
    raise RuntimeError("❌ VK_TOKEN не найден в переменных окружения")

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

    if "стоп оператор" in text:
        operator_mode[user_id] = False
        return "✅ Бот снова активен"

    if "подключение" in text:
        return "📲 Подключение:\n\n..."

    if "оплата" in text or "комис" in text:
        return "💰 Оплата и комиссия:\n— комиссия парка с заказа: 4%\n— вывод средств: 1% (минимум 30₽)"

    if "вывод" in text:
        return "💳 Вывод средств:\nДеньги → баланс → ещё → реквизиты"

    if "самозанятость" in text or "ип" in text:
        return "🧾 Подтверждение самозанятости/ИП:\n..."

    if "термокороб" in text or "короб" in text:
        return "🧊 Термокороб:\nИнвентарь → Получить инвентарь"

    if "оператор" in text:
        operator_mode[user_id] = True
        return "👨‍💻 Вы подключены к оператору.\nНапишите: СТОП ОПЕРАТОР"

    return "👇 Выберите раздел или напишите вопрос подробнее"

# =====================
# 🚀 ЗАПУСК
# =====================
def main():
    print("Бот запущен...")

    for event in longpoll.listen():

        if event.type != VkEventType.MESSAGE_NEW:
            continue

        # ✅ защита от дублей событий
        if event.message_id in last_event:
            continue
        last_event.add(event.message_id)

        user_id = event.user_id
        text = event.text.strip().lower()

        # если пишет оператор
        if event.from_me:
            operator_mode[user_id] = True
            continue

        if event.to_me:

            if text == "стоп оператор":
                operator_mode[user_id] = False
                send(user_id, "✅ Бот снова активен")
                continue

            if operator_mode.get(user_id):
                continue

            answer = get_answer(text, user_id)
            send(user_id, answer)

if __name__ == "__main__":
    main()