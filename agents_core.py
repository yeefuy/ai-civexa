import os
import json
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# 初始化 Gemini 客戶端 (從環境變數讀取 API Key，Render 中需在 Settings -> Environment Variables 設定)
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# ================= 企業官方資料與最新發票範本規範 =================
COMPANY_KNOWLEDGE = """
【企業官方資訊】
- 公司名稱：CIVEXA CONSTRUCTION
- 資質與註冊：CIDB Registered Contractor | Company Reg. No: 003666333-A
- 公司地址：48, Jalan Nuri 7/5, Kota Damansara, 47810 Petaling Jaya, Selangor
- 聯絡方式：Email: civexa2@gmail.com | Tel: 012-208 5595
- 收款銀行與賬號：
  * 銀行名稱：Maybank
  * 賬戶名稱：CIVEXA CONSTRUCTION
  * 賬戶號碼：5142-0890-0031
- 默認貨幣：RM (馬來西亞林吉特)

【最新發票排版與編號規範 (參考 INV-10051 格式)】
- 發票編號格式：INV-10052（後續自動遞增，如 INV-10053 等）
- 單據期限：發票日期起算 7 天內 (Due Date)
- 價格備註規則：如遇特別優惠，需明確列出 Original Price（原價）、Loyal Customer Discount（忠實顧客特別優惠折扣）、SST (0%)、以及 TOTAL AMOUNT DUE（應付總額）。
- 頁面限制：嚴格控制版面與行距，確保單張/新 A4 Invoice 絕不超過 2 頁。
"""

