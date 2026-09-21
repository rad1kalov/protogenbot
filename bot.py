import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	if update.message:
		await update.message.reply_text("Привет! Бот работает.")


def main() -> None:
	if not TOKEN:
		raise RuntimeError("Укажите BOT_TOKEN в файле .env")

	application = Application.builder().token(TOKEN).build()
	application.add_handler(CommandHandler("start", start))
	application.run_polling()


if __name__ == "__main__":
	main()
