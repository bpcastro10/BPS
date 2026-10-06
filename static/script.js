"use strict";

const MAX_BYTES = 25 * 1024 * 1024;
const $ = (id) => document.getElementById(id);

const ui = {
  status: $("status"),
  statusText: $("status-text"),
  source: $("source"),
  dropzone: $("dropzone"),
  fileInput: $("file-input"),
  viewer: $("viewer"),
  preview: $("preview"),
  previewNote: $("preview-note"),
  overlay: $("overlay"),
  overlayNote: $("overlay-note"),
  fileName: $("file-name"),
  run: $("run"),
  reset: $("reset"),
  empty: $("empty"),
  emptyText: $("empty-text"),
  loading: $("loading"),
  loadingTime: $("loading-time"),
  error: $("error"),
  errorText: $("error-text"),
  output: $("output"),
  overall: $("overall"),
  overallNumber: $("overall-number"),
  overallBadge: $("overall-badge"),
  overallMeter: $("overall-meter"),
  overallNote: $("overall-note"),
  review: $("review"),
  fields: $("fields"),
  copy: $("copy"),
  timing: $("timing"),
  details: $("details"),
  raw: $("raw"),
};

const EMPTY_TEXT = "Sube la imagen de un cheque para ver los datos extraídos y la confianza de cada uno.";
const READY_TEXT = "Imagen lista. Pulsa «Leer imagen» para extraer los datos.";

const FIELD_LABELS = {
  numero_cheque: "Número de cheque",
  pagese_a: "Páguese a",
  valor_numerico: "Valor en números",
  valor_letras: "Valor en letras",
  lugar: "Lugar",
  fecha: "Fecha",
  firma_presente: "Firma presente",
  firmas: "Firmas detectadas",
};

const LEVELS = { high: "Alta", mid: "Media", low: "Baja" };
const OVERALL_NOTES = {
  high: "El modelo estuvo muy seguro de lo que leyó. Aun así, compara los datos con la imagen antes de usarlos.",
  mid: "El modelo dudó en algunos datos. Revisa los que aparecen marcados abajo.",
  low: "El modelo estuvo poco seguro. Verifica cada dato contra la imagen.",
};

const numberFormat = new Intl.NumberFormat("es", { maximumFractionDigits: 1 });
const formatPct = (value) => `${numberFormat.format(value)}\u00a0%`;
const levelOf = (pct) => (pct >= 90 ? "high" : pct >= 70 ? "mid" : "low");
const humanize = (key) => {
  const text = key.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
};

let currentFile = null;
let objectUrl = null;
let lastResult = null;
let timer = null;

/* ---------- Utilidades de DOM ---------- */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function showView(name) {
  for (const key of ["empty", "loading", "error", "output"]) {
    ui[key].hidden = key !== name;
  }
}

function setStatus(state, text) {
  ui.status.dataset.state = state;
  ui.statusText.textContent = text;
}

/* ---------- Estado del servidor ---------- */
async function loadStatus() {
  try {
    const res = await fetch("/api/health");
    const health = await res.json();
    const device = health.device || "";
    if (device.startsWith("cuda")) setStatus("ok", `Modelo listo en la GPU (${device})`);
    else if (device.startsWith("mps")) setStatus("ok", "Modelo listo en la GPU de Apple");
    else setStatus("warn", "Modelo listo en la CPU: cada lectura será lenta");
  } catch {
    setStatus("off", "Sin conexión con el servidor");
  }
}

/* ---------- Selección de imagen ---------- */
function showError(message) {
  ui.errorText.textContent = message;
  showView("error");
}

function selectFile(file) {
  if (!file) return;
  if (file.type && !file.type.startsWith("image/")) {
    showError("Ese archivo no es una imagen. Elige un PNG, JPG, WEBP, BMP, TIFF o GIF.");
    return;
  }
  if (file.size > MAX_BYTES) {
    showError("La imagen supera los 25 MB. Reduce su tamaño e inténtalo de nuevo.");
    return;
  }

  currentFile = file;
  lastResult = null;
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = URL.createObjectURL(file);

  ui.previewNote.hidden = true;
  ui.overlay.replaceChildren();
  ui.overlayNote.hidden = true;
  ui.preview.src = objectUrl;
  ui.fileName.textContent = file.name || "Imagen pegada";

  ui.dropzone.hidden = true;
  ui.viewer.hidden = false;
  ui.reset.hidden = false;
  ui.run.disabled = false;

  ui.emptyText.textContent = READY_TEXT;
  showView("empty");
}

