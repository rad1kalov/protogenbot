import logging
import os
import sqlite3
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

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
DB_PATH = os.getenv("DB_PATH", "messages.db")
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "downloads"))
logger = logging.getLogger("protogenbot")
DB: sqlite3.Connection | None = None
greeted_chats: set[tuple[str, int]] = set()

INSTRUCTION_TEXT = (
	"Инструкция по подключению:\n\n"
	"1. Откройте Telegram и перейдите в Настройки.\n"
	"2. Откройте Telegram Business.\n"
	"3. Выберите Чат-боты и добавьте этого бота.\n"
	"4. Разрешите боту доступ к сообщениям.\n"
	"5. После подключения просто напишите любое сообщение.\n\n"
	"Удалённые сообщения и медиа будут отправляться в этот личный чат."
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


def init_db() -> sqlite3.Connection:
	connection = sqlite3.connect(DB_PATH, check_same_thread=False)
	connection.execute(
		"""
		CREATE TABLE IF NOT EXISTS messages (
			message_id INTEGER NOT NULL,
			chat_id INTEGER NOT NULL,
			from_user_id INTEGER,
			from_user_name TEXT,
			text TEXT,
			media_path TEXT,
			media_type TEXT,
			date TEXT NOT NULL,
			business_connection_id TEXT NOT NULL,
			is_ephemeral INTEGER NOT NULL DEFAULT 0,
			PRIMARY KEY (message_id, chat_id)
		)
		"""
	)
	connection.execute(
		"""
		CREATE TABLE IF NOT EXISTS business_connections (
			connection_id TEXT PRIMARY KEY,
			owner_chat_id INTEGER NOT NULL,
			enabled INTEGER NOT NULL DEFAULT 1
		)
		"""
	)
	connection.commit()
	return connection


def start_markup() -> InlineKeyboardMarkup:
	return InlineKeyboardMarkup(
		[[InlineKeyboardButton("Инструкция", callback_data="instruction")]]
	)


def content_type(message) -> str:
	if message.photo:
		return "photo"
	if message.video:
		return "video"
	if message.voice:
		return "voice"
	if message.audio:
		return "audio"
	if message.document:
		return "document"
	if message.video_note:
		return "video_note"
	if message.sticker:
		return "sticker"
	if message.location:
		return "location"
	if message.contact:
		return "contact"
	return "text"


async def download_media(message, context: ContextTypes.DEFAULT_TYPE):
	attachment = message.effective_attachment
	if not attachment:
		return None, None
	if isinstance(attachment, tuple):
		attachment = attachment[-1]

	try:
		file = await context.bot.get_file(attachment.file_id)
		extension = os.path.splitext(file.file_path or "")[1] or ".bin"
		path = MEDIA_DIR / f"{message.chat_id}_{message.message_id}{extension}"
		await file.download_to_drive(str(path))
		return str(path), content_type(message)
	except Exception:
		logger.exception("Failed to download media for message %s", message.message_id)
		return None, None


async def send_media_to_owner(
	context: ContextTypes.DEFAULT_TYPE,
	owner_id: int,
	media_path: str | None,
	media_kind: str | None,
	caption: str,
) -> None:
	if not media_path or not os.path.exists(media_path):
		return

	try:
		with open(media_path, "rb") as media_file:
			if media_kind == "photo":
				await context.bot.send_photo(owner_id, media_file, caption=caption)
			elif media_kind == "video":
				await context.bot.send_video(owner_id, media_file, caption=caption)
			elif media_kind == "voice":
				await context.bot.send_voice(owner_id, media_file, caption=caption)
			elif media_kind == "audio":
				await context.bot.send_audio(owner_id, media_file, caption=caption)
			elif media_kind == "video_note":
				await context.bot.send_video_note(owner_id, media_file)
				await context.bot.send_message(owner_id, caption)
			else:
				await context.bot.send_document(owner_id, media_file, caption=caption)
		logger.info("Media sent to owner %s: %s", owner_id, media_path)
	except Exception:
		logger.exception("Failed to send media to owner %s", owner_id)


async def log_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	logger.info("Update received: %s", update.to_dict())


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	if update.message:
		await update.message.reply_text(
			"Привет! Бот работает в режиме секретаря.",
			reply_markup=start_markup(),
		)


async def on_business_connection(
	update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
	connection = update.business_connection
	if not connection or DB is None:
		return

	DB.execute(
		"""
		INSERT INTO business_connections (connection_id, owner_chat_id, enabled)
		VALUES (?, ?, ?)
		ON CONFLICT(connection_id) DO UPDATE SET
		owner_chat_id = excluded.owner_chat_id,
		 enabled = excluded.enabled
		""",
		(connection.id, connection.user_chat_id, int(connection.is_enabled)),
	)
	DB.commit()
	logger.info(
		"Business connection updated: id=%s owner=%s enabled=%s",
		connection.id,
		connection.user_chat_id,
		connection.is_enabled,
	)


async def on_business_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	if DB is None:
		return

	message = update.business_message
	chat = update.effective_chat
	if not message or not chat or not message.business_connection_id:
		return

	media_path, media_kind = await download_media(message, context)
	user = message.from_user
	from_name = user.full_name if user else "Unknown"
	from_id = user.id if user else None
	text = message.text or message.caption or ""
	is_ephemeral = bool(
		getattr(message, "ttl", None)
		or getattr(message, "has_media_spoiler", False)
	)

	DB.execute(
		"""
		INSERT OR REPLACE INTO messages
		(message_id, chat_id, from_user_id, from_user_name, text, media_path,
		 media_type, date, business_connection_id, is_ephemeral)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		""",
		(
			message.message_id,
			chat.id,
			from_id,
			from_name,
			text,
			media_path,
			media_kind,
			datetime.now().isoformat(timespec="seconds"),
			message.business_connection_id,
			int(is_ephemeral),
		),
	)
	DB.commit()
	logger.info(
		"Saved business message: connection=%s chat=%s message=%s media=%s",
		message.business_connection_id,
		chat.id,
		message.message_id,
		media_kind,
	)

	chat_key = (message.business_connection_id, chat.id)
	if chat_key not in greeted_chats or text.split(maxsplit=1)[:1] == ["/start"]:
		greeted_chats.add(chat_key)
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
		await context.bot.send_message(
			chat_id=message.chat.id,
			text=INSTRUCTION_TEXT,
			business_connection_id=message.business_connection_id,
		)
	else:
		await context.bot.send_message(query.from_user.id, INSTRUCTION_TEXT)


async def on_deleted_messages(
	update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
	if DB is None or not update.deleted_business_messages:
		return

	deleted = update.deleted_business_messages
	owner_row = DB.execute(
		"SELECT owner_chat_id FROM business_connections WHERE connection_id = ?",
		(deleted.business_connection_id,),
	).fetchone()
	if not owner_row:
		logger.warning("Owner not found for connection %s", deleted.business_connection_id)
		return

	owner_id = owner_row[0]
	for message_id in deleted.message_ids:
		row = DB.execute(
			"""
			SELECT from_user_id, from_user_name, text, media_path, media_type, date
			FROM messages
			WHERE message_id = ? AND chat_id = ? AND business_connection_id = ?
			""",
			(message_id, deleted.chat.id, deleted.business_connection_id),
		).fetchone()
		if not row:
			logger.warning("Deleted message %s was not found in database", message_id)
			continue

		from_id, from_name, text, media_path, media_kind, date = row
		header = (
			"Удалено сообщение\n"
			f"Автор: {from_name} (ID: {from_id or 'unknown'})\n"
			f"Чат: {deleted.chat.id}\n"
			f"Дата: {date}"
		)
		if text:
			await context.bot.send_message(owner_id, f"{header}\n\n{text}")
		if media_path:
			await send_media_to_owner(context, owner_id, media_path, media_kind, header)
		logger.info(
			"Forwarded deleted message: connection=%s chat=%s message=%s owner=%s",
			deleted.business_connection_id,
			deleted.chat.id,
			message_id,
			owner_id,
		)


def main() -> None:
	global DB
	if not TOKEN:
		raise RuntimeError("Укажите BOT_TOKEN в файле .env")

	configure_logging()
	MEDIA_DIR.mkdir(parents=True, exist_ok=True)
	DB = init_db()
	application = Application.builder().token(TOKEN).build()
	application.add_handler(TypeHandler(Update, log_update), group=-1)
	application.add_handler(CommandHandler("start", on_start))
	application.add_handler(BusinessConnectionHandler(on_business_connection))
	application.add_handler(
		MessageHandler(filters.UpdateType.BUSINESS_MESSAGE, on_business_message)
	)
	application.add_handler(CallbackQueryHandler(on_instruction, pattern="^instruction$"))
	application.add_handler(BusinessMessagesDeletedHandler(on_deleted_messages))
	logger.info("Bot started")
	application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
	main()