import os
import json
import time
import re
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta
from openai import OpenAI
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ================= 客户端初始化 =================
# 注意：如果您使用的是 OpenRouter 或其他兼容 OpenAI 的平台，请修改 base_url
# 如果您使用的是 Groq，base_url 应为 "https://api.groq.com/openai/v1"
# 如果您使用的是 DeepSeek，base_url 应为 "https://api.deepseek.com"
client = OpenAI(
    api_key=os.environ.get("API_KEY"), # 请确保环境变量名与您的平台对应 (如 GROQ_API_KEY, OPENROUTER_API_KEY 等)
    base_url=os.environ.get("API_BASE_URL", "https://api.groq.com/openai/v1") 
)

# ================= 数据库配置 =================
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

# ================= 数据库工具函数 =================
def check_doc_status(doc_no: str) -> str:
    conn = get_db_conn()
    if not conn: return "⚠️ Database connection failed."
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM invoice_ledger WHERE doc_no = %s", (doc_no,))
        result = cursor.fetchone()
        if result:
            return f"⚠️ Warning: Document {doc_no} ({result['doc_type']}) was already created on {result['created_at']} for {result['client_name']}, amount RM {result['total_amount']}. Do not create duplicate."
        return f"✅ Confirmed: Document {doc_no} is not created yet, proceed."
    except Error as e:
        return f"⚠️ Query failed: {e}"
    finally:
        if conn.is_connected(): conn.close()