function resetAll() {
  currentFile = null;
  lastResult = null;
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = null;

  ui.fileInput.value = "";
  ui.preview.removeAttribute("src");
  ui.overlay.replaceChildren();
  ui.viewer.hidden = true;
  ui.dropzone.hidden = false;
  ui.reset.hidden = true;
  ui.run.disabled = true;
  ui.emptyText.textContent = EMPTY_TEXT;
  showView("empty");
}

ui.preview.addEventListener("error", () => {
  if (currentFile) ui.previewNote.hidden = false;
});

ui.dropzone.addEventListener("click", () => ui.fileInput.click());
ui.dropzone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    ui.fileInput.click();
  }
});
ui.fileInput.addEventListener("change", () => selectFile(ui.fileInput.files[0]));
ui.reset.addEventListener("click", resetAll);

for (const type of ["dragenter", "dragover"]) {
  ui.source.addEventListener(type, (event) => {
    event.preventDefault();
    ui.dropzone.classList.add("is-over");
  });
}
for (const type of ["dragleave", "drop"]) {
  ui.source.addEventListener(type, (event) => {
    event.preventDefault();
    ui.dropzone.classList.remove("is-over");
  });
}
ui.source.addEventListener("drop", (event) => selectFile(event.dataTransfer.files[0]));

document.addEventListener("paste", (event) => {
  const file = [...(event.clipboardData?.files || [])].find((f) => f.type.startsWith("image/"));
  if (file) selectFile(file);
});

/* ---------- Lectura con el modelo ---------- */
function setBusy(busy) {
  ui.run.disabled = busy;
  ui.reset.disabled = busy;
  ui.run.textContent = busy ? "Leyendo…" : "Leer imagen";
  ui.source.setAttribute("aria-busy", String(busy));
}

async function run() {
  if (!currentFile) return;

  setBusy(true);
  showView("loading");
  const started = performance.now();
  ui.loadingTime.textContent = "0 s";
  timer = setInterval(() => {
    ui.loadingTime.textContent = `${Math.round((performance.now() - started) / 1000)} s`;
  }, 1000);

  try {
    const body = new FormData();
    body.append("image", currentFile);
    const res = await fetch("/api/extract", { method: "POST", body });

    let payload = null;
    try {
      payload = await res.json();
    } catch {
      /* respuesta sin JSON */
    }
    if (!res.ok) {
      throw new Error(payload?.error || `El servidor respondió con el error ${res.status}.`);
    }

    lastResult = payload;
    renderResult(payload);
  } catch (error) {
    showError(
      error instanceof TypeError
        ? "No se pudo conectar con el servidor. Comprueba que app.py siga ejecutándose."
        : error.message
    );
  } finally {
    clearInterval(timer);
    setBusy(false);
  }
}
ui.run.addEventListener("click", run);

/* ---------- Mostrar resultados ---------- */
const isBox = (b) => Array.isArray(b) && b.length === 4 && b.every((n) => Number.isFinite(n));

function signatureBoxes(fields) {
  const boxes = [];
  for (const field of fields) {
    if (!/firma/i.test(field.key) || !Array.isArray(field.value)) continue;
    for (const box of field.value) {
      // Se asume que las coordenadas van de 0 a 1000 (x1, y1, x2, y2).
      if (isBox(box) && box.every((n) => n >= 0 && n <= 1000) && box[2] > box[0] && box[3] > box[1]) {
        boxes.push(box);
      }
    }
  }
  return boxes;
}

