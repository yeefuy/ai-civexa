import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from agents_core import run_multi_agent_system

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")   # 与你 Render 现有变量名一致
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "")  # 可选：填你的ID则只响应你

async def handle_telegram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user_text = update.message.text
    chat_id = update.message.chat_id

    # 可选白名单：防止外人乱开发票
    if OWNER_CHAT_ID and str(chat_id) != str(OWNER_CHAT_ID):
        await update.message.reply_text("⛔ 此為 CIVEXA 內部 AI 管家，無權限用戶請聯繫管理員。")
        return

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

if __name__ == "__main__":
    import uvicorn
    # 端口讀 Render 注入的 PORT，避免健康檢查失敗
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))
