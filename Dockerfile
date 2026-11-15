FROM python:3.10-slim

# 安裝雲端中文字體，確保生成的 PDF 中文不亂碼
RUN apt-get update && apt-get install -y fonts-wqy-zenhei && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