function drawBoxes(boxes) {
  ui.overlay.replaceChildren();
  boxes.forEach(([x1, y1, x2, y2], index) => {
    const box = el("div", "sig-box");
    box.style.left = `${x1 / 10}%`;
    box.style.top = `${y1 / 10}%`;
    box.style.width = `${(x2 - x1) / 10}%`;
    box.style.height = `${(y2 - y1) / 10}%`;
    box.appendChild(el("span", "", boxes.length > 1 ? `Firma ${index + 1}` : "Firma"));
    ui.overlay.appendChild(box);
  });
  ui.overlayNote.hidden = boxes.length === 0;
}

function formatValue(key, value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Sí" : "No";
  if (Array.isArray(value) && /firma/i.test(key) && value.length && value.every(isBox)) {
    return `${value.length} ${value.length === 1 ? "zona marcada" : "zonas marcadas"} en la imagen`;
  }
  if (typeof value === "object") return JSON.stringify(value);
  const text = String(value).trim();
  return text === "" ? "(vacío)" : text;
}

function renderField(field) {
  const pct = typeof field.confidence === "number" ? Math.min(100, Math.max(0, field.confidence)) : null;
  const item = el("li", "field");

  const head = el("div", "field-head");
  head.appendChild(el("span", "field-name", FIELD_LABELS[field.key] ?? humanize(field.key)));
  const conf = el("span", "field-conf");
  if (pct !== null) {
    const level = levelOf(pct);
    item.classList.add(`level-${level}`);
    conf.appendChild(el("span", "field-pct", formatPct(pct)));
    conf.appendChild(el("span", "badge", LEVELS[level]));
  } else {
    conf.appendChild(el("span", "note", "Sin dato de confianza"));
  }
  head.appendChild(conf);
  item.appendChild(head);

  item.appendChild(el("p", "field-value", formatValue(field.key, field.value)));

  if (pct !== null) {
    const meter = el("div", "meter");
    meter.setAttribute("role", "img");
    meter.setAttribute("aria-label", `Confianza ${formatPct(pct)}`);
    const fill = el("span");
    fill.dataset.target = String(pct);
    meter.appendChild(fill);
    item.appendChild(meter);
  }
  return item;
}

function renderReview(fields) {
  ui.review.replaceChildren();
  if (fields.length === 0) {
    ui.review.hidden = true;
    return;
  }
  ui.review.hidden = false;

  const doubtful = fields
    .filter((f) => typeof f.confidence === "number" && f.confidence < 90)
    .sort((a, b) => a.confidence - b.confidence);

  if (doubtful.length === 0) {
    ui.review.appendChild(el("p", "", "Todos los datos superan el 90 % de confianza."));
    return;
  }

  ui.review.appendChild(el("p", "review-title", "Conviene revisar estos datos"));
  const list = el("ul", "chips");
  for (const field of doubtful) {
    const chip = el(
      "li",
      `chip level-${levelOf(field.confidence)}`,
      `${FIELD_LABELS[field.key] ?? humanize(field.key)}: ${formatPct(field.confidence)}`
    );
    list.appendChild(chip);
  }
  ui.review.appendChild(list);
}

function renderResult(payload) {
  const fields = payload.fields || [];
  const overall = payload.confidence?.overall;

  // Confianza global
  ui.overall.classList.remove("level-high", "level-mid", "level-low");
  ui.overallMeter.style.width = "0";
  if (typeof overall === "number") {
    const level = levelOf(overall);
    ui.overall.classList.add(`level-${level}`);
    ui.overallNumber.textContent = formatPct(overall);
    ui.overallBadge.textContent = LEVELS[level];
    ui.overallMeter.dataset.target = String(Math.min(100, Math.max(0, overall)));
    ui.overallNote.textContent = OVERALL_NOTES[level];
  } else {
    ui.overallNumber.textContent = "--";
    ui.overallBadge.textContent = "";
    delete ui.overallMeter.dataset.target;
    ui.overallNote.textContent = "El modelo no devolvió texto, así que no hay confianza que mostrar.";
  }

  // Datos
  renderReview(fields);
  ui.fields.replaceChildren();
  if (fields.length) {
    for (const field of fields) ui.fields.appendChild(renderField(field));
  } else {
    const item = el("li", "field");
    item.appendChild(
      el("p", "note", "El modelo no devolvió un JSON válido. Abajo está su respuesta tal cual.")
    );
    ui.fields.appendChild(item);
  }

  ui.raw.textContent = payload.text || "(sin respuesta)";
  ui.details.open = fields.length === 0;
  ui.timing.textContent = `Leído en ${numberFormat.format(payload.seconds)} s`;
  ui.copy.textContent = "Copiar resultado";

  drawBoxes(signatureBoxes(fields));
  showView("output");

  // Las barras crecen desde cero una sola vez, al mostrar el resultado.
  requestAnimationFrame(() =>
    requestAnimationFrame(() => {
      ui.output.querySelectorAll("[data-target]").forEach((node) => {
        node.style.width = `${node.dataset.target}%`;
      });
    })
  );
}

