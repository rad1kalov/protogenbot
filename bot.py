import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
	Application,
	BusinessConnectionHandler,
	BusinessMessagesDeletedHandler,
	CallbackQueryHandler,
	CommandHandler,
	ContextTypes,
	MessageHandler,
	TypeHandler,
	filters,
)


load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
logger = logging.getLogger("protogenbot")

business_accounts: dict[str, int] = {}
message_cache: dict[tuple[str, int, int], str] = {}

INSTRUCTION_TEXT = (
	"Инструкция по подключению:\n\n"
	"1. Откройте Telegram и перейдите в Настройки.\n"
	"2. Откройте Telegram Business.\n"
	"3. Выберите Чат-боты и добавьте этого бота.\n"
	"4. Разрешите боту доступ к сообщениям.\n"
	"5. После подключения отправьте /start в нужном бизнес-чате.\n\n"
	"После этого бот будет присылать удалённые сообщения в личный чат владельца аккаунта."
)


def configure_logging() -> None:
	formatter = logging.Formatter(
		"%(asctime)s | %(levelname)s | %(name)s | %(message)s"
	)
	file_handler = RotatingFileHandler(
		"bot.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
	)
	console_handler = logging.StreamHandler()
	file_handler.setFormatter(formatter)
	console_handler.setFormatter(formatter)
	logger.setLevel(logging.INFO)
	logger.addHandler(file_handler)
	logger.addHandler(console_handler)


async def log_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	logger.info("Update received: %s", update.to_dict())


def start_markup() -> InlineKeyboardMarkup:
	return InlineKeyboardMarkup(
		[[InlineKeyboardButton("Инструкция", callback_data="instruction")]]
	)


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	if update.message:
		logger.info("Start command received in regular chat: chat=%s", update.message.chat.id)
		await update.message.reply_text(
			"Привет! Бот работает в режиме секретаря.",
			reply_markup=start_markup(),
		)


async def on_business_connection(
	update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
	connection = update.business_connection
	if connection:
		business_accounts[connection.id] = connection.user_chat_id
		logger.info(
			"Business connection %s: user_chat_id=%s enabled=%s",
			connection.id,
			connection.user_chat_id,
			connection.is_enabled,
		)


async def on_business_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	message = update.business_message
	chat = update.effective_chat
	if not message or not chat or not message.business_connection_id:
		return

	text = message.text or message.caption
	content_type = "text"
	if message.photo:
		content_type = "photo"
	elif message.video:
		content_type = "video"
	elif message.document:
		content_type = "document"
	elif message.audio:
		content_type = "audio"
	elif message.voice:
		content_type = "voice"
	elif message.sticker:
		content_type = "sticker"
	elif message.location:
		content_type = "location"
	elif message.contact:
		content_type = "contact"

	user = message.from_user
	sender = f"@{user.username}" if user and user.username else "без username"
	logger.info(
		"Business message received: connection=%s chat=%s message=%s type=%s sender=%s",
		message.business_connection_id,
		chat.id,
		message.message_id,
		content_type,
		sender,
	)
	message_text = text or f"[{content_type}]"
	message_cache[
		(message.business_connection_id, chat.id, message.message_id)
	] = (
		f"{message_text}\n"
		f"Отправитель: {sender}\n"
		f"Время: {datetime.now(timezone.utc).isoformat()}"
	)

	if text and text.split(maxsplit=1)[0].split("@", maxsplit=1)[0] == "/start":
		logger.info(
			"Sending start response: connection=%s chat=%s",
			message.business_connection_id,
			chat.id,
		)
		await context.bot.send_message(
			chat_id=chat.id,
			text="Привет! Бот работает в режиме секретаря.",
			business_connection_id=message.business_connection_id,
			reply_markup=start_markup(),
		)


async def on_instruction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	query = update.callback_query
	if not query:
		return

	await query.answer()
	message = query.message
	if message and message.business_connection_id:
		logger.info(
			"Instruction requested: connection=%s chat=%s user=%s",
			message.business_connection_id,
			message.chat.id,
			query.from_user.id,
		)
		await context.bot.send_message(
			chat_id=message.chat.id,
			text=INSTRUCTION_TEXT,
			business_connection_id=message.business_connection_id,
		)
	else:
		logger.info("Instruction requested in regular chat: user=%s", query.from_user.id)
		await context.bot.send_message(
			chat_id=query.from_user.id,
			text=INSTRUCTION_TEXT,
		)


async def on_business_messages_deleted(
	update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
	deleted = update.deleted_business_messages
	if not deleted:
		return

	account_id = business_accounts.get(deleted.business_connection_id)
	logger.info(
		"Business messages deleted: connection=%s chat=%s message_ids=%s account_id=%s",
		deleted.business_connection_id,
		deleted.chat.id,
		deleted.message_ids,
		account_id,
	)
	if not account_id:
		logger.warning(
			"Cannot forward deleted messages: unknown business connection %s",
			deleted.business_connection_id,
		)
		return

	for message_id in deleted.message_ids:
		key = (deleted.business_connection_id, deleted.chat.id, message_id)
		archived_message = message_cache.pop(key, None)
		if archived_message:
			logger.info(
				"Forwarding deleted message: connection=%s chat=%s message=%s account=%s",
				deleted.business_connection_id,
				deleted.chat.id,
				message_id,
				account_id,
			)
			await context.bot.send_message(
				chat_id=account_id,
				text=f"Удалено сообщение:\n\n{archived_message}",
			)
		else:
			logger.warning(
				"Deleted message was not found in memory: connection=%s chat=%s message=%s",
				deleted.business_connection_id,
				deleted.chat.id,
				message_id,
			)


def main() -> None:
	if not TOKEN:
		raise RuntimeError("Укажите BOT_TOKEN в файле .env")

	configure_logging()
	logger.info("Starting bot")
	application = Application.builder().token(TOKEN).build()
	application.add_handler(TypeHandler(Update, log_update), group=-1)
	application.add_handler(CommandHandler("start", on_start))
	application.add_handler(BusinessConnectionHandler(on_business_connection))
	application.add_handler(
		MessageHandler(filters.UpdateType.BUSINESS_MESSAGE, on_business_message)
	)
	application.add_handler(CallbackQueryHandler(on_instruction, pattern="^instruction$"))
	application.add_handler(BusinessMessagesDeletedHandler(on_business_messages_deleted))
	application.run_polling()


if __name__ == "__main__":
	main()