def create_official_pdf(client_name: str, client_attn: str, invoice_no: str, subject: str, items_json: str, discount_note: str, original_price: float, discount_amount: float) -> str:
    """
    工具：完全依照 INV-10051 最新範本生成專業 A4 PDF 發票/報價單。
    返回生成的 PDF 檔案本地路徑。
    """
    items = json.loads(items_json)
    # 使用 Render 的 /tmp 目錄，這是臨時可寫目錄
    safe_client_name = "".join(c for c in client_name if c.isalnum() or c in (' ', '_')).rstrip()
    filename = f"/tmp/{invoice_no}_{safe_client_name.replace(' ', '_')}.pdf"
    
    # A4 頁面與邊距設定 (確保不超過 2 頁)
    doc = SimpleDocTemplate(filename, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []

    # 使用內建標準 Helvetica 字體，百分之百穩定兼容，絕不報錯
    font_name = 'Helvetica'

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Normal'], fontName=font_name, fontSize=16, alignment=1, textColor=colors.HexColor("#1A365D"))
    normal_style = ParagraphStyle('NormalCN', parent=styles['Normal'], fontName=font_name, fontSize=9, leading=13)
    # 【已修復】移除了重複的 fontName 參數，只保留 Helvetica-Bold
    bold_style = ParagraphStyle('BoldCN', parent=normal_style, fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor("#1A365D"))

    # 1. 頂部公司標頭
    story.append(Paragraph("<b>CIVEXA CONSTRUCTION</b>", title_style))
    story.append(Paragraph("<font size=8 color='#555555'>CIDB Registered Contractor | Company Reg. No: 003666333-A<br/>48, Jalan Nuri 7/5, Kota Damansara, 47810 Petaling Jaya, Selangor<br/>Email: civexa2@gmail.com | Tel: 012-208 5595</font>", normal_style))
    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>INVOICE</b>", ParagraphStyle('InvTitle', parent=title_style, fontSize=14, textColor=colors.HexColor("#2B6CB0"))))
    story.append(Spacer(1, 10))

    # 2. 客戶與發票資訊區塊
    info_data = [
        [
            Paragraph(f"<b>BILL TO:</b><br/><b>{client_name}</b><br/>Attn: {client_attn}", normal_style),
            Paragraph(f"<b>INVOICE INFORMATION:</b><br/>Invoice Number: <b>{invoice_no}</b><br/>Invoice Date: {datetime.now().strftime('%d %b %Y')}<br/>Due Date: {(datetime.now() + timedelta(days=7)).strftime('%d %b %Y')}<br/>Payment: Bank Transfer / Cash / Cheque", normal_style)
        ]
    ]
    info_table = Table(info_data, colWidths=[270, 270])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F7FAFC")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E0")),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 10))

    # 3. 主旨 (SUBJECT)
    story.append(Paragraph(f"<b>SUBJECT:</b> {subject}", bold_style))
    story.append(Spacer(1, 8))

    # 4. 施工明細表格
    table_data = [[
        Paragraph("<b>NO.</b>", bold_style),
        Paragraph("<b>DESCRIPTION OF WORKS COMPLETED</b>", bold_style)
    ]]

    for idx, item in enumerate(items, 1):
        desc_html = f"<b>{item.get('title', '')}</b><br/>" + "<br/>".join([f"- {line}" for line in item.get('details', [])])
        table_data.append([
            Paragraph(str(idx), normal_style),
            Paragraph(desc_html, normal_style)
        ])

    work_table = Table(table_data, colWidths=[40, 500])
    work_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#EDF2F7")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E0")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(work_table)
    story.append(Spacer(1, 10))

    # 5. 價格與折扣備註
    total_amount = original_price - discount_amount
    calc_data = [
        [Paragraph(f"<b>{discount_note}</b>", normal_style), ""],
        [Paragraph("Original Price:", normal_style), Paragraph(f"RM {original_price:.2f}", normal_style)],
        [Paragraph("Special Discount:", normal_style), Paragraph(f"- RM {discount_amount:.2f}", normal_style)],
        [Paragraph("SST (0%):", normal_style), Paragraph("RM 0.00", normal_style)],
        [Paragraph("<b>TOTAL AMOUNT DUE:</b>", bold_style), Paragraph(f"<b>RM {total_amount:.2f}</b>", bold_style)]
    ]
    calc_table = Table(calc_data, colWidths=[380, 160])
    calc_table.setStyle(TableStyle([
        ('LINEABOVE', (0,1), (-1,1), 0.5, colors.HexColor("#CBD5E0")),
        ('LINEBELOW', (0,-1), (-1,-1), 1, colors.HexColor("#1A365D")),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(calc_table)
    story.append(Spacer(1, 10))

    # 6. 付款指示與條款
    pay_text = f"""<b>PAYMENT INSTRUCTIONS</b><br/>
Due: {(datetime.now() + timedelta(days=7)).strftime('%d %b %Y')} (Within 7 days)<br/>
Method: Bank Transfer / Cash / Cheque<br/>
Bank: Maybank | Account Name: CIVEXA CONSTRUCTION<br/>
Account No: 5142-0890-0031 | Reference: {invoice_no}<br/>
State reference clearly to avoid processing delays.
"""
    terms_text = "<b>TERMS & CONDITIONS:</b> Payment due within 7 days from invoice date - Late payment may result in work suspension & additional charges - All works completed as per agreed specifications - Special loyal customer rate applied - Quality workmanship guaranteed"
    
    story.append(Paragraph(pay_text, normal_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph(terms_text, ParagraphStyle('Terms', parent=normal_style, fontSize=7, leading=9, textColor=colors.HexColor("#718096"))))
    story.append(Spacer(1, 10))

    # 7. 簽名與結尾
    sig_data = [[
        Paragraph("<b>AUTHORIZED SIGNATURE:</b><br/><b>CIVEXA CONSTRUCTION</b><br/><br/><br/>___________________________", normal_style),
        Paragraph("<br/><br/><br/><b>Thank You For Your Business!</b>", ParagraphStyle('Thanks', parent=normal_style, alignment=2))
    ]]
    sig_table = Table(sig_data, colWidths=[300, 240])
    story.append(sig_table)

    # 生成 PDF
    doc.build(story)
    return filename


# ================= 多 Agent 總指揮調度系統 =================
def run_multi_agent_system(user_message: str):
    system_prompt = f"""你是企業級 AI 總管（Manager Agent），旗下統籌多個專業分身：
1. 【資深工程估價師 Agent】：精通馬來西亞裝修市場，嚴格依據公司規範計算價格與特別優惠。
2. 【財務單據專員 Agent】：精通 INV-10051 發票格式，負責調用 `create_official_pdf` 工具生成精準符合排版規範的 A4 PDF 發票（嚴格控制在 2 頁內）。

以下是公司的核心規範與最新發票範本格式：
{COMPANY_KNOWLEDGE}

【工作準則】
- 當老闆要求開立新發票（例如 INV-10052）時，請自動解析老闆提供的**新顧客名稱、聯繫人、工程主旨、明細內容、原價與特別優惠折扣金額**。
- **必須主動調用 `create_official_pdf` 工具**生成正式 PDF 發票，並在回覆中確認發票編號與總金額。
- 如果用戶只是普通問候，請以專業、簡潔的管家語氣回覆。
"""

    # 新版 google-genai SDK 支援直接傳入 Python function，會自動處理調用與結果回填
    response = client.models.generate_content(
        model="gemini-3.6-flash", # 建議使用 2.0-flash，速度更快且 function calling 更穩定
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[create_official_pdf],
            temperature=0.2,
        )
    )

    # 提取自動函數調用歷史中的 PDF 路徑
    generated_pdf_path = None
    if hasattr(response, 'automatic_function_calling_history') and response.automatic_function_calling_history:
        for step in response.automatic_function_calling_history:
            for part in step.parts:
                if hasattr(part, 'function_response') and part.function_response and part.function_response.name == "create_official_pdf":
                    resp_data = part.function_response.response
                    # 兼容處理：response 可能是 dict 或直接是 string
                    if isinstance(resp_data, dict):
                        generated_pdf_path = resp_data.get("result")
                    else:
                        generated_pdf_path = str(resp_data)
                    break
            if generated_pdf_path:
                break

    return response.text, generated_pdf_path