/* ---------- Copiar resultado ---------- */
function exportObject() {
  const result = { confianza_global: lastResult.confidence?.overall ?? null, campos: {} };
  for (const field of lastResult.fields) {
    result.campos[field.key] = { valor: field.value, confianza: field.confidence };
  }
  if (lastResult.fields.length === 0) result.texto = lastResult.text;
  return result;
}

ui.copy.addEventListener("click", async () => {
  if (!lastResult) return;
  try {
    await navigator.clipboard.writeText(JSON.stringify(exportObject(), null, 2));
    ui.copy.textContent = "Copiado";
  } catch {
    ui.copy.textContent = "No se pudo copiar";
  }
  setTimeout(() => {
    ui.copy.textContent = "Copiar resultado";
  }, 1800);
});

loadStatus();

/* ---------- Lectura de la carpeta y informe ---------- */
const COLUMNAS_SI_NO = new Set([9, 10, 11, 12, 13]);
const lote = {
  carpeta: $("lote-carpeta"),
  cuenta: $("lote-cuenta"),
  archivos: $("lote-archivos"),
  run: $("lote-run"),
  refresh: $("lote-refresh"),
  download: $("lote-download"),
  progress: $("lote-progress"),
  error: $("lote-error"),
  errorText: $("lote-error-text"),
  resumen: $("lote-resumen"),
  tablaWrap: $("lote-tabla-wrap"),
  cuerpo: $("lote-cuerpo"),
  reglaFecha: $("lote-regla-fecha"),
  formatos: $("lote-formatos"),
};
let loteTimer = null;

function renderArchivos(nombres) {
  lote.archivos.replaceChildren();
  if (!nombres.length) {
    lote.cuenta.textContent = "La carpeta entrada está vacía. Copia ahí las imágenes de los cheques.";
    lote.run.disabled = true;
    return;
  }
  lote.run.disabled = false;
  lote.cuenta.textContent =
    nombres.length === 1 ? "1 imagen lista para leer." : `${nombres.length} imágenes listas para leer.`;
  for (const nombre of nombres) lote.archivos.appendChild(el("li", "", nombre));
}

async function cargarEntrada() {
  try {
    const res = await fetch("/api/entrada");
    const data = await res.json();
    lote.carpeta.textContent = data.carpeta ? `Carpeta: ${data.carpeta}` : "";
    renderArchivos(data.archivos || []);
  } catch {
    lote.cuenta.textContent = "No se pudo consultar la carpeta de entrada.";
    lote.run.disabled = true;
  }
}

async function cargarReglas() {
  try {
    const res = await fetch("/api/reglas");
    const data = await res.json();
    if (!res.ok) {
      lote.reglaFecha.textContent = data.error || "No se pudieron leer las reglas.";
      return;
    }
    lote.reglaFecha.textContent =
      data.regla_fecha || `La fecha no puede tener ${data.meses_maximos} meses o más.`;
    lote.formatos.replaceChildren();
    for (const formato of data.formatos || []) lote.formatos.appendChild(el("li", "", formato));
  } catch {
    lote.reglaFecha.textContent = "No se pudieron leer las reglas.";
  }
}

function limpiarResultadoLote() {
  lote.error.hidden = true;
  lote.resumen.hidden = true;
  lote.resumen.replaceChildren();
  lote.tablaWrap.hidden = true;
  lote.cuerpo.replaceChildren();
  lote.download.hidden = true;
}

