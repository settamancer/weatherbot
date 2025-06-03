from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.filters import Command
from aiogram.types import Message
import sys
import logging
import asyncio
import requests
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram import F
from aiogram.types import CallbackQuery
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, time
import atexit
from config import API_TOKEN, weather_api_key, city, url, headers


# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Инициализация планировщика
scheduler = AsyncIOScheduler()

# Словарь для хранения данных пользователей
user_data = {}

#Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Остановка планировщика при завершении работы
atexit.register(lambda: scheduler.shutdown())

# Создаем клавиатуру с кнопками для выбора времени
def get_time_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Утро (08:00)", callback_data="time_morning"),
            InlineKeyboardButton(text="День (14:00)", callback_data="time_afternoon"),
        ],
        [
            InlineKeyboardButton(text="Вечер (19:00)", callback_data="time_evening"),
        ]
    ])
    return keyboard

# Обработчик команды /start
@dp.message(CommandStart())
async def start(message: Message):
    logger.info(f"Пользователь {message.from_user.full_name} запустил бота.")
    await message.answer(f"Привет, {message.from_user.full_name}! Я помогу тебе выбрать, что надеть.")

# Функция для получения погоды
def get_weather_moscow(city, api_key):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={weather_api_key}&units=metric"
    try:
        response = requests.get(url)
        data = response.json()
        return data
    except requests.exceptions.RequestException as e:
        logger.error(f'Ошибка при запросе к API погоды: {e}')
        return None

# Функция генерации рекомендации
def generate_recommendation(weather_data):
    if weather_data.get("cod") != 200:
        return "Не удалось получить данные о погоде. Проверьте API."

    temperature = weather_data["main"]["temp"]
    humidity = weather_data["main"]["humidity"]
    precipitation = "rain" in weather_data["weather"][0]["description"].lower()

    #Формируем запрос
    user_prompt = f"Сейчас на улице {temperature}°C, влажность {humidity}%. "
    user_prompt += f"{'Идёт дождь.' if precipitation else 'Дождя нет.'} "
    user_prompt += "Что лучше надеть?"
    
    try:
        prompt = {
    "modelUri": "gpt://b1gbrb3t8f13nr75ip8i/yandexgpt-lite",
    "completionOptions": {
        "stream": False,
        "temperature": 0.6,
        "maxTokens": "2000"
    },
    "messages": [
        {
            "role": "system",
            "text": "Ты помогаешь выбрать одежду, исходя из влажности и температуры."
        },
        {
            "role": "user",
            "text": user_prompt
        }
    ]
}
        
        response = requests.post(url, headers=headers, json=prompt)
        response_data = response.json()
        recommendation = response_data["result"]["alternatives"][0]["message"]["text"]
        recommendation = recommendation.replace("*", "")
        return recommendation
    except Exception as e:
        logger.error(f"Ошибка при запросе к yandex API: {e}")
        return "Не удалось сгенерировать рекомендацию. Попробуйте позже."

# Обработчик команды /weather
@dp.message(Command("weather"))
async def weather(message: Message):
    print("Команда /weather получена")
    try:
        logger.info(f"Пользователь {message.from_user.full_name} запросил погоду.")
        await message.answer("Выберите время для ежедневного уведомления о погоде:", reply_markup=get_time_keyboard())
        weather_data = get_weather_moscow(city, weather_api_key)
        if weather_data and weather_data.get("cod") == 200:
            logger.info(f"Данные о погоде получены: {weather_data}")
            recommendation = generate_recommendation(weather_data)
            await message.answer(recommendation)
        else:
            logger.error("Не удалось получить данные о погоде.")
            await message.answer("Не удалось получить данные о погоде. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Ошибка в обработчике команды /weather: {e}")
        await message.answer("Произошла ошибка при обработке запроса.")

# Словарь для преобразования callback_data в текстовые значения
time_mapping = {
    "time_morning": "Утро (08:00)",
    "time_afternoon": "День (14:00)",
    "time_evening": "Вечер (19:00)",
}

# Обработчик нажатия на кнопку
@dp.callback_query(F.data.startswith("time_"))
async def handle_time_selection(callback: CallbackQuery):
    user_id = callback.from_user.id
    selected_time = callback.data  # Например, "time_morning"

     # Получаем человекочитаемое название времени
    time_text = time_mapping.get(selected_time, "Неизвестное время")

    # Сохраняем выбранное время для пользователя
    user_data[user_id] = selected_time

    # Определяем время для уведомления
    if selected_time == "time_morning":
        notify_time = time(8, 0)
    elif selected_time == "time_afternoon":
        notify_time = time(14, 0)
    elif selected_time == "time_evening":
        notify_time = time(19, 0)

    # Добавляем задачу в планировщик
    scheduler.add_job(
        send_weather,
        trigger="cron",
        hour=notify_time.hour,
        minute=notify_time.minute,
        args=[user_id],
    )

    # Отправляем подтверждение
    await callback.message.answer(f"Вы выбрали время: {time_text}. Уведомления будут приходить ежедневно.")
    await callback.answer()

# Функция для отправки погоды
async def send_weather(user_id):
    weather_data = get_weather_moscow(city, weather_api_key)
    if weather_data and weather_data.get("cod") == 200:
        recommendation = generate_recommendation(weather_data)
        await bot.send_message(user_id, recommendation)
    else:
        await bot.send_message(user_id, "Не удалось получить данные о погоде. Попробуйте позже.")

async def main():
    # Запуск планировщика
    scheduler.start()


# Запуск
async def main():
    logger.info("Бот запущен.")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())