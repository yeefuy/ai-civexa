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

# ================= PDF 生成工具 (最终排版版) =================
def create_official_pdf(client_name: str, client_attn: str, doc_no: str,
                        subject: str, items_json: str, note_text: str,
                        original_price: float, discount_amount: float,
                        doc_type: str = "INVOICE") -> str:
    
    # 中文检测
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
    
    # --- 样式定义 (统一发票和估价单) ---
    # 1. 公司名：大字号，大间距
    title_style = ParagraphStyle("Title", parent=styles["Normal"], fontName=BOLD_FONT, fontSize=24, alignment=1, textColor=colors.HexColor("#1A365D"), spaceAfter=12)
    # 2. 地址/注册号：小字号，浅灰色
    subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontName=REG_FONT, fontSize=7, alignment=1, textColor=colors.HexColor("#666666"), spaceAfter=4, leading=10)
    # 3. 单据标题
    doc_title_style = ParagraphStyle("DocTitle", parent=title_style, fontSize=18, alignment=1, textColor=colors.HexColor("#2B6CB0"), spaceAfter=15)
    
    # 4. 正文
    normal_style = ParagraphStyle("Normal", parent=styles["Normal"], fontName=REG_FONT, fontSize=9, leading=14)
    # 5. 右侧信息专用：右对齐
    right_info_style = ParagraphStyle("RightInfo", parent=normal_style, alignment=2) 
    
    header_style = ParagraphStyle("Header", parent=styles["Normal"], fontName=BOLD_FONT, fontSize=10, textColor=colors.HexColor("#1A365D"), spaceAfter=6)
    bold_style = ParagraphStyle("Bold", parent=normal_style, fontName=BOLD_FONT)
    right_style = ParagraphStyle("Right", parent=normal_style, alignment=2)
    
    inv_date = datetime.now()
    due_days = 14 if doc_type.upper() == "QUOTATION" else 7
    due_date = inv_date + timedelta(days=due_days)
    inv_str = _format_date_ordinal(inv_date)
    due_str = _format_date_ordinal(due_date)
    
    is_invoice = (doc_type.upper() == "INVOICE")
    doc_title = "INVOICE" if is_invoice else "QUOTATION"

    # 1. 页眉 (Header) - 间距拉开，字体比例正确
    story.append(Paragraph("<b>CIVEXA CONSTRUCTION</b>", title_style))
    story.append(Paragraph("(003666333-A) | CIDB-Registered Contractor", subtitle_style))
    story.append(Paragraph("48, Jalan Nuri 7/5, Kota Damansara, 47810 Petaling Jaya, Selangor Darul Ehsan.", subtitle_style))
    story.append(Paragraph("Tel: 012-208 5595 | Email: civexa2@gmail.com", subtitle_style))
    story.append(Spacer(1, 20)) 
    
    # 2. 单据标题
    story.append(Paragraph(f"<b>{doc_title}</b>", doc_title_style))

    # 3. 单据信息区 (Meta Info) - 左右分栏，右侧靠右对齐
    meta_left = f"<b>BILL TO:</b><br/><b>{client_name}</b><br/>Attn: {client_attn}"
    
    if is_invoice:
        meta_right = f"<b>INVOICE INFORMATION:</b><br/>Invoice Number: <b>{doc_no}</b><br/>Invoice Date: {inv_str}<br/>Due Date: {due_str}<br/>Payment: Bank Transfer / Cash / Cheque"
    else:
        meta_right = f"<b>QUOTATION INFORMATION:</b><br/>Quotation Number: <b>{doc_no}</b><br/>Quotation Date: {inv_str}<br/>Valid Until: {due_str}<br/>Payment: Bank Transfer / Cash / Cheque"

    # 关键：右侧列使用 right_info_style (右对齐)
    meta_data = [[Paragraph(meta_left, normal_style), Paragraph(meta_right, right_info_style)]]
    mt = Table(meta_data, colWidths=[250, 250])
    mt.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F8FAFC")), 
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),  
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 12), 
        ('BOTTOMPADDING', (0,0), (-1,-1), 12),
        ('LEFTPADDING', (0,0), (-1,-1), 12),
        ('RIGHTPADDING', (0,0), (-1,-1), 12),
    ]))
    story.append(mt)
    story.append(Spacer(1, 20))

    # 4. 工程范围 (Scope)
    story.append(Paragraph(f"<b>SUBJECT:</b> {subject}", bold_style))
    story.append(Spacer(1, 15))

    # 5. 表格 (Table)
    if is_invoice:
        rows = [[
            Paragraph("<b>NO.</b>", ParagraphStyle("TH", parent=normal_style, fontName=BOLD_FONT, textColor=colors.white)),
            Paragraph("<b>DESCRIPTION OF WORKS COMPLETED</b>", ParagraphStyle("TH", parent=normal_style, fontName=BOLD_FONT, textColor=colors.white))
        ]]
        for idx, item in enumerate(items, 1):
            title = item.get('title') or item.get('name') or ''
            details = item.get('details') or []
            if isinstance(details, str): details = [details]
            desc_html = f"<b>{title}</b>"
            if details:
                desc_html += "<br/>" + "<br/>".join(f"- {line}" for line in details)
            rows.append([Paragraph(str(idx), normal_style), Paragraph(desc_html, normal_style)])
        wt = Table(rows, colWidths=[40, 500], repeatRows=1)
    else:
        rows = [[
            Paragraph("<b>NO.</b>", ParagraphStyle("TH", parent=normal_style, fontName=BOLD_FONT, textColor=colors.white)),
            Paragraph("<b>DESCRIPTION OF WORKS</b>", ParagraphStyle("TH", parent=normal_style, fontName=BOLD_FONT, textColor=colors.white)),
            Paragraph("<b>AMOUNT (RM)</b>", ParagraphStyle("TH", parent=normal_style, fontName=BOLD_FONT, textColor=colors.white, alignment=2))
        ]]
        for idx, item in enumerate(items, 1):
            title = item.get('title') or item.get('name') or ''
            details = item.get('details') or []
            if isinstance(details, str): details = [details]
            desc_html = f"<b>{title}</b>"
            if details:
                desc_html += "<br/><font size=8 color='#555555'>" + "<br/>".join(f"- {line}" for line in details) + "</font>"
            rows.append([
                Paragraph(str(idx), normal_style),
                Paragraph(desc_html, normal_style),
                Paragraph("-", right_style)
            ])
        wt = Table(rows, colWidths=[40, 400, 100], repeatRows=1)

    wt.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#4A5568")), 
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E0")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(wt)
    story.append(Spacer(1, 15))

    # 6. 备注 (Note)
    if note_text:
        story.append(Paragraph(f"<i>Note: {note_text}</i>", ParagraphStyle("Note", parent=normal_style, fontSize=8, textColor=colors.HexColor("#555555"))))
        story.append(Spacer(1, 15))

    # 7. 价格汇总 (Totals)
    total = original_price - discount_amount
    if original_price > 0:
        calc_data = [
            [Paragraph("Subtotal (Lumpsum):" if is_invoice else "Sub-Total (RM):", normal_style), Paragraph(f"RM {original_price:.2f}", right_style)],
            [Paragraph("SST (0%):", normal_style), Paragraph("RM 0.00", right_style)],
        ]
        if discount_amount > 0:
            calc_data.insert(1, [Paragraph("Less: Loyal Customer Discount:", normal_style), Paragraph(f"(RM {discount_amount:.2f})", right_style)])
        
        calc_data.append([Paragraph("<b>TOTAL AMOUNT DUE:</b>", bold_style), Paragraph(f"<b>RM {total:.2f}</b>", ParagraphStyle("TotalRight", parent=right_style, fontName=BOLD_FONT, fontSize=12, textColor=colors.HexColor("#1A365D")))])
        
        ct = Table(calc_data, colWidths=[350, 150])
        ct.setStyle(TableStyle([
            ('LINEABOVE', (0,0), (-1,0), 0.5, colors.HexColor("#CBD5E0")),
            ('LINEBELOW', (0,-1), (-1,-1), 1.5, colors.HexColor("#1A365D")), 
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        story.append(ct)
        story.append(Spacer(1, 20))

    # 8. 付款说明 & 条款 (无签名区)
    if is_invoice:
        story.append(Paragraph("<b>PAYMENT INSTRUCTIONS</b>", header_style))
        story.append(Paragraph(f"Due: {due_str} (Within 7 days)<br/>Method: Bank Transfer / Cash / Cheque<br/>Bank: Maybank | Account Name: CIVEXA CONSTRUCTION<br/>Account No: 5142-0890-0031 | Reference: {doc_no}", normal_style))
        story.append(Paragraph("<font size=8 color='#718096'>State reference clearly to avoid processing delays.</font>", normal_style))
        story.append(Spacer(1, 15))
        
        terms_text = "Payment due within 7 days from invoice date - Late payment may result in work suspension & additional charges - All works completed as per agreed specifications - Special loyal customer rate applied - Quality workmanship guaranteed"
        story.append(Paragraph(f"<b>TERMS & CONDITIONS:</b> {terms_text}", ParagraphStyle("Terms", parent=normal_style, fontSize=7, leading=9, textColor=colors.HexColor("#718096"))))
        story.append(Spacer(1, 20))
        
    else:
        story.append(Paragraph("<b>TERMS & CONDITIONS</b>", header_style))
        terms_list = [
            "<b>Included:</b> labour, materials, equipment, debris disposal and site cleaning as specified.",
            "<b>Warranty:</b> 12 months workmanship warranty from practical completion.",
            "<b>Payment:</b> 50% deposit upon acceptance; 50% upon satisfactory completion.",
            "<b>Validity:</b> Prices are subject to change after the validity period.",
        ]
        for term in terms_list:
            story.append(Paragraph(f"• {term}", ParagraphStyle("TermItem", parent=normal_style, fontSize=8, leftIndent=10, spaceAfter=6)))
        story.append(Spacer(1, 20))

    # 9. 页脚
    story.append(Spacer(1, 20))
    story.append(Paragraph("<font size=7 color='#A0AEC0'>Thank You For Your Business! | CIVEXA CONSTRUCTION | CIDB Registered Contractor</font>", ParagraphStyle("Footer", parent=normal_style, alignment=1)))

    doc.build(story)
    return filename

# ================= Tools 定义 =================
tools_schema = [
    {"type": "function", "function": {"name": "get_next_doc_no", "description": "Get next available doc number", "parameters": {"type": "object", "properties": {"doc_type": {"type": "string", "enum": ["INVOICE", "QUOTATION"]}}, "required": ["doc_type"]}}},
    {"type": "function", "function": {"name": "check_doc_status", "description": "Check if doc exists", "parameters": {"type": "object", "properties": {"doc_no": {"type": "string"}}, "required": ["doc_no"]}}},
    {"type": "function", "function": {"name": "register_doc", "description": "Register doc to DB", "parameters": {"type": "object", "properties": {"doc_no": {"type": "string"}, "doc_type": {"type": "string", "enum": ["INVOICE", "QUOTATION"]}, "client_name": {"type": "string"}, "total_amount": {"type": "number"}}, "required": ["doc_no", "doc_type", "client_name", "total_amount"]}}},
    {"type": "function", "function": {"name": "create_official_pdf", "description": "Generate PDF. ENGLISH ONLY.", "parameters": {"type": "object", "properties": {"client_name": {"type": "string"}, "client_attn": {"type": "string"}, "doc_no": {"type": "string"}, "subject": {"type": "string"}, "items_json": {"type": "string"}, "note_text": {"type": "string"}, "original_price": {"type": "number"}, "discount_amount": {"type": "number"}, "doc_type": {"type": "string", "enum": ["INVOICE", "QUOTATION"]}}, "required": ["client_name", "client_attn", "doc_no", "subject", "items_json", "original_price", "discount_amount", "doc_type"]}}}
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
    
    # 处理登记模式
    if force_action == "REGISTER":
        action_instruction = """
        【最高指令：仅登记/补录】
        用户正在手动登记一个已经在别处（如 Claude）做好的单据。
        你的任务：
        1. 从用户输入中提取：单据号 (doc_no)、客户名 (client_name)、总金额 (total_amount)。
        2. 根据单据号前缀自动判断 doc_type (INV开头=INVOICE, QT开头=QUOTATION)。
        3. **只调用 `register_doc`**。
        4. **严禁调用 `create_official_pdf`**。
        5. 回复用户：“✅ 已登记 [号码] 到系统，该号码已被锁定，下次自动生成将跳过。”
        """
    # 处理样本模式 (新增)
    elif force_action == "SAMPLE":
        action_instruction = """
        【最高指令：生成排版样本】
        用户需要检查 PDF 排版。
        1. 使用虚拟数据：客户名 'Sample Client Sdn Bhd'，联系人 'Mr. Sample'，号码 'SAMPLE-INV-001'，原价 RM 1000，折扣 RM 100。
        2. 主旨写 'Sample Layout Check - Repair Works'。
        3. **严禁调用 `check_doc_status` 和 `register_doc`** (不查重、不存库)。
        4. **直接调用 `create_official_pdf`** 生成文件。
        5. 回复用户："🎨 这是排版样本，未存入数据库。"
        """

    system_prompt = f"""你是企业级 AI 总管。
{mode_instruction}
{action_instruction}

【最高强制规则 - 纯英文输出】
生成 PDF 时，所有内容 (subject, items, note) 必须是 100% 纯英文。
翻译范例：
  「拆除旧瓷砖」→「Removal of existing damaged tiles」
  「安装新瓷砖」→「Installation of new tiles」

【工作流】
1. 确定单据号：用户指定则用指定的；未指定则调用 `get_next_doc_no`。
2. 调用 `check_doc_status` 防重。
3. 如果是生成任务：调用 `create_official_pdf` (全英文)，成功后调用 `register_doc`。
4. 如果是登记任务 (force_action=REGISTER)：直接调用 `register_doc`。
5. 如果是样本任务 (force_action=SAMPLE)：直接调用 `create_official_pdf`。

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
