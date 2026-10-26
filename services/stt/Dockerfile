FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the Vosk models into the image: "lang=model-name,lang=model-name"
ARG VOSK_MODELS=de=vosk-model-small-de-0.15,en=vosk-model-small-en-us-0.15
RUN mkdir -p /models && for pair in $(echo "$VOSK_MODELS" | tr ',' ' '); do \
        lang="${pair%%=*}"; name="${pair#*=}"; \
        curl -fsSL -o /tmp/model.zip "https://alphacephei.com/vosk/models/${name}.zip" \
        && unzip -q /tmp/model.zip -d /tmp/model \
        && mv "/tmp/model/${name}" "/models/${lang}" \
        && rm -rf /tmp/model /tmp/model.zip || exit 1; \
    done

COPY app.py .
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
