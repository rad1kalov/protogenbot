import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
	Application,
	BusinessMessagesDeletedHandler,
	ContextTypes,
	MessageHandler,
	filters,
)


load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_PATH = Path(__file__).with_name("messages.db")


def initialize_database() -> None:
	with sqlite3.connect(DATABASE_PATH) as connection:
		connection.execute(
			"""
			CREATE TABLE IF NOT EXISTS business_messages (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				business_connection_id TEXT NOT NULL,
				chat_id INTEGER NOT NULL,
				message_id INTEGER NOT NULL,
				user_id INTEGER,
				username TEXT,
				created_at TEXT NOT NULL,
				text TEXT,
				content_type TEXT NOT NULL,
				deleted_at TEXT
			)
			"""
		)


async def on_business_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
	message = update.business_message
	chat = update.effective_chat
	if not message or not chat or not message.business_connection_id:
		return

	content_type = "text"
	text = message.text or message.caption
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
	with sqlite3.connect(DATABASE_PATH) as connection:
		connection.execute(
			"""
			INSERT INTO business_messages
			(business_connection_id, chat_id, message_id, user_id, username,
			 created_at, text, content_type)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?)
			""",
			(
				message.business_connection_id,
				chat.id,
				message.message_id,
				user.id if user else None,
				user.username if user else None,
				datetime.now(timezone.utc).isoformat(),
				text,
				content_type,
			),
		)

	if text and text.split(maxsplit=1)[0].split("@", maxsplit=1)[0] == "/start":
		await context.bot.send_message(
			chat_id=chat.id,
			text="Привет! Бот работает в режиме секретаря.",
			business_connection_id=message.business_connection_id,
		)


async def on_business_messages_deleted(
	update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
	deleted = update.deleted_business_messages
	if not deleted:
		return

	with sqlite3.connect(DATABASE_PATH) as connection:
		connection.executemany(
			"""
			UPDATE business_messages
			SET deleted_at = ?
			WHERE business_connection_id = ? AND chat_id = ? AND message_id = ?
			""",
			(
				(
					datetime.now(timezone.utc).isoformat(),
					deleted.business_connection_id,
					deleted.chat.id,
					message_id,
				)
				for message_id in deleted.message_ids
			),
		)


def main() -> None:
	if not TOKEN:
		raise RuntimeError("Укажите BOT_TOKEN в файле .env")

	initialize_database()
	application = Application.builder().token(TOKEN).build()
	application.add_handler(
		MessageHandler(filters.UpdateType.BUSINESS_MESSAGE, on_business_message)
	)
	application.add_handler(BusinessMessagesDeletedHandler(on_business_messages_deleted))
	application.run_polling()


if __name__ == "__main__":
	main()