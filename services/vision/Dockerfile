# Upstream says 3.10, but its pinned deps (matplotlib 3.11, scipy 1.18) need >= 3.12.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
# Pinned upstream commit for reproducible builds.
ARG WEVIS_REF=9a6bcd85404505df0d05cfb5d97512ccacf35dee
RUN git clone https://github.com/Tencent/WeVisOne-VL.git \
    && cd WeVisOne-VL && git checkout "$WEVIS_REF" \
    && pip install --no-cache-dir .

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

EXPOSE 8000
# One worker: the model is loaded once and requests are serialised by a lock.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
