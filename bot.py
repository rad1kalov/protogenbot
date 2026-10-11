import os
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from dotenv import load_dotenv

# Загружаем переменные окружения из файла .env
load_dotenv()

# Достаем токен и ссылку
TOKEN = os.getenv('BOT_TOKEN')
WEB_URL = os.getenv('WEB_APP_URL')

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start_handler(message):
    # Создаем клавиатуру с кнопкой Web App
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    btn = KeyboardButton(text='🚀 Открыть Решатель Фано', web_app=WebAppInfo(url=WEB_URL))
    markup.add(btn)
    
    # Отправляем сообщение
    bot.send_message(
        message.chat.id, 
        'ProtogenBot v0.1 приветсвует тебя!\n Внизу кнопки с доступными фукнкциями.', 
        reply_markup=markup
    )

print("Бот запущен и ждет команду /start...")
bot.polling(non_stop=True)