FROM python:3.10-slim

WORKDIR /app

# 確保 log 能即時印出，避免緩衝卡在容器內
ENV PYTHONUNBUFFERED=1

# 安裝基本網路診斷工具與 ssh 用戶端環境
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製主程式與前端模板（不複製 servers.json 與私鑰）
COPY app.py .
COPY templates/ ./templates/

EXPOSE 5000

CMD ["python", "app.py"]