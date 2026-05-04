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

    if "вывод средств" in text:
        return (
            "💳 Вывод средств:\n"
            "Деньги → баланс → ещё → реквизиты\n\n"
            "⚡ Вывод моментальный, максимум до 15 000₽ в день"
        )

    if "не пришла оплата" in text:
        return (
            "⚠️ Если деньги не пришли:\n"
            "— подождать до 24 часов\n"
            "— проверить реквизиты\n"
            "— написать оператору парка"
        )

    if "как работать?" in text:
        return (
            "🚴 Работа с заказами:\n"
            "1. Включить «на линии».\n"
            "2. Принять заказ.\n"
            "3. Забрать и доставить.\n\n"
            "📌 Чтобы выйти с линии:\n"
            "во время последнего заказа нажмите на круглый значок приоритета и выйдите с линии.\n\n"
            "📌 ВАЖНО ЗНАТЬ❗️:\n"
            "Список советов, которые помогут избежать штрафов или оспорить уже выставленную корректировку:\n"
            "1️⃣  При получении заказа, ВНИМАТЕЛЬНО сверьте номер в приложении и на самой посылке.\n"
            "2️⃣  Обратите внимание, СКОЛЬКО ТОЧЕК у вас в заказе. В мультизаказе получение нескольких посылок в одном месте.\n"
            "3️⃣  НИ В КОЕМ СЛУЧАЕ, не нажимайте статус ПОСЫЛКА ПОЛУЧЕНА если Вы не забрали посылку(будет штраф).\n"
            "4️⃣  Дозвониться в поддержку можно только с номера, указанного в профиле Яндекс Про при регистрациии.\n"
            "5️⃣  Если торговая точка закрыта или заказа нет в магазине-отменяйте заказ! (-7 баллов можно восполнить).\n"
            "6️⃣  Если вы завершили заказ по причине поломки автомобиля или ДТП, ОБЯЗАТЕЛЬНО сохраните чеки оплаты, извещение о ДТП.\n"
            "7️⃣  Если заказ с опцией ОТ ДВЕРИ ДО ДВЕРИ, не отдавайте его на улице, нужно вручить заказ в квартиру.\n\n"
            "Эти простые правила, помогут вам обойти стороной штрафы, и неприятности на заказах."
        )

    if "самозанятость\ИП" in text or "ип" in text:
        return (
            "🧾 Подтверждение самозанятости/ИП:\n\n"
             "🧾 Подтверждение самозанятости/ИП:\n\n"
            "📌 Самозанятые:\n"
            "Напишите ФИО, номер, дату рождения и фактический адрес проживания: город, улица, дом и ждите ответа оператора.\n"
            "📌 ИП:\n"
            "открыть ОКВЭД 53.20 и связаться с оператором парка по номеру +79339922926 с 7ч до 15ч по МСК"
        )

    if "термокороб" in text or "короб" in text:
        return (
            "🧊 Термокороб:\n"
            "Инвентарь → Получить инвентарь"
        )

    if "оператор" in text:
        operator_mode[user_id] = True
        return (
            "👨‍💻 Вы подключены к оператору.\n\n"
            "Чтобы вернуть бота - напишите: СТОП ОПЕРАТОР"
        )

    return "👇 Выберите раздел или напишите вопрос подробнее"

# =====================
# 🚀 ЗАПУСК
# =====================
def main():
   def main():
    if not TOKEN:
        raise RuntimeError("VK token is not set.")

    print("Бот запущен...")

    for event in longpoll.listen():

        if event.type != VkEventType.MESSAGE_NEW:
            continue

        user_id = event.user_id

        # =====================
        # 👨‍💻 ПИШЕТ ОПЕРАТОР
        # =====================
        if event.from_me:
            operator_mode[user_id] = True
            continue

        # =====================
        # 📩 ПИШЕТ ПОЛЬЗОВАТЕЛЬ
        # =====================
        if event.to_me:

            text = event.text.lower()

            # ✅ ВСЕГДА можно выйти из оператора
            if text == "стоп оператор":
                operator_mode[user_id] = False
                send(user_id, "✅ Бот снова активен")
                continue

            # если оператор включён — бот молчит
            if operator_mode.get(user_id):
                continue

            # обычный ответ
            answer = get_answer(event.text, user_id)
            send(user_id, answer)

if __name__ == "__main__":
    main()
   
