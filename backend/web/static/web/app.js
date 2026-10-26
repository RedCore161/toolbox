"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

// ───────────── shared helpers ─────────────

function csrfToken() {
  return document.cookie.split("; ").find((c) => c.startsWith("csrftoken="))?.split("=")[1] ?? "";
}

async function postForm(url, formData) {
  const resp = await fetch(url, { method: "POST", body: formData, headers: { "X-CSRFToken": csrfToken() } });
  const data = await resp.json().catch(() => ({ detail: `${resp.status} ${resp.statusText}` }));
  if (!resp.ok) throw new Error(errorText(data));
  return data;
}

// DRF errors are {"detail": "..."} or {"field": ["msg", ...]}.
function errorText(data) {
  if (data.detail) return data.detail;
  return Object.entries(data).map(([k, v]) => `${k}: ${[].concat(v).join(" ")}`).join(" · ");
}

function setMsg(el, text, { error = false, busy = false } = {}) {
  el.classList.toggle("error", error);
  el.innerHTML = "";
  if (busy) el.insertAdjacentHTML("afterbegin", '<span class="spinner"></span>');
  el.append(text);
}

function formatTime(seconds) {
  const s = Math.floor(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function storage(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch { /* private mode etc. */ }
}

// ───────────── tabs ─────────────

function showTab(name) {
  $$(".tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === name)));
  $$(".panel").forEach((p) => (p.hidden = p.id !== `tab-${name}`));
  storage("tab", name);
}
$$(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
showTab(storage("tab") || "speech");

// ───────────── service health ─────────────

let healthTimer;
async function pollHealth() {
  let health = null;
  try {
    health = await (await fetch("/api/health/")).json();
  } catch { /* backend unreachable */ }
  for (const service of ["stt", "vision"]) {
    const info = health?.[service];
    const chip = $(`.chip[data-service="${service}"]`);
    const loading = !info?.ok && /loading/.test(info?.detail ?? "");
    chip.className = `chip ${info?.ok ? "ok" : loading ? "loading" : "down"}`;
    chip.title = info?.ok ? (info.device ?? info.languages?.join(", ") ?? "ok") : info?.detail ?? "unreachable";
  }
  if (health?.stt?.languages) fillLanguages(health.stt.languages, health.stt.default);
  const allOk = health?.stt?.ok && health?.vision?.ok;
  clearTimeout(healthTimer);
  healthTimer = setTimeout(pollHealth, allOk ? 60_000 : 5_000);
}

function fillLanguages(languages, fallback) {
  const select = $("#language");
  if (select.options.length > 1) return;
  const saved = storage("language") || fallback;
  select.innerHTML = languages.map((l) => `<option value="${l}">${l.toUpperCase()}</option>`).join("");
  if (languages.includes(saved)) select.value = saved;
}
$("#language").addEventListener("change", (e) => storage("language", e.target.value));
pollHealth();

// ───────────── speech to text ─────────────

const speech = {
  mic: $("#mic"),
  recordBtn: $("#record"),
  allowBtn: $("#mic-allow"),
  level: $("#level"),
  timer: $("#timer"),
  msg: $("#speech-msg"),
  transcript: $("#transcript"),
  playback: $("#playback"),
  recorder: null,
  stream: null,
  audioCtx: null,
  startedAt: 0,
  tick: null,
};

const MIME_TYPES = [
  ["audio/webm;codecs=opus", "webm"],
  ["audio/ogg;codecs=opus", "ogg"],
  ["audio/mp4", "m4a"],
  ["audio/webm", "webm"],
];

async function listMicrophones() {
  if (!navigator.mediaDevices?.getUserMedia) {
    speech.mic.innerHTML = "<option>Not available</option>";
    setMsg(speech.msg, "Microphone access needs a secure origin: open the page via http://localhost or HTTPS.", { error: true });
    return;
  }
  const devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "audioinput");
  // Browsers hide device labels until the page has been granted microphone access once.
  const hasLabels = devices.some((d) => d.label);
  speech.allowBtn.hidden = hasLabels || devices.length === 0;
  if (devices.length === 0) {
    speech.mic.innerHTML = "<option>No microphone found</option>";
    speech.mic.disabled = true;
    speech.recordBtn.disabled = true;
    return;
  }
  const saved = storage("mic");
  speech.mic.innerHTML = devices
    .map((d, i) => `<option value="${d.deviceId}">${d.label || `Microphone ${i + 1}`}</option>`)
    .join("");
  if (devices.some((d) => d.deviceId === saved)) speech.mic.value = saved;
  speech.mic.disabled = !hasLabels;
  speech.recordBtn.disabled = false;
}

async function requestMicAccess() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((t) => t.stop());
    setMsg(speech.msg, "");
  } catch (err) {
    setMsg(speech.msg, `Microphone access denied: ${err.message}`, { error: true });
  }
  await listMicrophones();
}

speech.allowBtn.addEventListener("click", requestMicAccess);
$("#mic-refresh").addEventListener("click", listMicrophones);
speech.mic.addEventListener("change", () => storage("mic", speech.mic.value));
navigator.mediaDevices?.addEventListener?.("devicechange", listMicrophones);
listMicrophones();

async function startRecording() {
  const deviceId = speech.mic.disabled ? undefined : speech.mic.value;
  try {
    speech.stream = await navigator.mediaDevices.getUserMedia({
      audio: deviceId ? { deviceId: { exact: deviceId } } : true,
    });
  } catch (err) {
    setMsg(speech.msg, `Could not open microphone: ${err.message}`, { error: true });
    return;
  }
  if (speech.mic.disabled) listMicrophones(); // first grant: labels are available now

  const [mimeType, ext] = MIME_TYPES.find(([m]) => MediaRecorder.isTypeSupported(m)) ?? ["", "webm"];
  const chunks = [];
  speech.recorder = new MediaRecorder(speech.stream, mimeType ? { mimeType } : {});
  speech.recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  speech.recorder.onstop = () => {
    const blob = new Blob(chunks, { type: speech.recorder.mimeType || mimeType });
    speech.playback.src = URL.createObjectURL(blob);
    speech.playback.hidden = false;
    transcribe(new File([blob], `recording.${ext}`, { type: blob.type }));
  };
  speech.recorder.start(250);

  startMeter(speech.stream);
  speech.startedAt = performance.now();
  speech.timer.textContent = "0:00";
  speech.tick = setInterval(() => {
    speech.timer.textContent = formatTime((performance.now() - speech.startedAt) / 1000);
  }, 250);
  speech.recordBtn.setAttribute("aria-pressed", "true");
  speech.recordBtn.querySelector(".label").textContent = "Stop";
  speech.mic.disabled = true;
  setMsg(speech.msg, "Recording…");
}

function stopRecording() {
  speech.recorder?.state === "recording" && speech.recorder.stop();
  speech.stream?.getTracks().forEach((t) => t.stop());
  speech.audioCtx?.close();
  clearInterval(speech.tick);
  speech.level.style.width = "0";
  speech.recordBtn.setAttribute("aria-pressed", "false");
  speech.recordBtn.querySelector(".label").textContent = "Record";
  speech.mic.disabled = false;
}

function startMeter(stream) {
  speech.audioCtx = new AudioContext();
  const analyser = speech.audioCtx.createAnalyser();
  analyser.fftSize = 512;
  speech.audioCtx.createMediaStreamSource(stream).connect(analyser);
  const data = new Uint8Array(analyser.fftSize);
  const draw = () => {
    if (speech.audioCtx.state === "closed") return;
    analyser.getByteTimeDomainData(data);
    const peak = data.reduce((max, v) => Math.max(max, Math.abs(v - 128)), 0) / 128;
    speech.level.style.width = `${Math.min(100, peak * 140)}%`;
    requestAnimationFrame(draw);
  };
  draw();
}

speech.recordBtn.addEventListener("click", () => {
  speech.recorder?.state === "recording" ? stopRecording() : startRecording();
});

$("#audio-file").addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;
  speech.playback.src = URL.createObjectURL(file);
  speech.playback.hidden = false;
  transcribe(file);
  e.target.value = "";
});

