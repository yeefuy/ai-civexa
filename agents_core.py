import os
import json
import time
import re
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from groq import Groq
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ================= Groq 客户端初始化 =================
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# ================= Supabase 数据库配置 =================
DB_CONFIG = {
    'host': os.environ.get("DB_HOST", "db.vnpalwldlobrdmyyjrxf.supabase.co"),
    'port': int(os.environ.get("DB_PORT", 5432)),
    'database': os.environ.get("DB_NAME", "postgres"),
    'user': os.environ.get("DB_USER", "postgres"),
    'password': os.environ.get("DB_PASSWORD", "")
}

def get_db_conn():
    if not DB_CONFIG['password']: return None
    try: return psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        print(f"DB Error: {e}")
        return None

# ================= 字体注册 =================
REG_FONT, BOLD_FONT = "Helvetica", "Helvetica-Bold"
if os.environ.get("USE_CJK_FONT", "0") == "1":
    try:
        pdfmetrics.registerFont(TTFont("WQY", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", subfontIndex=0))
        REG_FONT, BOLD_FONT = "WQY", "WQY"
    except Exception: pass

# ================= 企业规范 =================
COMPANY_KNOWLEDGE = """
【企业官方资讯】
- 公司名称：CIVEXA CONSTRUCTION
- 资质与注册：(003666333-A) | CIDB-Registered Contractor
- 公司地址：48, Jalan Nuri 7/5, Kota Damansara, 47810 Petaling Jaya, Selangor Darul Ehsan.
- 联系方式：Tel: 012-208 5595 | Email: civexa2@gmail.com
- 收款银行：Maybank | Account Name: CIVEXA CONSTRUCTION | Account No: 5142-0890-0031

【单据排版规范】
- 编号格式：发票 INV-xxxxx，估价单 QT-xxxxx。
- 日期格式：序数+完整月份，例 18th November 2026。
- 期限：发票 Due Date 为 7 天内；估价单 Valid Until 为 14 天内。
- 折扣标签：必须 "Loyal Customer Discount" 或 "Valued Returning Customer Discount"。
"""

def _format_date_ordinal(d: datetime) -> str:
    day = d.day
    suffix = "th" if day % 100 in (11, 12, 13) else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} {d.strftime('%B')} {d.year}"

# ================= 数据库工具 =================
def get_next_doc_no(doc_type: str) -> str:
    conn = get_db_conn()
    if not conn: return "⚠️ DB connection failed."
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT doc_no FROM invoice_ledger WHERE doc_type = %s ORDER BY id DESC LIMIT 1", (doc_type,))
        result = cursor.fetchone()
        if result:
            last_no = result[0]
            match = re.search(r'(\d+)$', last_no)
            if match:
                num = int(match.group(1)) + 1
                prefix = last_no[:match.start()]
                return f"✅ Next number: {prefix}{str(num).zfill(len(match.group(1)))}"
        return f"✅ Next number: {'INV-10001' if doc_type == 'INVOICE' else 'QT-2026-001'}"
    except Exception as e: return f"⚠️ Query failed: {e}"
    finally:
        if conn: conn.close()

def check_doc_status(doc_no: str) -> str:
    conn = get_db_conn()
    if not conn: return "⚠️ DB connection failed."
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute("SELECT * FROM invoice_ledger WHERE doc_no = %s", (doc_no,))
        result = cursor.fetchone()
        if result:
            return f"⚠️ Warning: {doc_no} already exists ({result['doc_type']}) for {result['client_name']}, RM {result['total_amount']}."
        return f"✅ Confirmed: {doc_no} is available."
    except Exception as e: return f"⚠️ Query failed: {e}"
    finally:
        if conn: conn.close()

def register_doc(doc_no: str, doc_type: str, client_name: str, total_amount: float) -> str:
    conn = get_db_conn()
    if not conn: return "⚠️ DB connection failed."
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO invoice_ledger (doc_no, doc_type, client_name, client_attn, subject, original_price, discount_amount, total_amount, pdf_path)
               VALUES (%s, %s, %s, '', '', 0, 0, %s, '')""",
            (doc_no, doc_type, client_name, total_amount)
        )
        conn.commit()
        return f"✅ Registered {doc_no} ({doc_type}) for {client_name}, RM {total_amount}. Number LOCKED."
    except Exception as e: return f"⚠️ Registration failed: {e}"
    finally:
        if conn: conn.close()

# ================= PDF 生成工具 (修复版：名字不重复 + 地址显示) =================
def create_official_pdf(client_name: str, client_attn: str, doc_no: str,
                        subject: str, items_json: str, note_text: str,
                        original_price: float, discount_amount: float,
                        doc_type: str = "INVOICE",
                        client_address: str = "") -> str:
    
    _check_text = (subject or "") + (note_text or "") + str(items_json)
    if re.search(r'[\u4e00-\u9fff]', _check_text):
        return "⚠️ CHINESE DETECTED: Abort. Translate to English first."

    try:
        items = json.loads(items_json) if isinstance(items_json, str) else items_json
        if not isinstance(items, list): items = [items]
    except: items = [{"title": "Works", "details": ["Completed"]}]

    safe_client = "".join(c for c in client_name if c.isalnum() or c in (" ", "_")).rstrip()
    filename = f"/tmp/{doc_no}_{safe_client.replace(' ', '_')}.pdf"

    doc = SimpleDocTemplate(filename, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    styles = getSampleStyleSheet()
    
    # ========== 专业字体层级系统 ==========
    company_name_style = ParagraphStyle("CompanyName", parent=styles["Normal"], 
                                        fontName=BOLD_FONT, fontSize=20, alignment=1, 
                                        textColor=colors.HexColor("#1A365D"), spaceAfter=10)
    
    address_style = ParagraphStyle("Address", parent=styles["Normal"], 
                                   fontName=REG_FONT, fontSize=8, alignment=1, 
                                   textColor=colors.HexColor("#666666"), spaceAfter=2, leading=10)
    
    doc_title_style = ParagraphStyle("DocTitle", parent=styles["Normal"], 
                                     fontName=BOLD_FONT, fontSize=16, alignment=1, 
                                     textColor=colors.HexColor("#2B6CB0"), spaceBefore=8, spaceAfter=8)
    
    section_header_style = ParagraphStyle("SectionHeader", parent=styles["Normal"], 
                                          fontName=BOLD_FONT, fontSize=10, 
                                          textColor=colors.HexColor("#1A365D"), spaceAfter=6)
    
    body_style = ParagraphStyle("Body", parent=styles["Normal"], 
                                fontName=REG_FONT, fontSize=9, leading=12)
    
    right_info_style = ParagraphStyle("RightInfo", parent=body_style, alignment=2)
    
    bold_body_style = ParagraphStyle("BoldBody", parent=body_style, fontName=BOLD_FONT)
    
    right_amount_style = ParagraphStyle("RightAmount", parent=body_style, alignment=2)
    
    total_style = ParagraphStyle("Total", parent=body_style, 
                                 fontName=BOLD_FONT, alignment=2, 
                                 textColor=colors.HexColor("#1A365D"))
    
    small_note_style = ParagraphStyle("SmallNote", parent=styles["Normal"], 
                                      fontName=REG_FONT, fontSize=7, 
                                      textColor=colors.HexColor("#888888"), leading=9)
    
    terms_style = ParagraphStyle("Terms", parent=styles["Normal"], 
                                 fontName=REG_FONT, fontSize=7.5, 
                                 textColor=colors.HexColor("#666666"), leading=10, spaceAfter=3)
    
    footer_style = ParagraphStyle("Footer", parent=styles["Normal"], 
                                  fontName=REG_FONT, fontSize=7, 
                                  textColor=colors.HexColor("#AAAAAA"), alignment=1)

    inv_date = datetime.now()
    due_days = 14 if doc_type.upper() == "QUOTATION" else 7
    due_date = inv_date + timedelta(days=due_days)
    inv_str = _format_date_ordinal(inv_date)
    due_str = _format_date_ordinal(due_date)
    
    is_invoice = (doc_type.upper() == "INVOICE")
    doc_title = "INVOICE" if is_invoice else "QUOTATION"

    # ========== 1. 页眉 ==========
    story.append(Paragraph("<b>CIVEXA CONSTRUCTION</b>", company_name_style))
    story.append(Paragraph("(003666333-A) | CIDB-Registered Contractor", address_style))
    story.append(Paragraph("48, Jalan Nuri 7/5, Kota Damansara, 47810 Petaling Jaya, Selangor Darul Ehsan.", address_style))
    story.append(Paragraph("Tel: 012-208 5595 | Email: civexa2@gmail.com", address_style))
    
    # ========== 2. 单据标题 ==========
    story.append(Paragraph(f"<b>{doc_title}</b>", doc_title_style))

    # ========== 3. 单据信息区 (修复：名字不重复，地址显示) ==========
    bill_to_lines = ["<b>BILL TO:</b>"]
    bill_to_lines.append(f"<b>{client_name}</b>")
    
    if client_address:
        bill_to_lines.append(client_address)
    
    if client_attn and client_attn.strip().lower() != client_name.strip().lower():
        bill_to_lines.append(f"Attn: {client_attn}")
    
    meta_left = "<br/>".join(bill_to_lines)
    
    if is_invoice:
        meta_right = f"<b>INVOICE INFORMATION:</b><br/>Invoice Number: <b>{doc_no}</b><br/>Invoice Date: {inv_str}<br/>Due Date: {due_str}<br/>Payment: Bank Transfer / Cash / Cheque"
    else:
        meta_right = f"<b>QUOTATION INFORMATION:</b><br/>Quotation Number: <b>{doc_no}</b><br/>Quotation Date: {inv_str}<br/>Valid Until: {due_str}<br/>Payment: Bank Transfer / Cash / Cheque"

    meta_data = [[Paragraph(meta_left, body_style), Paragraph(meta_right, right_info_style)]]
    mt = Table(meta_data, colWidths=[250, 250])
    mt.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")), 
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),  
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(mt)
    story.append(Spacer(1, 12))

    # ========== 4. 工程范围 ==========
    story.append(Paragraph(f"<b>SUBJECT:</b> {subject}", bold_body_style))
    story.append(Spacer(1, 10))

    # ========== 5. 表格 ==========
    if is_invoice:
        rows = [[
            Paragraph("<b>NO.</b>", ParagraphStyle("TH", parent=body_style, fontName=BOLD_FONT, textColor=colors.white)),
            Paragraph("<b>DESCRIPTION OF WORKS COMPLETED</b>", ParagraphStyle("TH", parent=body_style, fontName=BOLD_FONT, textColor=colors.white))
        ]]
        for idx, item in enumerate(items, 1):
            title = item.get('title') or item.get('name') or ''
            details = item.get('details') or []
            if isinstance(details, str): details = [details]
            desc_html = f"<b>{title}</b>"
            if details:
                desc_html += "<br/>" + "<br/>".join(f"- {line}" for line in details)
            rows.append([Paragraph(str(idx), body_style), Paragraph(desc_html, body_style)])
        wt = Table(rows, colWidths=[40, 460], repeatRows=1)
    else:
        rows = [[
            Paragraph("<b>NO.</b>", ParagraphStyle("TH", parent=body_style, fontName=BOLD_FONT, textColor=colors.white)),
            Paragraph("<b>DESCRIPTION OF WORKS</b>", ParagraphStyle("TH", parent=body_style, fontName=BOLD_FONT, textColor=colors.white)),
            Paragraph("<b>AMOUNT (RM)</b>", ParagraphStyle("TH", parent=body_style, fontName=BOLD_FONT, textColor=colors.white, alignment=2))
        ]]
        for idx, item in enumerate(items, 1):
            title = item.get('title') or item.get('name') or ''
            details = item.get('details') or []
            if isinstance(details, str): details = [details]
            desc_html = f"<b>{title}</b>"
            if details:
                desc_html += "<br/><font size=8 color='#555555'>" + "<br/>".join(f"- {line}" for line in details) + "</font>"
            rows.append([
                Paragraph(str(idx), body_style),
                Paragraph(desc_html, body_style),
                Paragraph("-", right_amount_style)
            ])
        wt = Table(rows, colWidths=[40, 360, 100], repeatRows=1)

    wt.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#4A5568")), 
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E0")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(wt)
    story.append(Spacer(1, 10))

    # ========== 6. 备注 ==========
    if note_text:
        story.append(Paragraph(f"<i>Note: {note_text}</i>", ParagraphStyle("Note", parent=body_style, fontSize=8, textColor=colors.HexColor("#555555"))))
        story.append(Spacer(1, 10))

    # ========== 7. 价格汇总 ==========
    total = original_price - discount_amount
    if original_price > 0:
        calc_data = [
            [Paragraph("Subtotal (Lumpsum):" if is_invoice else "Sub-Total (RM):", body_style), Paragraph(f"RM {original_price:.2f}", right_amount_style)],
            [Paragraph("SST (0%):", body_style), Paragraph("RM 0.00", right_amount_style)],
        ]
        if discount_amount > 0:
            calc_data.insert(1, [Paragraph("Less: Loyal Customer Discount:", body_style), Paragraph(f"(RM {discount_amount:.2f})", right_amount_style)])
        
        calc_data.append([Paragraph("<b>TOTAL AMOUNT DUE:</b>", bold_body_style), Paragraph(f"<b>RM {total:.2f}</b>", total_style)])
        
        ct = Table(calc_data, colWidths=[350, 150])
        ct.setStyle(TableStyle([
            ('LINEABOVE', (0,0), (-1,0), 0.5, colors.HexColor("#CBD5E0")),
            ('LINEBELOW', (0,-1), (-1,-1), 1.5, colors.HexColor("#1A365D")), 
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        story.append(ct)
        story.append(Spacer(1, 12))

    # ========== 8. 付款说明 & 条款 ==========
    if is_invoice:
        story.append(Paragraph("<b>PAYMENT INSTRUCTIONS</b>", section_header_style))
        story.append(Paragraph(f"Due: {due_str} (Within 7 days)<br/>Method: Bank Transfer / Cash / Cheque<br/>Bank: Maybank | Account Name: CIVEXA CONSTRUCTION<br/>Account No: 5142-0890-0031 | Reference: {doc_no}", body_style))
        story.append(Paragraph("State reference clearly to avoid processing delays.", small_note_style))
        story.append(Spacer(1, 10))
        
        terms_text = "Payment due within 7 days from invoice date - Late payment may result in work suspension & additional charges - All works completed as per agreed specifications - Special loyal customer rate applied - Quality workmanship guaranteed"
        story.append(Paragraph(f"<b>TERMS & CONDITIONS:</b> {terms_text}", terms_style))
        story.append(Spacer(1, 12))
        
    else:
        story.append(Paragraph("<b>TERMS & CONDITIONS</b>", section_header_style))
        terms_list = [
            "<b>Included:</b> labour, materials, equipment, debris disposal and site cleaning as specified.",
            "<b>Warranty:</b> 12 months workmanship warranty from practical completion.",
            "<b>Payment:</b> 50% deposit upon acceptance; 50% upon satisfactory completion.",
            "<b>Validity:</b> Prices are subject to change after the validity period.",
        ]
        for term in terms_list:
            story.append(Paragraph(f"• {term}", terms_style))
        story.append(Spacer(1, 12))

    # ========== 9. 页脚 ==========
    story.append(Spacer(1, 15))
    story.append(Paragraph("Thank You For Your Business! | CIVEXA CONSTRUCTION | CIDB Registered Contractor", footer_style))

    doc.build(story)
    return filename

# ================= Tools 定义 (语法修复版) =================
tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "get_next_doc_no",
            "description": "Get next available doc number",
            "parameters": {
                "type": "object",
                "properties": {"doc_type": {"type": "string", "enum": ["INVOICE", "QUOTATION"]}},
                "required": ["doc_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_doc_status",
            "description": "Check if doc exists",
            "parameters": {
                "type": "object",
                "properties": {"doc_no": {"type": "string"}},
                "required": ["doc_no"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "register_doc",
            "description": "Register doc to DB",
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
            "description": "Generate PDF. ENGLISH ONLY.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name": {"type": "string"},
                    "client_attn": {"type": "string"},
                    "client_address": {"type": "string", "description": "Client address. Displayed under client name in BILL TO section."},
                    "doc_no": {"type": "string"},
                    "subject": {"type": "string"},
                    "items_json": {"type": "string", "description": "JSON array of items. Each item must have 'title' and 'details' (array of strings)."},
                    "note_text": {"type": "string"},
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
    "get_next_doc_no": get_next_doc_no,
    "check_doc_status": check_doc_status,
    "register_doc": register_doc,
    "create_official_pdf": create_official_pdf,
}

# ================= 总指挥 =================
def run_multi_agent_system(user_message: str, force_mode: str = None, force_action: str = None):
    mode_instruction = ""
    if force_mode:
        mode_instruction = f"【模式锁定】doc_type 必须是 '{force_mode}'。"
    
    action_instruction = ""
    
    if force_action == "REGISTER":
        action_instruction = """
        【最高指令：仅登记/补录】
        1. 提取：doc_no, client_name, total_amount。
        2. 自动判断 doc_type (INV=INVOICE, QT=QUOTATION)。
        3. **只调用 `register_doc`**。严禁调用 `create_official_pdf`。
        """
    elif force_action == "SAMPLE":
        action_instruction = """
        【最高指令：生成排版样本 - 绝对禁止提问】
        1. **严禁提问**，严禁要求用户提供信息。
        2. **严禁调用 `check_doc_status` 和 `register_doc`**。
        3. **必须立即调用 `create_official_pdf`**，使用以下虚拟数据：
           - client_name: "Sample Client Sdn Bhd"
           - client_attn: "Mr. Sample"
           - client_address: "123, Jalan Sample, 12345 City, State"
           - doc_no: "SAMPLE-001"
           - doc_type: "INVOICE"
           - subject: "Sample Layout Check - Repair Works"
           - items_json: '[{"title": "Sample Work Item 1", "details": ["Detail A", "Detail B"]}, {"title": "Sample Work Item 2", "details": ["Detail C"]}]'
           - original_price: 1000.00
           - discount_amount: 100.00
           - note_text: "This is a layout sample."
        4. 回复："🎨 样本已生成。"
        """

    system_prompt = f"""你是企业级 AI 总管。
{mode_instruction}
{action_instruction}

【最高强制规则 - 纯英文输出】
生成 PDF 时，所有内容必须是 100% 纯英文。

【工作流】
1. 如果是 SAMPLE 模式：直接调用 `create_official_pdf` (用虚拟数据)。
2. 如果是 REGISTER 模式：直接调用 `register_doc`。
3. 如果是正常模式：
   a. 解析用户输入，提取：client_name, client_attn, client_address (如果有), doc_no (或自动查号), subject, items, original_price, discount_amount, note_text。
   b. **关键：items 必须是 JSON 数组格式**，例如：
      [
        {{"title": "Staircase Tile Installation", "details": ["Supply and install ceramic tiles"]}},
        {{"title": "Living Room Tile Installation", "details": ["Supply and install ceramic tiles"]}},
        {{"title": "Kitchen Tile Installation", "details": ["Supply and install ceramic tiles"]}}
      ]
   c. 调用 `check_doc_status` 防重。
   d. 调用 `create_official_pdf` (全英文)。
   e. 调用 `register_doc`。

【明细解析规则 - 重要！】
用户可能用以下方式提供明细，你必须正确解析成 items_json 数组：
- "明细：1. xxx 2. xxx 3. xxx" (数字 + 点号分隔)
- "明细：\\n1. xxx\\n2. xxx\\n3. xxx" (换行分隔)
- "明细：1. xxx; 2. xxx; 3. xxx" (分号分隔)
- "Items: 1. xxx, 2. xxx, 3. xxx" (逗号分隔)
- "明细：xxx, yyy, zzz" (无编号，直接逗号分隔)

解析后，每项必须包含：
- "title": 工程标题 (英文)
- "details": 工程细节数组 (英文，可以是空数组 [])

【BILL TO 区块规则 - 重要！】
1. **客户名 (client_name)**：显示在 BILL TO 第一行，加粗。
2. **地址 (client_address)**：如果用户提供了地址，显示在客户名下方第二行。
3. **联系人 (client_attn)**：只有当联系人和客户名**不同时**才显示在第三行，格式 "Attn: xxx"。
   - 如果客户名是 "Mr. Lim Eng Soon"，联系人也是 "Mr. Lim Eng Soon"，则**不显示** Attn 行。
   - 如果客户名是 "ABC Company"，联系人是 "Mr. Lim"，则显示 "Attn: Mr. Lim"。

示例：
用户输入："给 Mr. Lim Eng Soon 开发票，地址 No. 1, Jalan Perdana Residence 1, 68100 Selayang, Selangor Darul Ehsan"
你应提取：
- client_name: "Mr. Lim Eng Soon"
- client_address: "No. 1, Jalan Perdana Residence 1, 68100 Selayang, Selangor Darul Ehsan"
- client_attn: "Mr. Lim Eng Soon" (与 client_name 相同，PDF 中不显示 Attn 行)

公司规范：
{COMPANY_KNOWLEDGE}
"""

    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}]
    generated_pdf_path = None
    _iter = 0
    max_iter = 6

    while _iter < max_iter:
        _iter += 1
        try:
            response = client.chat.completions.create(model="openai/gpt-oss-120b", messages=messages, tools=tools_schema, tool_choice="auto", temperature=0.2)
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                time.sleep(5); continue
            else: raise e

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
                return message.content, generated_pdf_path

            messages.append({"tool_call_id": tool_call.id, "role": "tool", "name": function_name, "content": str(function_response)})
            
    return "⚠️ Max iterations reached.", generated_pdf_path
