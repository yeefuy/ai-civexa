import os
import logging
import requests
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from agents_core import run_multi_agent_system

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("civexa-bot")

app = FastAPI()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "")  # 留空=不限制；填了=只有老板能用
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _send_text(chat_id, text: str):
    try:
        requests.post(f"{TG_API}/sendMessage", json={
            "chat_id": chat_id, "text": text, "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }, timeout=20)
    except Exception as e:
        logger.error(f"send_text fail: {e}")


def _send_pdf(chat_id, path: str, caption: str):
    try:
        with open(path, "rb") as f:
            requests.post(f"{TG_API}/sendDocument",
                          data={"chat_id": chat_id, "caption": caption},
                          files={"document": f}, timeout=60)
    except Exception as e:
        logger.error(f"send_pdf fail: {e}")


@app.get("/")
def root():
    return {"status": "ok", "service": "CIVEXA AI Manager"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook")
async def telegram_webhook(req: Request):
    # 1) 校驗 Telegram 密鑰，防惡意調用
    secret = req.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        return {"ok": False, "reason": "bad secret"}

    data = await req.json()
    msg = data.get("message") or data.get("edited_message")
    if not msg:
        return {"ok": True}

    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    if not text:
        return {"ok": True}

    # 2) 白名單：只有老板可操作發票（防外人亂開票）
    if OWNER_CHAT_ID and str(chat_id) != str(OWNER_CHAT_ID):
        _send_text(chat_id, "⛔ 此為 CIVEXA 內部 AI 管家，無權限用戶請聯繫管理員。")
        return {"ok": True}

    # 3) 跑多 Agent（放線程池，避免阻塞事件循環）
    try:
        reply, pdf_path = await run_in_threadpool(run_multi_agent_system, text)
    except Exception as e:
        logger.exception("agent error")
        _send_text(chat_id, f"❌ 管家處理失敗：{e}")
        return {"ok": True}

    # 4) 有 PDF 就發附件並清理 /tmp；否則發文字
    if pdf_path and os.path.exists(pdf_path):
        _send_pdf(chat_id, pdf_path, reply)
        try:
            os.remove(pdf_path)
        except Exception:
            pass
    else:
        _send_text(chat_id, reply)

    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    # 【關鍵修正】端口讀 Render 注入的 PORT，默認 7860 僅本地調試用
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