async function transcribe(file) {
  const form = new FormData();
  form.append("audio", file);
  const language = $("#language").value;
  if (language) form.append("language", language);

  speech.recordBtn.disabled = true;
  setMsg(speech.msg, "Transcribing…", { busy: true });
  try {
    const result = await postForm("/api/stt/transcribe/", form);
    if (result.text) {
      insertAtCursor(speech.transcript, result.text);
      setMsg(speech.msg, `Transcribed ${result.duration_s.toFixed(1)} s of audio (${result.language}).`);
    } else {
      setMsg(speech.msg, "No speech recognised.", { error: true });
    }
  } catch (err) {
    setMsg(speech.msg, err.message, { error: true });
  } finally {
    speech.recordBtn.disabled = false;
  }
}

// Insert at the caret (or replace the selection), keeping words separated by a space.
function insertAtCursor(textarea, text) {
  const { selectionStart: start, selectionEnd: end, value } = textarea;
  const before = value.slice(0, start);
  const sep = before && !/\s$/.test(before) ? " " : "";
  textarea.setRangeText(sep + text, start, end, "end");
  textarea.focus();
}

$("#copy").addEventListener("click", async () => {
  await navigator.clipboard.writeText(speech.transcript.value);
  setMsg(speech.msg, "Copied to clipboard.");
});
$("#clear").addEventListener("click", () => {
  speech.transcript.value = "";
  speech.transcript.focus();
});

