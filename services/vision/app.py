"""WeVisOne-VL inference over HTTP: detection, segmentation and alpha matting."""

import base64
import io
import os
import re
import threading
import time
from contextlib import asynccontextmanager

import numpy as np
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from PIL import Image
from wevisone_vl import TASKS, WeVisOneVL
from wevisone_vl.mask_decoder import FourierPE1D

MODEL_ID = os.environ.get("WEVIS_MODEL", "tencent/WeVisOne-VL-2B")
DEVICE = os.environ.get("WEVIS_DEVICE", "auto")
DTYPE = os.environ.get("WEVIS_DTYPE", "float16")
# Caps the vision tokens fed to the VLM. Masks are still returned at full input resolution.
MAX_PIXELS = int(os.environ.get("WEVIS_MAX_PIXELS", 768 * 512))
# Each instance costs ~1.3 GB in the full-res decoder; 1 keeps peak memory flat for many objects.
DECODER_BATCH_SIZE = int(os.environ.get("WEVIS_DECODER_BATCH_SIZE", 1))
LOAD_ATTEMPTS = int(os.environ.get("WEVIS_LOAD_ATTEMPTS", 10))

REF_BOX_RE = re.compile(r"<ref>(.*?)</ref>\s*<box>(.*?)</box>", re.DOTALL)
COORD_RE = re.compile(r"<(\d{1,4})>")

state: dict = {"model": None, "error": None, "last_error": None}
lock = threading.Lock()


def fix_float16_decoder(model: WeVisOneVL) -> None:
    """Upstream builds the mask decoder in the model dtype. Its Fourier frequencies (2**i, up to 2**31)
    overflow to inf in float16 (max 65504), which turns every mask into NaN. bfloat16 has the range,
    float16 (needed on pre-Ampere GPUs) does not. Run the tiny decoder in float32 and rebuild the buffers."""
    model.mask_decoder.float()
    for module in model.mask_decoder.modules():
        if isinstance(module, FourierPE1D):
            n = module.frequencies.numel()
            module.frequencies = 2.0 ** torch.arange(n, dtype=torch.float32, device=module.frequencies.device)
    model.dtype = torch.float32  # after __init__ this is only used to cast the decoder's inputs


def load() -> None:
    # Retries cover flaky weight downloads; partial files are resumed by huggingface_hub.
    for attempt in range(1, LOAD_ATTEMPTS + 1):
        try:
            model = WeVisOneVL(
                MODEL_ID, backend="transformers", device=DEVICE, dtype=DTYPE,
                max_pixels=MAX_PIXELS, decoder_batch_size=DECODER_BATCH_SIZE,
            )
            if model.dtype == torch.float16:
                fix_float16_decoder(model)
            state["model"] = model
            return
        except Exception as exc:
            state["last_error"] = f"attempt {attempt}/{LOAD_ATTEMPTS}: {exc!r}"
            print(f"model load failed ({state['last_error']})", flush=True)
            time.sleep(min(30 * attempt, 300))
    state["error"] = state["last_error"]  # give up: surfaced via /health


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Load in the background so the first boot (multi-GB download) doesn't block the server.
    threading.Thread(target=load, daemon=True).start()
    yield


app = FastAPI(title="toolbox-vision", lifespan=lifespan)


def mask_to_png_b64(mask: np.ndarray) -> str:
    buf = io.BytesIO()
    Image.fromarray((np.clip(mask, 0, 1) * 255).astype(np.uint8), mode="L").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def parse_detections(response: str, width: int, height: int) -> list[dict]:
    """Turn `<ref>label</ref><box><x1><y1><x2><y2>,...</box>` (0..1000 coords) into labelled pixel boxes."""
    detections = []
    for label, body in REF_BOX_RE.findall(response):
        for group in body.split(","):
            coords = [int(v) for v in COORD_RE.findall(group)]
            if len(coords) >= 4:
                x1, y1, x2, y2 = coords[:4]
                detections.append({
                    "label": label.strip(),
                    "box": [x1 / 1000 * width, y1 / 1000 * height, x2 / 1000 * width, y2 / 1000 * height],
                })
    return detections


@app.get("/health")
def health():
    if state["error"]:
        raise HTTPException(500, state["error"])
    if state["model"] is None:
        detail = "model loading" + (f" (retrying after {state['last_error']})" if state["last_error"] else "")
        raise HTTPException(503, detail)
    return {"status": "ok", "model": MODEL_ID, "device": str(state["model"].device)}


@app.post("/predict")
def predict(image: UploadFile = File(...), task: str = Form(...), query: str = Form("")) -> dict:
    model = state["model"]
    if model is None:
        raise HTTPException(503, state["error"] or "model loading")
    if task not in TASKS:
        raise HTTPException(400, f"unknown task {task!r}; choose from {list(TASKS)}")

    img = Image.open(io.BytesIO(image.file.read())).convert("RGB")
    queries = [q.strip() for q in query.split("\n") if q.strip()] if task == "detection" else query
    with lock:
        result = model.predict(img, task=task, query=queries)
        if model.device.type == "cuda":
            torch.cuda.empty_cache()

    width, height = img.size
    return {
        "task": task,
        "query": query,
        "response": result.response,
        "width": width,
        "height": height,
        "detections": parse_detections(result.response, width, height),
        # Mask boxes come back normalised (0..1); convert them to pixels for consistency.
        "boxes": [[b[0] * width, b[1] * height, b[2] * width, b[3] * height] for b in result.boxes],
        "masks": [mask_to_png_b64(m) for m in result.masks],
        "latency_s": result.latency_s,
    }
