"""HTTP clients for the internal model services."""

import requests
from django.conf import settings
from rest_framework.exceptions import APIException


class ServiceError(APIException):
    """Upstream service failure; DRF renders it as {"detail": ...} with a matching status."""

    def __init__(self, service: str, status: int, detail):
        # Client errors (bad audio, unknown language) pass through; everything else is a bad gateway.
        self.status_code = status if 400 <= status < 500 or status == 503 else 502
        super().__init__(f"{service}: {detail}")


def _post(service: str, url: str, files: dict, data: dict) -> dict:
    try:
        resp = requests.post(url, files=files, data=data, timeout=settings.SERVICE_TIMEOUT)
    except requests.RequestException as exc:
        raise ServiceError(service, 503, str(exc)) from exc
    if not resp.ok:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        raise ServiceError(service, resp.status_code, detail)
    return resp.json()


def health(base_url: str) -> dict:
    try:
        resp = requests.get(f"{base_url}/health", timeout=5)
        return {"ok": resp.ok, **(resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {})}
    except requests.RequestException as exc:
        return {"ok": False, "detail": str(exc)}


def transcribe(audio_file, language: str = "") -> dict:
    audio_file.seek(0)
    return _post(
        "stt",
        f"{settings.STT_URL}/transcribe",
        files={"audio": (audio_file.name, audio_file)},
        data={"language": language} if language else {},
    )


def predict(image_file, task: str, query: str) -> dict:
    image_file.seek(0)
    return _post(
        "vision",
        f"{settings.VISION_URL}/predict",
        files={"image": (image_file.name, image_file)},
        data={"task": task, "query": query},
    )