// ───────────── image tools ─────────────

const vision = {
  file: null,
  background: null,
  mode: "matte",
  drop: $("#drop"),
  img: $("#preview-img"),
  overlay: $("#overlay"),
  form: $("#vision-form"),
  run: $("#run"),
  msg: $("#vision-msg"),
  outputs: $("#outputs"),
};

const OUTPUT_LABELS = {
  alpha: "Alpha map",
  cutout: "Cutout",
  foreground_mask: "Foreground mask",
  background_mask: "Background mask",
  edited: "Edited",
};

function setImage(file) {
  if (!file?.type.startsWith("image/")) return;
  vision.file = file;
  vision.img.src = URL.createObjectURL(file);
  $("#drop-empty").hidden = true;
  $("#preview").hidden = false;
  vision.overlay.innerHTML = "";
  vision.run.disabled = false;
}

$("#image-file").addEventListener("change", (e) => setImage(e.target.files[0]));
vision.drop.addEventListener("dragover", (e) => { e.preventDefault(); vision.drop.classList.add("over"); });
vision.drop.addEventListener("dragleave", () => vision.drop.classList.remove("over"));
vision.drop.addEventListener("drop", (e) => {
  e.preventDefault();
  vision.drop.classList.remove("over");
  setImage(e.dataTransfer.files[0]);
});
document.addEventListener("paste", (e) => {
  const item = [...(e.clipboardData?.items ?? [])].find((i) => i.type.startsWith("image/"));
  if (item && !$("#tab-vision").hidden) setImage(item.getAsFile());
});

function updateFields() {
  const op = $("#operation").value;
  $$("[data-for]").forEach((el) => {
    const forMode = el.dataset.for.split(" ").includes(vision.mode);
    const forOp = !el.dataset.op || el.dataset.op === op;
    el.hidden = !(forMode && forOp);
  });
}
$$(".segmented button").forEach((b) =>
  b.addEventListener("click", () => {
    vision.mode = b.dataset.mode;
    $$(".segmented button").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
    updateFields();
  }),
);
$("#operation").addEventListener("change", updateFields);
$("#blur").addEventListener("input", (e) => ($("#blur-out").textContent = e.target.value));
$("#background").addEventListener("change", (e) => {
  vision.background = e.target.files[0] ?? null;
  $("#bg-label").textContent = vision.background ? vision.background.name : "Or background image…";
});
updateFields();