function mostrarErrorLote(mensaje) {
  lote.error.hidden = false;
  lote.errorText.textContent = mensaje;
}

function pintarResumen(resultado) {
  const datos = [
    [resultado.leidos, "leídos"],
    [resultado.con_observaciones, "con observaciones"],
    [resultado.sin_observaciones, "sin observaciones"],
    [resultado.no_leidos, "no se pudieron leer"],
  ];
  lote.resumen.hidden = false;
  lote.resumen.replaceChildren();
  for (const [valor, etiqueta] of datos) {
    const caja = el("div", "stat");
    caja.appendChild(el("strong", "", String(valor ?? 0)));
    caja.appendChild(el("span", "", etiqueta));
    lote.resumen.appendChild(caja);
  }

  const filas = resultado.filas || [];
  lote.cuerpo.replaceChildren();
  lote.tablaWrap.hidden = filas.length === 0;
  for (const fila of filas) {
    const tr = document.createElement("tr");
    fila.forEach((valor, indice) => {
      const td = document.createElement("td");
      const texto = valor === null || valor === undefined || valor === "" ? "" : String(valor);
      td.textContent = texto;
      if (COLUMNAS_SI_NO.has(indice)) td.className = texto === "NO" ? "no" : "si";
      tr.appendChild(td);
    });
    lote.cuerpo.appendChild(tr);
  }
}

function pintarEstado(estado) {
  if (estado.estado === "procesando") {
    const total = estado.total || 0;
    const hechos = estado.hechos || 0;
    const actual = estado.actual ? ` Leyendo ${estado.actual}.` : "";
    lote.progress.hidden = false;
    lote.progress.textContent = total ? `Procesando ${hechos} de ${total}.${actual}` : "Preparando la lectura…";
    return;
  }

  lote.progress.hidden = true;
  lote.refresh.disabled = false;
  lote.run.disabled = false;
  if (loteTimer) {
    clearInterval(loteTimer);
    loteTimer = null;
  }
  if (estado.estado === "error") {
    mostrarErrorLote(estado.error || "No se pudo generar el informe.");
    return;
  }
  if (estado.estado === "listo" && estado.resultado) {
    pintarResumen(estado.resultado);
    if (estado.resultado.descarga) {
      lote.download.hidden = false;
      lote.download.href = estado.resultado.descarga;
      lote.download.textContent = "Descargar Excel";
    }
  }
}

async function consultarProceso() {
  try {
    const res = await fetch("/api/procesar");
    pintarEstado(await res.json());
  } catch {
    if (loteTimer) {
      clearInterval(loteTimer);
      loteTimer = null;
    }
    lote.run.disabled = false;
    lote.refresh.disabled = false;
    mostrarErrorLote("Se perdió la conexión mientras se leía la carpeta.");
  }
}

async function procesarCarpeta() {
  limpiarResultadoLote();
  lote.run.disabled = true;
  lote.refresh.disabled = true;
  lote.progress.hidden = false;
  lote.progress.textContent = "Iniciando la lectura…";
  try {
    const res = await fetch("/api/procesar", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "No se pudo iniciar la lectura.");
    if (loteTimer) clearInterval(loteTimer);
    loteTimer = setInterval(consultarProceso, 1000);
    consultarProceso();
  } catch (error) {
    lote.run.disabled = false;
    lote.refresh.disabled = false;
    lote.progress.hidden = true;
    mostrarErrorLote(error.message);
  }
}

async function reanudarSiHaceFalta() {
  try {
    const res = await fetch("/api/procesar");
    const estado = await res.json();
    if (estado.estado === "procesando") {
      lote.run.disabled = true;
      lote.refresh.disabled = true;
      loteTimer = setInterval(consultarProceso, 1000);
    }
    if (estado.estado === "procesando" || estado.estado === "listo" || estado.estado === "error") {
      pintarEstado(estado);
    }
  } catch {
    /* el servidor todavía puede estar arrancando */
  }
}

lote.run.addEventListener("click", procesarCarpeta);
lote.refresh.addEventListener("click", cargarEntrada);
cargarEntrada();
cargarReglas();
reanudarSiHaceFalta();
