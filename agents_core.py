import os
import json
from datetime import datetime
from google import genai
from google.genai import types
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFFont

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# ================= 企業知識庫 (可隨時在 GitHub 網頁修改) =================
COMPANY_KNOWLEDGE = """
【企業標準規範】
- 默認貨幣：RM (馬來西亞林吉特)
- 付款條款：開工前支付 50% 定金，完工驗收後支付 50% 尾款。
- 標準工料參考單價：
  1. 拆除舊地磚（含清運）：RM 3.50 / sqft
  2. 鋪設 60x60cm 拋光地磚（包工包料）：RM 9.50 / sqft
  3. 實木門安裝（含門框與五金）：RM 350.00 / 套
  4. 浴室/陽台防水處理：RM 450.00 / 間
  5. 混凝土牆體高壓注漿補漏：RM 800.00 / 處
"""

# ================= Agent 可自主調用的工具箱 =================
def create_official_pdf(client_name: str, doc_type: str, items_json: str) -> str:
    """
    工具：生成正式的工程報價單或發票 PDF 文件。
    """
    items = json.loads(items_json)
    filename = f"/tmp/{doc_type}_{client_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []

    font_path = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFFont('WenQuanYi', font_path))
        font_name = 'WenQuanYi'
    else:
        font_name = 'Helvetica'

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Normal'], fontName=font_name, fontSize=18, alignment=1, textColor=colors.HexColor("#1A365D"))
    normal_style = ParagraphStyle('NormalCN', parent=styles['Normal'], fontName=font_name, fontSize=10, leading=14)
    bold_style = ParagraphStyle('BoldCN', parent=normal_style, fontName=font_name, fontSize=10, textColor=colors.HexColor("#1A365D"))

    title_text = "工程報價單 / QUOTATION" if doc_type.lower() == "quotation" else "正式發票 / INVOICE"
    story.append(Paragraph(f"<b>{title_text}</b>", title_style))
    story.append(Spacer(1, 15))

    info_data = [
        [Paragraph(f"<b>客戶名稱：</b>{client_name}", normal_style), Paragraph(f"<b>日期：</b>{datetime.now().strftime('%Y-%m-%d')}", normal_style)],
        [Paragraph(f"<b>單據類型：</b>{doc_type}", normal_style), Paragraph(f"<b>結算貨幣：</b>RM (馬幣)", normal_style)]
    ]
    story.append(Table(info_data, colWidths=[280, 240]))
    story.append(Spacer(1, 15))

    table_data = [[
        Paragraph("<b>項目明細與規格</b>", bold_style),
        Paragraph("<b>數量</b>", bold_style),
        Paragraph("<b>單位</b>", bold_style),
        Paragraph("<b>單價(RM)</b>", bold_style),
        Paragraph("<b>小計(RM)</b>", bold_style)]
    ]

    total_amount = 0.0
    for item in items:
        sub = float(item.get("subtotal", 0))
        total_amount += sub
        table_data.append([
            Paragraph(str(item.get("name", "")), normal_style),
            Paragraph(str(item.get("qty", "")), normal_style),
            Paragraph(str(item.get("unit", "")), normal_style),
            Paragraph(f"{float(item.get('price', 0)):.2f}", normal_style),
            Paragraph(f"{sub:.2f}", normal_style)
        ])

    t = Table(table_data, colWidths=[210, 60, 60, 95, 95])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 15))

    total_table = Table([["", "", "", Paragraph("<b>總計金額：</b>", bold_style), Paragraph(f"<b>RM {total_amount:.2f}</b>", bold_style)]], colWidths=[210, 60, 60, 95, 95])
    story.append(total_table)

    doc.build(story)
    return filename

# ================= 多 Agent 總指揮調度系統 =================
def run_multi_agent_system(user_message: str):
    system_prompt = f"""你是企業級 AI 總管（Manager Agent），旗下統籌多個專業分身：
1. 【資深工程估價師 Agent】：精通馬來西亞裝修市場，嚴格依據知識庫計算成本與報價。
2. 【財務單據專員 Agent】：當用戶需要正式單據時，負責調用 `create_official_pdf` 工具生成 PDF。
3. 【全能商務助理 Agent】：負責中英文商務溝通與日常決策。

以下是公司的核心知識庫：
{COMPANY_KNOWLEDGE}

【工作準則】
- 自主判斷用戶意圖：如果只是諮詢、算草稿、寫郵件，直接給出專業清晰的回覆。
- 如果用戶明確要求「開報價單」、「生成發票」或「出 PDF」，請先算好精準明細，然後**主動調用 `create_official_pdf` 工具**生成檔案。
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[create_official_pdf],
            temperature=0.3,
        )
    )

    generated_pdf_path = None
    if response.automatic_function_calling_history:
        for step in response.automatic_function_calling_history:
            for part in step.parts:
                if part.function_response and part.function_response.name == "create_official_pdf":
                    generated_pdf_path = part.function_response.response.get("result")

    return response.text, generated_pdf_path
