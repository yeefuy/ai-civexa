import os
import json
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, KeepTogether)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# ================= 企业官方资料与最新发票范本规范 (严格对齐 INV-10051) =================
COMPANY_KNOWLEDGE = """
【企业官方资讯】
- 公司名称：CIVEXA CONSTRUCTION
- 资质与注册：CIDB Registered Contractor | Company Reg. No: 003666333-A
- 公司地址：48, Jalan Nuri 7/5, Kota Damansara, 47810 Petaling Jaya, Selangor
- 联系方式：Email: civexa2@gmail.com | Tel: 012-208 5595
- 收款银行与账号：Maybank | Account Name: CIVEXA CONSTRUCTION | Account No: 5142-0890-0031
- 默认货币：RM (马来西亚林吉特)

【最新发票排版与编号规范 (参考 INV-10051 格式)】
- 发票编号格式：INV-10052（后续自动递增，如 INV-10053 等）
- 日期格式：必须使用"序数+完整月份"，例如 4th November 2026、11th November 2026（不要缩写、不要前导零）
- 单据期限：发票日期起算 7 天内 (Due Date)
- 折扣标签：必须使用 "Loyal Customer Discount"（不是 Special Discount）
- 价格备注：在价格表上方必须有一行 "Note:" 说明特别优惠价与涵盖范围
- 页面限制：严格控制版面，确保单张 A4 Invoice 绝不超过 2 页
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
    工具：完全依照 INV-10051 范本生成专业 A4 PDF 发票/报价单。
    参数 items_json 必须是 JSON 字符串，格式：
      [{"title": "20mm Copper Water Pipe Leakage Repair Works",
        "details": ["Repair of damaged and leaking 20mm copper water pipe, including:",
                    "Cutting and removal of the damaged section",
                    "Reconnection and replacement using old copper pipe supplied by customer",
                    "Supply and installation of fitting ring"]}]
    返回生成的 PDF 本地路径。
    """
    # 【稳健性修复】兼容 AI 传成 list 或字符串，且解析失败不崩服务
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
    # 【语法修复】fontName 只保留一次，使用 Helvetica-Bold
    bold_style = ParagraphStyle("BoldCN", parent=normal_style, fontName="Helvetica-Bold",
                                fontSize=9, textColor=colors.HexColor("#1A365D"))

    inv_date = datetime.now()
    due_date = inv_date + timedelta(days=7)
    inv_date_str = _format_date_ordinal(inv_date)
    due_date_str = _format_date_ordinal(due_date)

    # 1. 顶部公司标头
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

    # 2. 客户与发票资讯区块（日期使用序数格式）
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

    # 4. 施工明细表格
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

    # 5. Note 行（独立段落，对齐 INV-10051 位置）
    if note_text:
        story.append(Paragraph(f"<b>Note:</b> {note_text}", normal_style))
        story.append(Spacer(1, 6))

    # 6. 价格与折扣区块（标签改为 Loyal Customer Discount）
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

    # 7. 付款指示与条款
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
    story.append(Spacer(1, 10))

    # 8. 签名区块（保留签名线占位，与 INV-10051 一致）
    sig_data = [[
        Paragraph("<b>AUTHORIZED SIGNATURE:</b><br/><b>CIVEXA CONSTRUCTION</b><br/><br/><br/>"
                  "___________________________", normal_style),
        Paragraph("<br/><br/><br/><b>Thank You For Your Business!</b>",
                  ParagraphStyle("Thanks", parent=normal_style, alignment=2))
    ]]
    sig_table = Table(sig_data, colWidths=[300, 240])
    story.append(sig_table)
    story.append(Spacer(1, 8))

    # 9. 底部页脚三栏（对齐 INV-10051）
    footer_text = ("<font size=7 color='#718096'>Thank You For Your Business!  |  "
                   "For any queries regarding this invoice, please contact us.  |  "
                   "CIVEXA CONSTRUCTION  |  CIDB Registered Contractor</font>")
    story.append(Paragraph(footer_text,
                           ParagraphStyle("Footer", parent=normal_style, alignment=1)))

    doc.build(story)
    return filename


# ================= 多 Agent 总指挥调度系统 =================
def run_multi_agent_system(user_message: str):
    system_prompt = f"""你是企业级 AI 总管（Manager Agent），旗下统筹多个专业分身：
1. 【资深工程估价师 Agent】：精通马来西亚装修市场，严格依据公司规范计算价格与特别优惠。
2. 【财务单据专员 Agent】：精通 INV-10051 发票格式，负责调用 `create_official_pdf` 工具生成 A4 PDF 发票。

以下是公司的核心规范与最新发票范本格式：
{COMPANY_KNOWLEDGE}

【工作准则】
- 当老板要求开立/更新新发票（例如 INV-10052）时，请自动解析：新顾客名称、联系人、工程主旨、明细内容、Note 备注文案、原价与 Loyal Customer Discount 折扣金额。
- 必须调用 `create_official_pdf` 工具，items_json 参数请传 JSON 字符串，note_text 请传价格备注文案。
- 若明细过多可能超过 2 页，请主动精简描述文字，确保不超过 2 页 A4。
- 普通问候请用专业、简洁的管家语气回复，不要调用工具。
"""

    # 新版 google-genai SDK 直接传 Python function 即自动调用并回填结果
    response = client.models.generate_content(
        model="gemini-3.6-flash",  # 如追求更快/更稳的 function calling，可改 "gemini-2.0-flash"
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[create_official_pdf],
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
