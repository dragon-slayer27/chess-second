FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends stockfish \
    && rm -rf /var/lib/apt/lists/*

ENV STOCKFISH_PATH=/usr/games/stockfish \
    SECOND_DATA_DIR=/tmp/second-reviews \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY second ./second
COPY samples ./samples

EXPOSE 10000
CMD ["sh", "-c", "uvicorn second.web:app --host 0.0.0.0 --port ${PORT:-10000}"]
