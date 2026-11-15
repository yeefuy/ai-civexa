import os
import json
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# ================= 字體註冊（對齊 Dockerfile 的 fonts-wqy-zenhei）=================
# 默認英文 Helvetica（完美匹配 INV-10051 英文範本，粗體正常）。
# 若需在 Render 設 USE_CJK_FONT=1，則啟用文泉驿正黑支持中文（無真粗體，可接受）。
REG_FONT, BOLD_FONT = "Helvetica", "Helvetica-Bold"
if os.environ.get("USE_CJK_FONT", "0") == "1":
    try:
        pdfmetrics.registerFont(TTFont("WQY", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", subfontIndex=0))
        REG_FONT, BOLD_FONT = "WQY", "WQY"
    except Exception:
        REG_FONT, BOLD_FONT = "Helvetica", "Helvetica-Bold"

# ================= 發票防重登記簿（Render /tmp）=================
LEDGER_FILE = "/tmp/invoice_ledger.json"

def _load_ledger():
    if not os.path.exists(LEDGER_FILE):
        return {}
    with open(LEDGER_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_ledger(ledger):
    with open(LEDGER_FILE, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, ensure_ascii=False)

def check_invoice_status(invoice_no: str) -> str:
    """工具：檢查發票是否已開立（防重複）。"""
    ledger = _load_ledger()
    if invoice_no in ledger:
        info = ledger[invoice_no]
        return f"⚠️ 警告：發票 {invoice_no} 已於 {info['date']} 開立給 {info['client']}，金額 RM {info['amount']}。請勿重複開立。"
    return f"✅ 確認：發票 {invoice_no} 尚未開立，可以繼續生成。"

def register_invoice(invoice_no: str, client_name: str, amount: float) -> str:
    """工具：將新發票寫入登記簿，防止未來重複。"""
    ledger = _load_ledger()
    ledger[invoice_no] = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "client": client_name,
        "amount": float(amount)
    }
    _save_ledger(ledger)
    return f"✅ 已登記發票 {invoice_no}（客戶: {client_name}，金額: RM {amount}）到系統帳冊。"


# ================= 企業規範（嚴格對齊 INV-10051）=================
COMPANY_KNOWLEDGE = """
【企業官方資訊】
- 公司名稱：CIVEXA CONSTRUCTION
- 資質與註冊：CIDB Registered Contractor | Company Reg. No: 003666333-A
- 公司地址：48, Jalan Nuri 7/5, Kota Damansara, 47810 Petaling Jaya, Selangor
- 聯絡方式：Email: civexa2@gmail.com | Tel: 012-208 5595
- 收款銀行：Maybank | Account Name: CIVEXA CONSTRUCTION | Account No: 5142-0890-0031
- 默認貨幣：RM (馬來西亞林吉特)

【發票排版規範（對齊 INV-10051）】
- 發票編號：INV-10052 起自動遞增
- 日期格式：序數+完整月份，例 4th November 2026（禁縮寫/前導零）
- 期限：發票日起 7 天
- 折扣標籤：必須 "Loyal Customer Discount"（禁 Special Discount）
- 價格表上方必須有 "Note:" 特別優惠說明行
- 頁面：單張 A4 不超過 2 頁
"""

def _format_date_ordinal(d: datetime) -> str:
    day = d.day
    if day % 100 in (11, 12, 13):
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} {d.strftime('%B')} {d.year}"


def create_official_pdf(client_name: str, client_attn: str, invoice_no: str,
                        subject: str, items_json: str, note_text: str,
                        original_price: float, discount_amount: float) -> str:
    """工具：依 INV-10051 範本生成 A4 PDF（無簽名，乾淨版）。返回本地路徑。"""
    try:
        items = json.loads(items_json) if isinstance(items_json, str) else items_json
        if not isinstance(items, list):
            items = [items]
    except Exception:
        items = [{"title": "Works Completed", "details": [str(items_json)]}]

    safe_client = "".join(c for c in client_name if c.isalnum() or c in (" ", "_")).rstrip()
    filename = f"/tmp/{invoice_no}_{safe_client.replace(' ', '_')}.pdf"

    doc = SimpleDocTemplate(filename, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Normal"], fontName=REG_FONT, fontSize=16, alignment=1, textColor=colors.HexColor("#1A365D"))
    normal_style = ParagraphStyle("NormalCN", parent=styles["Normal"], fontName=REG_FONT, fontSize=9, leading=13)
    bold_style = ParagraphStyle("BoldCN", parent=normal_style, fontName=BOLD_FONT, fontSize=9, textColor=colors.HexColor("#1A365D"))

    inv_date = datetime.now()
    due_date = inv_date + timedelta(days=7)
    inv_str, due_str = _format_date_ordinal(inv_date), _format_date_ordinal(due_date)

    # 1 標頭
    story.append(Paragraph("<b>CIVEXA CONSTRUCTION</b>", title_style))
    story.append(Paragraph(
        "<font size=8 color='#555555'>CIDB Registered Contractor | Company Reg. No: 003666333-A<br/>"
        "48, Jalan Nuri 7/5, Kota Damansara, 47810 Petaling Jaya, Selangor<br/>"
        "Email: civexa2@gmail.com | Tel: 012-208 5595</font>", normal_style))
    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>INVOICE</b>", ParagraphStyle("InvTitle", parent=title_style, fontSize=14, textColor=colors.HexColor("#2B6CB0"))))
    story.append(Spacer(1, 10))

    # 2 客戶/發票資訊
    info = [[
        Paragraph(f"<b>BILL TO:</b><br/><b>{client_name}</b><br/>Attn: {client_attn}", normal_style),
        Paragraph(f"<b>INVOICE INFORMATION:</b><br/>Invoice Number: <b>{invoice_no}</b><br/>Invoice Date: {inv_str}<br/>Due Date: {due_str}<br/>Payment: Bank Transfer / Cash / Cheque", normal_style)
    ]]
    t = Table(info, colWidths=[270, 270])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#F7FAFC")),
        ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E0")),
        ("TOPPADDING", (0,0), (-1,-1), 8), ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING", (0,0), (-1,-1), 8), ("RIGHTPADDING", (0,0), (-1,-1), 8),
    ]))
    story.append(t); story.append(Spacer(1, 10))

    # 3 主旨
    story.append(Paragraph(f"<b>SUBJECT:</b> {subject}", bold_style))
    story.append(Spacer(1, 8))

    # 4 明細
    rows = [[Paragraph("<b>NO.</b>", bold_style), Paragraph("<b>DESCRIPTION OF WORKS COMPLETED</b>", bold_style)]]
    for idx, it in enumerate(items, 1):
        html = f"<b>{it.get('title','')}</b><br/>" + "<br/>".join(f"- {ln}" for ln in it.get("details", []))
        rows.append([Paragraph(str(idx), normal_style), Paragraph(html, normal_style)])
    wt = Table(rows, colWidths=[40, 500], repeatRows=1)
    wt.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#EDF2F7")),
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E0")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(wt); story.append(Spacer(1, 10))

    # 5 Note
    if note_text:
        story.append(Paragraph(f"<b>Note:</b> {note_text}", normal_style))
        story.append(Spacer(1, 6))

    # 6 價格
    total = original_price - discount_amount
    calc = [
        [Paragraph("Original Price:", normal_style), Paragraph(f"RM {original_price:.2f}", normal_style)],
        [Paragraph("Loyal Customer Discount:", normal_style), Paragraph(f"- RM {discount_amount:.2f}", normal_style)],
        [Paragraph("SST (0%):", normal_style), Paragraph("RM 0.00", normal_style)],
        [Paragraph("<b>TOTAL AMOUNT DUE:</b>", bold_style), Paragraph(f"<b>RM {total:.2f}</b>", bold_style)],
    ]
    ct = Table(calc, colWidths=[380, 160])
    ct.setStyle(TableStyle([
        ("LINEABOVE", (0,0), (-1,0), 0.5, colors.HexColor("#CBD5E0")),
        ("LINEBELOW", (0,-1), (-1,-1), 1, colors.HexColor("#1A365D")),
        ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    story.append(ct); story.append(Spacer(1, 10))

    # 7 付款/條款
    story.append(Paragraph(
        f"<b>PAYMENT INSTRUCTIONS</b><br/>Due: {due_str} (Within 7 days)<br/>"
        f"Method: Bank Transfer / Cash / Cheque<br/>Bank: Maybank | Account Name: CIVEXA CONSTRUCTION<br/>"
        f"Account No: 5142-0890-0031 | Reference: {invoice_no}<br/>State reference clearly to avoid processing delays.", normal_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "<b>TERMS &amp; CONDITIONS:</b> Payment due within 7 days from invoice date - Late payment may result in work suspension &amp; additional charges - All works completed as per agreed specifications - Special loyal customer rate applied - Quality workmanship guaranteed",
        ParagraphStyle("Terms", parent=normal_style, fontSize=7, leading=9, textColor=colors.HexColor("#718096"))))
    story.append(Spacer(1, 15))

    # 8 頁腳（【已刪除簽名區塊】，直接發顧客無需手簽）
    story.append(Paragraph(
        "<font size=7 color='#718096'>Thank You For Your Business!  |  For any queries regarding this invoice, please contact us.  |  CIVEXA CONSTRUCTION  |  CIDB Registered Contractor</font>",
        ParagraphStyle("Footer", parent=normal_style, alignment=1)))

    doc.build(story)
    return filename


# ================= 多 Agent 總指揮（含防重準則）=================
def run_multi_agent_system(user_message: str):
    system_prompt = f"""你是企業級 AI 總管（Manager Agent）。

【核心安全準則 - 防重複開票】
1. 老闆要求開立新發票（如 INV-10052）時，**必須先調用 `check_invoice_status`** 查冊。
2. 若返回「⚠️ 警告：已開立」→ **立即停止**，回覆：「⚠️ 老闆，{user_message[:0]}該發票已開立過，請確認是要補發舊 PDF 還是作廢重開？」
3. 僅當返回「✅ 確認：尚未開立」才可調用 `create_official_pdf`。
4. PDF 生成成功後，**必須立即調用 `register_invoice`** 寫入登記簿（amount 傳 TOTAL AMOUNT DUE）。

【工具參數】
- create_official_pdf 的 items_json 傳 JSON 字符串；note_text 傳價格備註文案。
- 明細過多會超 2 頁時，主動精簡描述。

公司規範與範本：
{COMPANY_KNOWLEDGE}
"""
    tools = [check_invoice_status, register_invoice, create_official_pdf]
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=user_message,
        config=types.GenerateContentConfig(system_instruction=system_prompt, tools=tools, temperature=0.2),
    )

    generated_pdf_path = None
    history = getattr(response, "automatic_function_calling_history", None)
    if history:
        for step in history:
            for part in getattr(step, "parts", []):
                fr = getattr(part, "function_response", None)
                if fr and fr.name == "create_official_pdf":
                    data = fr.response
                    generated_pdf_path = data.get("result") if isinstance(data, dict) else str(data)
                    break
            if generated_pdf_path:
                break
    return response.text, generated_pdf_path