vision.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!vision.file) return;

  const form = new FormData();
  form.append("image", vision.file);
  let url;
  if (vision.mode === "analyze") {
    const task = $("#task").value;
    const query = $("#aquery").value.trim();
    form.append("task", task);
    form.append("query", task === "detection" ? query.split(",").map((s) => s.trim()).filter(Boolean).join("\n") : query);
    url = "/api/vision/analyze/";
  } else {
    form.append("query", $("#query").value.trim() || "the main subject");
    url = `/api/vision/${vision.mode}/`;
    if (vision.mode === "edit") {
      const op = $("#operation").value;
      form.append("operation", op);
      if (op === "replace_background") {
        vision.background ? form.append("background", vision.background) : form.append("color", $("#color").value);
      }
      if (op === "blur_background") form.append("blur_radius", $("#blur").value);
    }
  }

  vision.run.disabled = true;
  const started = performance.now();
  const tick = setInterval(() => {
    setMsg(vision.msg, `Running… ${formatTime((performance.now() - started) / 1000)}`, { busy: true });
  }, 500);
  setMsg(vision.msg, "Running…", { busy: true });
  try {
    renderResult(await postForm(url, form));
    setMsg(vision.msg, "");
  } catch (err) {
    setMsg(vision.msg, err.message, { error: true });
  } finally {
    clearInterval(tick);
    vision.run.disabled = false;
  }
});

function renderResult(job) {
  const { result = {}, output_urls: urls = {} } = job;
  $("#latency").textContent = result.latency_s ? `model ${result.latency_s.toFixed(1)} s` : "";

  vision.outputs.innerHTML = "";
  for (const [name, href] of Object.entries(urls)) {
    const label = OUTPUT_LABELS[name] ?? name.replace(/_/g, " ");
    const fig = document.createElement("figure");
    fig.className = "output";
    fig.innerHTML = `<div class="img"><img alt=""></div>
      <figcaption><span></span><a download>Download</a></figcaption>`;
    fig.querySelector("img").src = href;
    fig.querySelector("img").alt = label;
    fig.querySelector("span").textContent = label;
    fig.querySelector("a").href = href;
    fig.querySelector("a").download = `${job.id}_${name}.png`;
    vision.outputs.append(fig);
  }

  const detections = result.detections ?? [];
  if (!vision.outputs.children.length) {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = detections.length ? `${detections.length} found, boxes drawn on the image.` : "No image output for this task.";
    vision.outputs.append(p);
  }
  drawDetections(detections, result.width, result.height);

  $("#raw").hidden = !result.response;
  $("#raw-text").textContent = result.response ?? "";
}

function drawDetections(detections, width, height) {
  const svg = vision.overlay;
  svg.innerHTML = "";
  if (!detections.length || !width) return;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const ns = "http://www.w3.org/2000/svg";
  const scale = width / vision.img.clientWidth; // keep label text a constant on-screen size
  for (const { label, box: [x1, y1, x2, y2] } of detections) {
    const rect = document.createElementNS(ns, "rect");
    Object.entries({ x: x1, y: y1, width: x2 - x1, height: y2 - y1 }).forEach(([k, v]) => rect.setAttribute(k, v));
    const text = document.createElementNS(ns, "text");
    text.setAttribute("x", x1 + 4 * scale);
    text.setAttribute("y", y1 + 16 * scale);
    text.setAttribute("font-size", 14 * scale);
    text.setAttribute("stroke-width", 3 * scale);
    text.textContent = label;
    svg.append(rect, text);
  }
}
