FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
  chromium \
  chromium-driver \
  fonts-liberation \
  fonts-noto \
  xdg-utils \
  ca-certificates \
  && ln -sf /usr/bin/chromium /usr/bin/google-chrome \
  && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
  CHROME_BIN=/usr/bin/chromium \
  CHROMEDRIVER_BIN=/usr/bin/chromedriver

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p logs

EXPOSE 8181

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8181"]