def register_doc(doc_no: str, doc_type: str, client_name: str, total_amount: float) -> str:
    conn = get_db_conn()
    if not conn: return "⚠️ Database connection failed."
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO invoice_ledger (doc_no, doc_type, client_name, client_attn, subject, original_price, discount_amount, total_amount, pdf_path)
               VALUES (%s, %s, %s, '', '', 0, 0, %s, '')""",
            (doc_no, doc_type, client_name, total_amount)
        )
        conn.commit()
        return f"✅ Registered {doc_type} {doc_no} (Client: {client_name}, Amount: RM {total_amount}) to ledger."
    except Error as e:
        return f"⚠️ Registration failed: {e}"
    finally:
        if conn.is_connected(): conn.close()

# ================= PDF 生成工具 =================
def create_official_pdf(client_name: str, client_attn: str, doc_no: str,
                        subject: str, items_json: str, note_text: str,
                        original_price: float, discount_amount: float,
                        doc_type: str = "INVOICE") -> str:
    """生成 A4 PDF（支持 INVOICE 和 QUOTATION）"""
    
    # 【中文检测兜底】强制要求全英文
    _check_text = (subject or "") + (note_text or "") + str(items_json)
    if re.search(r'[\u4e00-\u9fff]', _check_text):
        return "⚠️ CHINESE DETECTED: PDF generation aborted. You MUST translate subject, items_json, and note_text into professional English before calling this tool again."

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
    due_date = inv_date + timedelta(days=7 if doc_type.upper() == "INVOICE" else 30)
    inv_str, due_str = _format_date_ordinal(inv_date), _format_date_ordinal(due_date)
    
    is_invoice = (doc_type.upper() == "INVOICE")
    doc_title = "INVOICE" if is_invoice else "QUOTATION"
    doc_label = "Invoice" if is_invoice else "Quotation"
    date_label = "Invoice Date" if is_invoice else "Quotation Date"
    due_label = "Due Date" if is_invoice else "Valid Until"

    story.append(Paragraph("<b>CIVEXA CONSTRUCTION</b>", title_style))
    story.append(Spacer(1, 5))
    story.append(Paragraph("<font size=8 color='#555555'>CIDB Registered Contractor | Company Reg. No: 003666333-A<br/>48, Jalan Nuri 7/5, Kota Damansara, 47810 Petaling Jaya, Selangor<br/>Email: civexa2@gmail.com | Tel: 012-208 5595</font>", normal_style))
    story.append(Spacer(1, 15))
    story.append(Paragraph(f"<b>{doc_title}</b>", ParagraphStyle("DocTitle", parent=title_style, fontSize=14, textColor=colors.HexColor("#2B6CB0"), alignment=1)))
    story.append(Spacer(1, 15))

    info = [[
        Paragraph(f"<b>BILL TO:</b><br/><b>{client_name}</b><br/>Attn: {client_attn}", normal_style),
        Paragraph(f"<b>{doc_label.upper()} INFORMATION:</b><br/>{doc_label} Number: <b>{doc_no}</b><br/>{date_label}: {inv_str}<br/>{due_label}: {due_str}<br/>Payment: Bank Transfer / Cash / Cheque", normal_style)
    ]]
    t = Table(info, colWidths=[270, 270])
    t.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#F7FAFC")), ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E0")), ("TOPPADDING", (0,0), (-1,-1), 10), ("BOTTOMPADDING", (0,0), (-1,-1), 10), ("LEFTPADDING", (0,0), (-1,-1), 10), ("RIGHTPADDING", (0,0), (-1,-1), 10)]))
    story.append(t); story.append(Spacer(1, 15))

    story.append(Paragraph(f"<b>SUBJECT:</b> {subject}", bold_style))
    story.append(Spacer(1, 10))

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

    if note_text:
        story.append(Paragraph(f"<b>Note:</b> {note_text}", normal_style))
        story.append(Spacer(1, 8))

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

    if is_invoice:
        story.append(Paragraph(f"<b>PAYMENT INSTRUCTIONS</b><br/>Due: {due_str} (Within 7 days)<br/>Method: Bank Transfer / Cash / Cheque<br/>Bank: Maybank | Account Name: CIVEXA CONSTRUCTION<br/>Account No: 5142-0890-0031 | Reference: {doc_no}<br/>State reference clearly to avoid processing delays.", normal_style))
        story.append(Spacer(1, 8))
        story.append(Paragraph("<b>TERMS &amp; CONDITIONS:</b> Payment due within 7 days from invoice date - Late payment may result in work suspension &amp; additional charges - All works completed as per agreed specifications - Special loyal customer rate applied - Quality workmanship guaranteed", ParagraphStyle("Terms", parent=normal_style, fontSize=7, leading=9, textColor=colors.HexColor("#718096"))))
    else:
        story.append(Paragraph(f"<b>QUOTATION TERMS</b><br/>This quotation is valid until {due_str} (30 days from date of issue).<br/>Prices are subject to change after the validity period.<br/>50% deposit required upon acceptance of this quotation.<br/>Bank: Maybank | Account Name: CIVEXA CONSTRUCTION | Account No: 5142-0890-0031", normal_style))
        story.append(Spacer(1, 8))
        story.append(Paragraph("<b>TERMS &amp; CONDITIONS:</b> This quotation covers labour and materials as specified above - Any additional works will be charged separately - Workmanship guaranteed - Subject to site inspection confirmation", ParagraphStyle("Terms", parent=normal_style, fontSize=7, leading=9, textColor=colors.HexColor("#718096"))))
            
    story.append(Spacer(1, 20))
    story.append(Paragraph("<font size=7 color='#718096'>Thank You For Your Business!  |  For any queries regarding this document, please contact us.  |  CIVEXA CONSTRUCTION  |  CIDB Registered Contractor</font>", ParagraphStyle("Footer", parent=normal_style, alignment=1)))

    doc.build(story)
    return filename

# ================= OpenAI 格式的 Tools 定义 =================
tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "check_doc_status",
            "description": "Check if document is already created (anti-duplicate)",
            "parameters": {
                "type": "object",
                "properties": {"doc_no": {"type": "string", "description": "Document number, e.g. INV-10052"}},
                "required": ["doc_no"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "register_doc",
            "description": "Register new document to database",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_no": {"type": "string"},
                    "doc_type": {"type": "string", "enum": ["INVOICE", "QUOTATION"]},
                    "client_name": {"type": "string"},
                    "total_amount": {"type": "number"}
                },
                "required": ["doc_no", "doc_type", "client_name", "total_amount"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_official_pdf",
            "description": "Generate A4 PDF (Support INVOICE and QUOTATION). ALL CONTENT MUST BE IN ENGLISH.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name": {"type": "string"},
                    "client_attn": {"type": "string"},
                    "doc_no": {"type": "string"},
                    "subject": {"type": "string", "description": "Must be English"},
                    "items_json": {"type": "string", "description": "JSON string array of items. Title and details must be English."},
                    "note_text": {"type": "string", "description": "Must be English"},
                    "original_price": {"type": "number"},
                    "discount_amount": {"type": "number"},
                    "doc_type": {"type": "string", "enum": ["INVOICE", "QUOTATION"]}
                },
                "required": ["client_name", "client_attn", "doc_no", "subject", "items_json", "original_price", "discount_amount", "doc_type"]
            }
        }
    }
]

AVAILABLE_FUNCTIONS = {
    "check_doc_status": check_doc_status,
    "register_doc": register_doc,
    "create_official_pdf": create_official_pdf,
}

# ================= 多 Agent 总指挥 (带防死循环) =================
def run_multi_agent_system(user_message: str, force_mode: str = None):
    mode_instruction = ""
    if force_mode:
        mode_instruction = f"【最高指令】：当前已被用户通过指令强制锁定为 {force_mode} 模式。无论用户说什么，你生成的 doc_type 必须是 '{force_mode}'！"

    system_prompt = f"""你是企业级 AI 总管。
{mode_instruction}

