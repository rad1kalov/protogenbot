import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
	Application,
	BusinessConnectionHandler,
	BusinessMessagesDeletedHandler,
	ContextTypes,
	MessageHandler,
	filters,
)


load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

business_accounts: dict[str, int] = {}
message_cache: dict[tuple[str, int, int], str] = {}


async def on_business_connection(
	update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
	connection = update.business_connection
	if connection:
		business_accounts[connection.id] = connection.user_chat_id


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
	message_text = text or f"[{content_type}]"
	message_cache[
		(message.business_connection_id, chat.id, message.message_id)
	] = (
		f"{message_text}\n"
		f"Отправитель: {sender}\n"
		f"Время: {datetime.now(timezone.utc).isoformat()}"
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

	account_id = business_accounts.get(deleted.business_connection_id)
	if not account_id:
		return

	for message_id in deleted.message_ids:
		key = (deleted.business_connection_id, deleted.chat.id, message_id)
		archived_message = message_cache.pop(key, None)
		if archived_message:
			await context.bot.send_message(
				chat_id=account_id,
				text=f"Удалено сообщение:\n\n{archived_message}",
			)


def main() -> None:
	if not TOKEN:
		raise RuntimeError("Укажите BOT_TOKEN в файле .env")

	application = Application.builder().token(TOKEN).build()
	application.add_handler(BusinessConnectionHandler(on_business_connection))
	application.add_handler(
		MessageHandler(filters.UpdateType.BUSINESS_MESSAGE, on_business_message)
	)
	application.add_handler(BusinessMessagesDeletedHandler(on_business_messages_deleted))
	application.run_polling()


if __name__ == "__main__":
	main()