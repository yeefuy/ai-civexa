import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from agents_core import run_multi_agent_system

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "")

async def handle_telegram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    user_text = update.message.text.strip()
    chat_id = update.message.chat_id

    if OWNER_CHAT_ID and str(chat_id) != str(OWNER_CHAT_ID):
        await update.message.reply_text("⛔ 无权限。")
        return

    force_mode = None
    force_action = None
    actual_message = user_text

    # 1. 识别指令
    if user_text.lower().startswith('/inv'):
        force_mode = "INVOICE"
        actual_message = user_text[4:].strip()
        await context.bot.send_message(chat_id, "🔒 已强制切换至【发票模式 INVOICE】")
    elif user_text.lower().startswith('/qt'):
        force_mode = "QUOTATION"
        actual_message = user_text[3:].strip()
        await context.bot.send_message(chat_id, "🔒 已强制切换至【估价单模式 QUOTATION】")
    elif user_text.lower().startswith('/reg'):
        force_action = "REGISTER"
        actual_message = user_text[4:].strip()
        await context.bot.send_message(chat_id, "📝 进入【手动登记模式】，只存号码不生成 PDF。")
    elif user_text.lower().startswith('/sample'):
        force_action = "SAMPLE"  # <--- 关键：样本模式
        actual_message = "Generate sample." # 随便写，AI 会忽略，直接用虚拟数据
        await context.bot.send_message(chat_id, "🎨 正在生成排版样本（不查重、不存库）...")

    if not actual_message and force_action != "SAMPLE":
        await update.message.reply_text("请输入内容。")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        reply_text, pdf_path = await asyncio.to_thread(
            run_multi_agent_system, 
            actual_message, 
            force_mode=force_mode,
            force_action=force_action
        )
        
        if reply_text:
            await update.message.reply_text(reply_text)

        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as pdf_file:
                await context.bot.send_document(chat_id=chat_id, document=pdf_file)
            os.remove(pdf_path)
            
    except Exception as e:
        await update.message.reply_text(f"⚠️ 系统异常：{str(e)}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    tg_app = Application.builder().token(TELEGRAM_TOKEN).build()
    tg_app.add_handler(MessageHandler(filters.TEXT, handle_telegram_message))
    
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
    return {"status": "CIVEXA AI Manager is Running!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))
