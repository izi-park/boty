import os
import random
import vk_api

from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.longpoll import VkEventType, VkLongPoll

# =====================
# 🔑 ТОКЕН
# =====================
DEFAULT_TOKEN = "vk1.a.eXe01GD66CPVaIkxfNX3dzAdlFbcEaxBFUBHBiItX4gzoQhJkKRtHgH-ZqdZr8o4T3KJgkiVLdQnHjlSNe2GRYyd9w328J2sAEwAtAenegFX28-PZeIL5YqTy-UvPT45yt9s0rKYQgI-wUSgIHxDw8zoNQKhtdUtSsj_iq5vQQ8StnxGOp_-TAr2Q4hCFWp_IrAmQbGsKZ3Nj65KejnyvA"
TOKEN = os.getenv("VK_TOKEN", DEFAULT_TOKEN)

vk_session = vk_api.VkApi(token=TOKEN)
vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)

# =====================
# 🧠 ПАМЯТЬ
# =====================
# пользователи, с которыми сейчас работает оператор
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
        random_id=random.randint(1, 2**31),  # ✅ фикс дублей
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

    if "подключ" in text:
        return (
            "📲 Подключение:\n\n"
            "⚠️ Если нет самозанятости — оформите в приложении «Мой налог»\n"
            "📌 Если уже есть самозанятость — заполните форму:\n"
            "https://forms.fleet.yandex.ru/forms?ref_id=9b19cd7f604441c7abbb312cb9fb6160\n\n"
            "📌 Если у вас ИП — откройте ОКВЭД 53.20 и свяжитесь с парком по номеру +79339922926 с 7ч до 15ч по МСК"
        )

    if "оплат" in text or "комис" in text:
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

    if "не приш" in text:
        return (
            "⚠️ Если деньги не пришли:\n"
            "— подождать до 24 часов\n"
            "— проверить реквизиты\n"
            "— написать оператору парка"
        )

    if "заказ" in text:
        return (
            "🚴 Работа с заказами:\n"
            "1. Включить «на линии».\n"
            "2. Принять заказ.\n"
            "3. Забрать и доставить.\n\n"
            "📌 Чтобы выйти с линии:\n"
            "во время последнего заказа нажмите на круглый значок приоритета и выйдите с линии.\n\n"
            "📌 ВАЖНО:\n"
            "— проверяйте номер заказа\n"
            "— не нажимайте 'получено' заранее\n"
            "— при проблемах отменяйте заказ\n"
        )

    if "самозан" in text or "ип" in text:
        return (
            "🧾 Подтверждение самозанятости/ИП:\n\n"
            "Напишите ФИО, номер, дату рождения и адрес — оператор ответит"
        )

    if "термо" in text or "короб" in text:
        return (
            "🧊 Термокороб:\n"
            "Инвентарь → Получить инвентарь"
        )

    if "оператор" in text:
        operator_mode[user_id] = True
        return (
            "👨‍💻 Оператор подключится.\n"
            "Бот временно остановлен."
        )

    return "👇 Выберите раздел или напишите вопрос подробнее"

# =====================
# 🚀 ЗАПУСК
# =====================
def main():
    if not TOKEN:
        raise RuntimeError("VK token is not set.")

    for event in longpoll.listen():

        if event.type != VkEventType.MESSAGE_NEW:
            continue

        user_id = event.user_id

        # 📩 пользователь пишет
        if event.to_me and not event.from_me:

            # если оператор уже отвечает — бот молчит
            if operator_mode.get(user_id):
                continue

            answer = get_answer(event.text, user_id)
            send(user_id, answer)

        # 👨‍💻 пишет оператор
        if event.from_me:
            operator_mode[user_id] = True

if __name__ == "__main__":
    main()

