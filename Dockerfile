FROM python:3.10-slim

# 安裝雲端中文字體，確保生成的 PDF 中文不亂碼（需搭配 USE_CJK_FONT=1 啟用）
RUN apt-get update && apt-get install -y fonts-wqy-zenhei && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 僅作文件用途；實際監聽端口由 app.py 讀取 Render 注入的 PORT 環境變數
EXPOSE 7860

# 【關鍵修正】改用 python 啟動，端口在 app.py 內讀 $PORT，避免 Render 健康檢查失敗
CMD ["python", "app.py"]
