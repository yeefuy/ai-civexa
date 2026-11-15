import os
import json
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# 初始化 Gemini 客戶端
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# ================= 發票防重登記簿 (存儲在 Render 的 /tmp 目錄) =================
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
    """
    工具：檢查發票是否已開立。
    如果已存在，返回警告；如果不存在，返回允許。
    """
    ledger = _load_ledger()
    if invoice_no in ledger:
        info = ledger[invoice_no]
        return f"⚠️ 警告：發票 {invoice_no} 已經於 {info['date']} 開立給 {info['client']}，金額 RM {info['amount']}。請勿重複開立。"
    return f"✅ 確認：發票 {invoice_no} 尚未開立，可以繼續生成。"

def register_invoice(invoice_no: str, client_name: str, amount: float) -> str:
    """
    工具：在登記簿中記錄新發票，防止未來重複。
    """
    ledger = _load_ledger()
    ledger[invoice_no] = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "client": client_name,
        "amount": float(amount)
    }
    _save_ledger(ledger)
    return f"✅ 已成功登記發票 {invoice_no} (客戶: {client_name}, 金額: RM {amount}) 到系統帳冊。"


# ================= 企業官方資料與最新發票範本規範 =================
COMPANY_KNOWLEDGE = """
【企業官方資訊】
- 公司名稱：CIVEXA CONSTRUCTION
- 資質與註冊：CIDB Registered Contractor | Company Reg. No: 003666333-A
- 公司地址：48, Jalan Nuri 7/5, Kota Damansara, 47810 Petaling Jaya, Selangor
- 聯絡方式：Email: civexa2@gmail.com | Tel: 012-208 5595
- 收款銀行與賬號：Maybank | Account Name: CIVEXA CONSTRUCTION | Account No: 5142-0890-0031
- 默認貨幣：RM (馬來西亞林吉特)

【最新發票排版與編號規範 (嚴格對齊 INV-10051)】
- 發票編號格式：INV-10052（後續自動遞增）
- 日期格式：必須使用"序數+完整月份"，例如 4th November 2026（不要縮寫、不要前導零）
- 單據期限：發票日期起算 7 天內 (Due Date)
- 折扣標籤：必須使用 "Loyal Customer Discount"（絕對不能用 Special Discount）
- 價格備註：在價格表上方必須有一行 "Note:" 說明特別優惠價與涵蓋範圍
- 頁面限制：嚴格控制版面，確保單張 A4 Invoice 絕不超過 2 頁
"""

def _format_date_ordinal(d: datetime) -> str:
    """生成 INV-10051 同款日期格式，如 '4th November 2026'。"""
    day = d.day
    if day % 100 in (11, 12, 13):
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} {d.strftime('%B')} {d.year}"