【最高强制规则 - 纯英文输出】
你生成的所有单据内容（subject、items_json 里的 title/details、note_text）必须是 100% 纯英文专业工程术语，严禁出现任何中文字符，无论用户用什么语言输入。
翻译对照范例（照此风格翻译）：
  中文「拆除 Manhole Cover 旧破瓷砖 (Block 1=1pc & Block 2=1pc)」→ 英文「Removal of existing damaged tiles on manhole cover (Block 1 = 1pc & Block 2 = 1pc)」
  中文「安装新瓷砖」→ 英文「Installation of new high-durability tiles」
  中文「报价包含材料人工，含垃圾清运」→ 英文「Quotation includes materials and labour; debris disposal included」

【工作流】
1. 先把用户输入的中文内容全部翻译成英文，再调用工具。
2. 调用 `check_doc_status(doc_no)` 检查是否重复。
3. 如果未重复，调用 `create_official_pdf(...)` 生成文件（doc_type 必须正确，内容必须全英文）。
4. 生成成功后，调用 `register_doc(doc_no, doc_type, client_name, total_amount)` 存入数据库。

公司规范：
{COMPANY_KNOWLEDGE}
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]

    generated_pdf_path = None
    _iter = 0
    max_iter = 5  # 防止死循环，最多重试 5 次

    while _iter < max_iter:
        _iter += 1
        try:
            # 注意：请将下面的模型名称替换为您实际使用的模型，例如 "llama-3.3-70b-versatile" 或 "deepseek-chat"
            # 用户之前测试成功的是 "openai/gpt-oss-120b" (这通常是 OpenRouter 的格式)
            response = client.chat.completions.create(
                model=os.environ.get("MODEL_NAME", "openai/gpt-oss-120b"), 
                messages=messages,
                tools=tools_schema,
                tool_choice="auto",
                temperature=0.2
            )
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "rate" in error_msg.lower():
                time.sleep(5)
                continue
            else:
                raise e

        message = response.choices[0].message

        if not message.tool_calls:
            return message.content, generated_pdf_path

        messages.append(message)

        for tool_call in message.tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            function_response = AVAILABLE_FUNCTIONS[function_name](**function_args)
            
            if function_name == "create_official_pdf" and isinstance(function_response, str) and function_response.startswith("/tmp/"):
                generated_pdf_path = function_response

            messages.append({
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": function_name,
                "content": str(function_response),
            })
            
    return "⚠️ Max iterations reached. Please check input.", generated_pdf_path
