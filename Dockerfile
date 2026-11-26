FROM python:3.10-slim

LABEL org.opencontainers.image.source="https://github.com/wushiyi105-jpg/hejia"
LABEL org.opencontainers.image.description="核价 · 装修报价核查,逐行复算与漏项检测"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY . .

RUN pip install -e .

EXPOSE 8000

CMD ["python", "-m", "hejia", "web", "--host", "0.0.0.0"]