def create_official_pdf(client_name: str, client_attn: str, invoice_no: str,
                        subject: str, items_json: str, note_text: str,
                        original_price: float, discount_amount: float) -> str:
    """
    工具：完全依照 INV-10051 範本生成專業 A4 PDF 發票/報價單（無簽名線，乾淨版）。
    返回生成的 PDF 本地路徑。
    """
    # 【穩健性修復】兼容 AI 傳成 list 或字符串，且解析失敗不崩服務
    try:
        items = json.loads(items_json) if isinstance(items_json, str) else items_json
        if not isinstance(items, list):
            items = [items]
    except Exception:
        items = [{"title": "Works Completed", "details": [str(items_json)]}]

    safe_client_name = "".join(c for c in client_name if c.isalnum() or c in (" ", "_")).rstrip()
    filename = f"/tmp/{invoice_no}_{safe_client_name.replace(' ', '_')}.pdf"

    doc = SimpleDocTemplate(filename, pagesize=A4,
                            rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []

    font_name = "Helvetica"
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Normal"], fontName=font_name,
                                 fontSize=16, alignment=1, textColor=colors.HexColor("#1A365D"))
    normal_style = ParagraphStyle("NormalCN", parent=styles["Normal"], fontName=font_name,
                                  fontSize=9, leading=13)
    bold_style = ParagraphStyle("BoldCN", parent=normal_style, fontName="Helvetica-Bold",
                                fontSize=9, textColor=colors.HexColor("#1A365D"))

    inv_date = datetime.now()
    due_date = inv_date + timedelta(days=7)
    inv_date_str = _format_date_ordinal(inv_date)
    due_date_str = _format_date_ordinal(due_date)

    # 1. 頂部公司標頭
    story.append(Paragraph("<b>CIVEXA CONSTRUCTION</b>", title_style))
    story.append(Paragraph(
        "<font size=8 color='#555555'>CIDB Registered Contractor | Company Reg. No: 003666333-A<br/>"
        "48, Jalan Nuri 7/5, Kota Damansara, 47810 Petaling Jaya, Selangor<br/>"
        "Email: civexa2@gmail.com | Tel: 012-208 5595</font>", normal_style))
    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>INVOICE</b>",
                           ParagraphStyle("InvTitle", parent=title_style, fontSize=14,
                                          textColor=colors.HexColor("#2B6CB0"))))
    story.append(Spacer(1, 10))

    # 2. 客戶與發票資訊區塊
    info_data = [[
        Paragraph(f"<b>BILL TO:</b><br/><b>{client_name}</b><br/>Attn: {client_attn}", normal_style),
        Paragraph(f"<b>INVOICE INFORMATION:</b><br/>Invoice Number: <b>{invoice_no}</b><br/>"
                  f"Invoice Date: {inv_date_str}<br/>Due Date: {due_date_str}<br/>"
                  f"Payment: Bank Transfer / Cash / Cheque", normal_style)
    ]]
    info_table = Table(info_data, colWidths=[270, 270])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 10))

    # 3. 主旨
    story.append(Paragraph(f"<b>SUBJECT:</b> {subject}", bold_style))
    story.append(Spacer(1, 8))

    # 4. 施工明細表格
    table_data = [[Paragraph("<b>NO.</b>", bold_style),
                   Paragraph("<b>DESCRIPTION OF WORKS COMPLETED</b>", bold_style)]]
    for idx, item in enumerate(items, 1):
        desc_html = f"<b>{item.get('title', '')}</b><br/>" + "<br/>".join(
            [f"- {line}" for line in item.get("details", [])])
        table_data.append([Paragraph(str(idx), normal_style),
                           Paragraph(desc_html, normal_style)])

    work_table = Table(table_data, colWidths=[40, 500], repeatRows=1)
    work_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(work_table)
    story.append(Spacer(1, 10))

    # 5. Note 行（獨立段落）
    if note_text:
        story.append(Paragraph(f"<b>Note:</b> {note_text}", normal_style))
        story.append(Spacer(1, 6))

    # 6. 價格與折扣區塊
    total_amount = original_price - discount_amount
    calc_data = [
        [Paragraph("Original Price:", normal_style), Paragraph(f"RM {original_price:.2f}", normal_style)],
        [Paragraph("Loyal Customer Discount:", normal_style), Paragraph(f"- RM {discount_amount:.2f}", normal_style)],
        [Paragraph("SST (0%):", normal_style), Paragraph("RM 0.00", normal_style)],
        [Paragraph("<b>TOTAL AMOUNT DUE:</b>", bold_style), Paragraph(f"<b>RM {total_amount:.2f}</b>", bold_style)],
    ]
    calc_table = Table(calc_data, colWidths=[380, 160])
    calc_table.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.5, colors.HexColor("#CBD5E0")),
        ("LINEBELOW", (0, -1), (-1, -1), 1, colors.HexColor("#1A365D")),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(calc_table)
    story.append(Spacer(1, 10))

    # 7. 付款指示與條款
    pay_text = (f"<b>PAYMENT INSTRUCTIONS</b><br/>"
                f"Due: {due_date_str} (Within 7 days)<br/>"
                f"Method: Bank Transfer / Cash / Cheque<br/>"
                f"Bank: Maybank | Account Name: CIVEXA CONSTRUCTION<br/>"
                f"Account No: 5142-0890-0031 | Reference: {invoice_no}<br/>"
                f"State reference clearly to avoid processing delays.")
    terms_text = ("<b>TERMS &amp; CONDITIONS:</b> Payment due within 7 days from invoice date - "
                  "Late payment may result in work suspension &amp; additional charges - "
                  "All works completed as per agreed specifications - "
                  "Special loyal customer rate applied - Quality workmanship guaranteed")
    story.append(Paragraph(pay_text, normal_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph(terms_text,
                           ParagraphStyle("Terms", parent=normal_style, fontSize=7,
                                          leading=9, textColor=colors.HexColor("#718096"))))
    story.append(Spacer(1, 15))

    # 8. 底部頁腳三欄（已移除簽名線，保持乾淨專業）
    footer_text = ("<font size=7 color='#718096'>Thank You For Your Business!  |  "
                   "For any queries regarding this invoice, please contact us.  |  "
                   "CIVEXA CONSTRUCTION  |  CIDB Registered Contractor</font>")
    story.append(Paragraph(footer_text,
                           ParagraphStyle("Footer", parent=normal_style, alignment=1)))

    doc.build(story)
    return filename


# ================= 多 Agent 總指揮調度系統 =================
def run_multi_agent_system(user_message: str):
    system_prompt = f"""你是企業級 AI 總管（Manager Agent）。

    【核心安全準則 - 防重複開票】
    1. 當老闆要求開立新發票（如 INV-10052）時，**必須先調用 `check_invoice_status` 工具**檢查該號碼是否已存在。
    2. 如果工具返回「⚠️ 警告：已開立」，你必須立刻停止生成 PDF，並回覆老闆：「⚠️ 老闆，該發票已經開立過了，請問是要補發舊的，還是要作廢重開？」
    3. 只有在工具返回「✅ 確認：尚未開立」時，你才能調用 `create_official_pdf` 生成 PDF。
    4. 生成 PDF 成功後，**必須立刻調用 `register_invoice` 工具**將此發票寫入登記簿。

    以下是公司規範與發票範本：
    {COMPANY_KNOWLEDGE}
    """

    # 將三個工具一起傳給 AI，SDK 會自動處理調用順序
    tools = [check_invoice_status, register_invoice, create_official_pdf]

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=tools,
            temperature=0.2,
        ),
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
