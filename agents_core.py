import os
import json
import time
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# 初始化 Gemini 客户端
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# ================= 数据库配置 =================
# ⚠️ 注意：如果 Render 连不上你的 cPanel 数据库，请检查 DB_HOST 是否为 cPanel 提供的远程地址，
# 并且 cPanel 里是否开启了 "Remote MySQL" 并添加了 Render 的 IP。
DB_CONFIG = {
    'host': os.environ.get("DB_HOST", "localhost"),
    'user': os.environ.get("DB_USER", "webcre6_你的用户名"),  # 请替换！
    'password': os.environ.get("DB_PASSWORD", "你的密码"),      # 请替换！
    'database': os.environ.get("DB_NAME", "webcre6_Civexa_bot") # 请替换！
}

def get_db_conn():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as e:
        print(f"Database connection error: {e}")
        return None

# ================= 字体注册 =================
REG_FONT, BOLD_FONT = "Helvetica", "Helvetica-Bold"
if os.environ.get("USE_CJK_FONT", "0") == "1":
    try:
        pdfmetrics.registerFont(TTFont("WQY", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", subfontIndex=0))
        REG_FONT, BOLD_FONT = "WQY", "WQY"
    except Exception:
        pass

# ================= 企业规范知识库 =================
COMPANY_KNOWLEDGE = """
【企业官方资讯】
- 公司名称：CIVEXA CONSTRUCTION
- 资质与注册：CIDB Registered Contractor | Company Reg. No: 003666333-A
- 公司地址：48, Jalan Nuri 7/5, Kota Damansara, 47810 Petaling Jaya, Selangor
- 联系方式：Email: civexa2@gmail.com | Tel: 012-208 5595
- 收款银行：Maybank | Account Name: CIVEXA CONSTRUCTION | Account No: 5142-0890-0031
- 默认货币：RM (马来西亚林吉特)

【单据排版规范】
- 编号格式：发票 INV-xxxxx，估价单 QT-xxxxx。
- 日期格式：序数+完整月份，例 4th November 2026（禁缩写/前导零）。
- 期限：发票 Due Date 为 7 天内；估价单 Valid Until 为 30 天内。
- 折扣标签：必须 "Loyal Customer Discount"（禁 Special Discount）。
- 页面：单张 A4 不超过 2 页。
"""

def _format_date_ordinal(d: datetime) -> str:
    day = d.day
    if day % 100 in (11, 12, 13):
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} {d.strftime('%B')} {d.year}"

# ================= 数据库工具函数 (AI 可调用的 Tools) =================
def check_doc_status(doc_no: str) -> str:
    """检查单据是否已开立（防重）"""
    conn = get_db_conn()
    if not conn: return "⚠️ 数据库连接失败，无法检查状态。"
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM invoice_ledger WHERE doc_no = %s", (doc_no,))
        result = cursor.fetchone()
        if result:
            return f"⚠️ 警告：单据 {doc_no} ({result['doc_type']}) 已于 {result['created_at']} 开立给 {result['client_name']}，金额 RM {result['total_amount']}。请勿重复开立。"
        return f"✅ 确认：单据 {doc_no} 尚未开立，可以继续生成。"
    except Error as e:
        return f"⚠️ 查询失败：{e}"
    finally:
        if conn.is_connected(): conn.close()

def register_doc(doc_no: str, doc_type: str, client_name: str, total_amount: float) -> str:
    """登记新单据到数据库"""
    conn = get_db_conn()
    if not conn: return "⚠️ 数据库连接失败，无法登记。"
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO invoice_ledger (doc_no, doc_type, client_name, client_attn, subject, original_price, discount_amount, total_amount, pdf_path)
               VALUES (%s, %s, %s, '', '', 0, 0, %s, '')""",
            (doc_no, doc_type, client_name, total_amount)
        )
        conn.commit()
        return f"✅ 已登记 {doc_type} {doc_no}（客户: {client_name}，金额: RM {total_amount}）到系统帐册。"
    except Error as e:
        return f"⚠️ 登记失败：{e}"
    finally:
        if conn.is_connected(): conn.close()

# ================= PDF 生成工具 =================
def create_official_pdf(client_name: str, client_attn: str, doc_no: str,
                        subject: str, items_json: str, note_text: str,
                        original_price: float, discount_amount: float,
                        doc_type: str = "INVOICE") -> str:
    """生成 A4 PDF（完美支持 INVOICE 和 QUOTATION 双模式）"""
    try:
        items = json.loads(items_json) if isinstance(items_json, str) else items_json
        if not isinstance(items, list): items = [items]
    except Exception:
        items = [{"title": "Works", "details": ["Completed"]}]

    safe_client = "".join(c for c in client_name if c.isalnum() or c in (" ", "_")).rstrip()
    filename = f"/tmp/{doc_no}_{safe_client.replace(' ', '_')}.pdf"

    doc = SimpleDocTemplate(filename, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Normal"], fontName=REG_FONT, fontSize=16, alignment=1, textColor=colors.HexColor("#1A365D"), leading=22)
    normal_style = ParagraphStyle("NormalCN", parent=styles["Normal"], fontName=REG_FONT, fontSize=9, leading=13)
    bold_style = ParagraphStyle("BoldCN", parent=normal_style, fontName=BOLD_FONT, fontSize=9, textColor=colors.HexColor("#1A365D"))

    inv_date = datetime.now()
    # 核心区别：发票7天，估价单30天
    due_date = inv_date + timedelta(days=7 if doc_type.upper() == "INVOICE" else 30)
    inv_str, due_str = _format_date_ordinal(inv_date), _format_date_ordinal(due_date)
    
    is_invoice = (doc_type.upper() == "INVOICE")
    doc_title = "INVOICE" if is_invoice else "QUOTATION"
    doc_label = "Invoice" if is_invoice else "Quotation"
    date_label = "Invoice Date" if is_invoice else "Quotation Date"
    due_label = "Due Date" if is_invoice else "Valid Until"

    # 1. 标头
    story.append(Paragraph("<b>CIVEXA CONSTRUCTION</b>", title_style))
    story.append(Spacer(1, 5))
    story.append(Paragraph("<font size=8 color='#555555'>CIDB Registered Contractor | Company Reg. No: 003666333-A<br/>48, Jalan Nuri 7/5, Kota Damansara, 47810 Petaling Jaya, Selangor<br/>Email: civexa2@gmail.com | Tel: 012-208 5595</font>", normal_style))
    story.append(Spacer(1, 15))
    story.append(Paragraph(f"<b>{doc_title}</b>", ParagraphStyle("DocTitle", parent=title_style, fontSize=14, textColor=colors.HexColor("#2B6CB0"), alignment=1)))
    story.append(Spacer(1, 15))

    # 2. 客户与单据信息
    info = [[
        Paragraph(f"<b>BILL TO:</b><br/><b>{client_name}</b><br/>Attn: {client_attn}", normal_style),
        Paragraph(f"<b>{doc_label.upper()} INFORMATION:</b><br/>{doc_label} Number: <b>{doc_no}</b><br/>{date_label}: {inv_str}<br/>{due_label}: {due_str}<br/>Payment: Bank Transfer / Cash / Cheque", normal_style)
    ]]
    t = Table(info, colWidths=[270, 270])
    t.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#F7FAFC")), ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E0")), ("TOPPADDING", (0,0), (-1,-1), 10), ("BOTTOMPADDING", (0,0), (-1,-1), 10), ("LEFTPADDING", (0,0), (-1,-1), 10), ("RIGHTPADDING", (0,0), (-1,-1), 10)]))
    story.append(t); story.append(Spacer(1, 15))

    # 3. 主旨
    story.append(Paragraph(f"<b>SUBJECT:</b> {subject}", bold_style))
    story.append(Spacer(1, 10))

    # 4. 明细表格 (兼容多种字段名)
    rows = [[Paragraph("<b>NO.</b>", bold_style), Paragraph(f"<b>DESCRIPTION OF {'WORKS COMPLETED' if is_invoice else 'WORKS'}</b>", bold_style)]]
    for idx, item in enumerate(items, 1):
        title = item.get('title') or item.get('name') or item.get('description') or ''
        details = item.get('details') or item.get('lines') or []
        if isinstance(details, str): details = [details]
        desc_html = f"<b>{title}</b>" + ("<br/>" + "<br/>".join(f"- {line}" for line in details) if details else "")
        rows.append([Paragraph(str(idx), normal_style), Paragraph(desc_html, normal_style)])
        
    wt = Table(rows, colWidths=[40, 500], repeatRows=1)
    wt.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#EDF2F7")), ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E0")), ("VALIGN", (0,0), (-1,-1), "TOP"), ("TOPPADDING", (0,0), (-1,-1), 8), ("BOTTOMPADDING", (0,0), (-1,-1), 8)]))
    story.append(wt); story.append(Spacer(1, 10))

    # 5. Note 备注
    if note_text:
        story.append(Paragraph(f"<b>Note:</b> {note_text}", normal_style))
        story.append(Spacer(1, 8))

    # 6. 价格计算
    total = original_price - discount_amount
    calc = [
        [Paragraph("Original Price:", normal_style), Paragraph(f"RM {original_price:.2f}", normal_style)],
        [Paragraph("Loyal Customer Discount:", normal_style), Paragraph(f"- RM {discount_amount:.2f}", normal_style)],
        [Paragraph("SST (0%):", normal_style), Paragraph("RM 0.00", normal_style)],
        [Paragraph("<b>TOTAL AMOUNT DUE:</b>", bold_style), Paragraph(f"<b>RM {total:.2f}</b>", bold_style)],
    ]
    ct = Table(calc, colWidths=[380, 160])
    ct.setStyle(TableStyle([("LINEABOVE", (0,0), (-1,0), 0.5, colors.HexColor("#CBD5E0")), ("LINEBELOW", (0,-1), (-1,-1), 1, colors.HexColor("#1A365D")), ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6)]))
    story.append(ct); story.append(Spacer(1, 15))

    # 7. 底部条款 (发票和估价单不同)
    if is_invoice:
        story.append(Paragraph(f"<b>PAYMENT INSTRUCTIONS</b><br/>Due: {due_str} (Within 7 days)<br/>Method: Bank Transfer / Cash / Cheque<br/>Bank: Maybank | Account Name: CIVEXA CONSTRUCTION<br/>Account No: 5142-0890-0031 | Reference: {doc_no}<br/>State reference clearly to avoid processing delays.", normal_style))
        story.append(Spacer(1, 8))
        story.append(Paragraph("<b>TERMS &amp; CONDITIONS:</b> Payment due within 7 days from invoice date - Late payment may result in work suspension &amp; additional charges - All works completed as per agreed specifications - Special loyal customer rate applied - Quality workmanship guaranteed", ParagraphStyle("Terms", parent=normal_style, fontSize=7, leading=9, textColor=colors.HexColor("#718096"))))
    else:
        story.append(Paragraph(f"<b>QUOTATION TERMS</b><br/>This quotation is valid until {due_str} (30 days from date of issue).<br/>Prices are subject to change after the validity period.<br/>50% deposit required upon acceptance of this quotation.<br/>Bank: Maybank | Account Name: CIVEXA CONSTRUCTION | Account No: 5142-0890-0031", normal_style))
        story.append(Spacer(1, 8))
        story.append(Paragraph("<b>TERMS &amp; CONDITIONS:</b> This quotation covers labour and materials as specified above - Any additional works will be charged separately - Workmanship guaranteed - Subject to site inspection confirmation", ParagraphStyle("Terms", parent=normal_style, fontSize=7, leading=9, textColor=colors.HexColor("#718096"))))
            
    story.append(Spacer(1, 20))
    # 8. 页脚
    story.append(Paragraph("<font size=7 color='#718096'>Thank You For Your Business!  |  For any queries regarding this document, please contact us.  |  CIVEXA CONSTRUCTION  |  CIDB Registered Contractor</font>", ParagraphStyle("Footer", parent=normal_style, alignment=1)))

    doc.build(story)
    return filename

# ================= 多 Agent 总指挥 (支持强制模式) =================
def run_multi_agent_system(user_message: str, force_mode: str = None):
    # 构建强制模式指令
    mode_instruction = ""
    if force_mode:
        mode_instruction = f"【最高指令】：当前已被用户通过指令强制锁定为 {force_mode} 模式。无论用户说什么，你生成的 doc_type 必须是 '{force_mode}'！"

    system_prompt = f"""你是企业级 AI 总管。
{mode_instruction}

【工作流】
1. 调用 `check_doc_status(doc_no)` 检查是否重复。
2. 如果未重复，调用 `create_official_pdf(...)` 生成文件。注意 `doc_type` 必须正确！
3. 生成成功后，调用 `register_doc(doc_no, doc_type, client_name, total_amount)` 存入数据库。

【工具参数】
- `doc_type`: 必须是 "INVOICE" 或 "QUOTATION"。
- `items_json`: JSON 字符串数组，如：[{{"title": "工程标题", "details": ["细节1"]}}]

公司规范：
{COMPANY_KNOWLEDGE}
"""
    tools = [check_doc_status, register_doc, create_official_pdf]
    config = types.GenerateContentConfig(system_instruction=system_prompt, tools=tools, temperature=0.2)

    # 自动重试与模型降级机制
    models_to_try = ["gemini-3.6-flash"]
    response = None

    for model_name in models_to_try:
        for attempt in range(3):
            try:
                response = client.models.generate_content(model=model_name, contents=user_message, config=config)
                break
            except Exception as e:
                error_msg = str(e)
                if "503" in error_msg or "UNAVAILABLE" in error_msg:
                    if attempt < 2: time.sleep(5)
                elif "404" in error_msg or "NOT_FOUND" in error_msg:
                    break
                else:
                    raise e
        if response is not None: break

    if response is None:
        raise Exception("所有模型均尝试失败。")

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
            if generated_pdf_path: break
                
    return response.text, generated_pdf_path
