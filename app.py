import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from agents_core import run_multi_agent_system

# 从环境变量读取配置
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "")

async def handle_telegram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    user_text = update.message.text.strip()
    chat_id = update.message.chat_id

    # 白名单检查 (可选)
    if OWNER_CHAT_ID and str(chat_id) != str(OWNER_CHAT_ID):
        await update.message.reply_text("⛔ 此為 CIVEXA 內部 AI 管家，無權限用戶請聯繫管理員。")
        return

    # 强制模式识别
    force_mode = None
    actual_message = user_text

    if user_text.lower().startswith('/inv'):
        force_mode = "INVOICE"
        actual_message = user_text[4:].strip()
        await context.bot.send_message(chat_id, "🔒 已强制切换至【发票模式 INVOICE】")
    elif user_text.lower().startswith('/qt'):
        force_mode = "QUOTATION"
        actual_message = user_text[3:].strip()
        await context.bot.send_message(chat_id, "🔒 已强制切换至【估价单模式 QUOTATION】")

    if not actual_message:
        await update.message.reply_text("请输入具体内容，例如：/inv 给 Yanda 开 INV-10052...")
        return

    # 显示正在输入
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    # 调用 AI 核心逻辑
    try:
        reply_text, pdf_path = await asyncio.to_thread(
            run_multi_agent_system, 
            actual_message, 
            force_mode=force_mode
        )
        
        # 发送文字回复
        if reply_text:
            await update.message.reply_text(reply_text)

        # 发送 PDF 附件
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as pdf_file:
                await context.bot.send_document(chat_id=chat_id, document=pdf_file)
            os.remove(pdf_path)
            
    except Exception as e:
        await update.message.reply_text(f"⚠️ 系統處理異常：{str(e)}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动 Telegram Bot (Polling 模式)
    tg_app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # 【关键修复】只用一个 handler 处理所有文本消息（包括 /inv 和 /qt 开头的）
    # 不再用 filters.COMMAND 过滤，让 handle_telegram_message 自己判断
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
