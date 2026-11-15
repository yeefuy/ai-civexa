import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from agents_core import run_multi_agent_system

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")

async def handle_telegram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user_text = update.message.text
    chat_id = update.message.chat_id

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    try:
        reply_text, pdf_path = await asyncio.to_thread(run_multi_agent_system, user_text)
        await update.message.reply_text(reply_text)
        
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as pdf_file:
                await context.bot.send_document(chat_id=chat_id, document=pdf_file)
            os.remove(pdf_path)
    except Exception as e:
        await update.message.reply_text(f"⚠️ 系統處理異常：{str(e)}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    tg_app = Application.builder().token(TELEGRAM_TOKEN).build()
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telegram_message))
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling(drop_pending_updates=True)
    yield
    await tg_app.updater.stop()
    await tg_app.stop()
    await tg_app.shutdown()

app = FastAPI(lifespan=lifespan)

@app.get("/")
@app.head("/")
def health_check():
    return {"status": "Enterprise Multi-Agent Cloud Butler is Running 24/7!"}
