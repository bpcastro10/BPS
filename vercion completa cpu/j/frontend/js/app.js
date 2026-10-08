/**
 * Lógica de la interfaz: muestra el reporte, consulta periódicamente si hay cheques nuevos
 * y permite revisar / corregir cada cheque.
 */

const FIELDS = [
  { key: "banco", label: "Banco", color: "#2563eb" },
  { key: "numero_cheque", label: "N° Cheque", color: "#dc2626" },
  { key: "ciudad", label: "Ciudad", color: "#0891b2" },
  { key: "fecha", label: "Fecha", color: "#0d9488", type: "date" },
  { key: "beneficiario", label: "Beneficiario", color: "#7c3aed" },
  { key: "monto", label: "Monto", color: "#16a34a" },
  { key: "monto_letras", label: "Monto en letras", color: "#ea580c", multiline: true },
  { key: "moneda", label: "Moneda", color: "#64748b", noBox: true },
  { key: "cuenta", label: "Cuenta", color: "#9333ea" },
  { key: "codigo_ruta", label: "Código de ruta", color: "#475569", readonly: true },
  { key: "linea_micr", label: "Línea MICR", color: "#334155", readonly: true },
  { key: "concepto", label: "Concepto", color: "#ca8a04" },
  { key: "firma", label: "Firma", color: "#be185d", readonly: true },
];

const SOURCE_LABELS = {
  ocr: "OCR", micr: "MICR", trocr: "IA manuscritos", vlm: "IA visión", imagen: "Análisis imagen",
  calculado: "Calculado", manual: "Manual",
};

const POLL_MS = 2500;
const PAGE_SIZE = 50;

const state = {
  page: 1,
  totalPages: 1,
  version: null,
  knownIds: new Set(),
  firstLoad: true,
  current: null,
};

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- utilidades
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function money(value, currency) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  const symbol = !currency || currency === "USD" || currency === "PESOS" ? "$" : `${currency} `;
  return symbol + n.toLocaleString("es-EC", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatDate(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

function confColor(c) {
  if (c >= 0.9) return "#1f9d55";
  if (c >= 0.7) return "#d69e2e";
  return "#e53e3e";
}

function confBar(c) {
  const pct = Math.round((c || 0) * 100);
  return `<div class="conf"><div class="conf-bar"><span style="width:${pct}%;background:${confColor(c)}"></span></div><small>${pct}%</small></div>`;
}

function fieldValue(check, key) {
  return check.fields?.[key]?.value ?? null;
}

function cell(check, key, formatter = (v) => escapeHtml(v)) {
  const f = check.fields?.[key];
  if (!f || !f.value) return '<span class="muted">—</span>';
  const hw = f.writing === "manuscrito" ? '<span class="hw-mark" title="Escrito a mano">✍</span>' : "";
  return formatter(f.value) + hw;
}

function toast(message, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = message;
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

function currentFilters() {
  const [sortBy, order] = $("sortBy").value.split(":");
  return { search: $("search").value.trim(), status: $("statusFilter").value, sortBy, order };
}

// ---------------------------------------------------------------- reporte
async function loadChecks() {
  const filters = currentFilters();
  const data = await Api.listChecks({ ...filters, page: state.page, pageSize: PAGE_SIZE });
  state.totalPages = data.total_pages;
  renderTable(data.items);
  $("resultInfo").textContent = `${data.total} cheque(s)`;
  $("pageInfo").textContent = `Página ${data.page} de ${data.total_pages}`;
  $("prevPage").disabled = data.page <= 1;
  $("nextPage").disabled = data.page >= data.total_pages;
  $("pager").style.display = data.total_pages > 1 ? "flex" : "none";
}

function renderTable(items) {
  $("emptyState").style.display = items.length ? "none" : "block";
  const offset = (state.page - 1) * PAGE_SIZE;
  $("checksBody").innerHTML = items.map((c, i) => {
    const isNew = !state.firstLoad && !state.knownIds.has(c.id);
    const currency = fieldValue(c, "moneda");
    const mismatch = c.amount_match === false
      ? `<span class="mismatch" title="El monto en letras no coincide">≠ letras: ${money(c.amount_words_value, currency)}</span>` : "";
    const firma = fieldValue(c, "firma");
    return `
      <tr data-id="${c.id}" class="${isNew ? "is-new" : ""}">
        <td class="muted">${offset + i + 1}</td>
        <td>
          <img class="thumb" loading="lazy" src="${Api.imageUrl(c)}" alt="" onerror="this.style.visibility='hidden'">
          <div class="file-name" title="${escapeHtml(c.file_name)}">${escapeHtml(c.file_name)}</div>
        </td>
        <td>${cell(c, "banco")}</td>
        <td>${cell(c, "numero_cheque")}</td>
        <td>${cell(c, "fecha", formatDate)}</td>
        <td>${cell(c, "ciudad")}</td>
        <td><strong>${cell(c, "beneficiario")}</strong></td>
        <td class="num"><span class="amount">${cell(c, "monto", (v) => money(v, currency))}</span>${mismatch}</td>
        <td class="words">${cell(c, "monto_letras")}</td>
        <td>${cell(c, "cuenta")}</td>
        <td>${firma === "Sí" ? "✅ Sí" : firma === "No" ? "❌ No" : "—"}</td>
        <td>${confBar(c.overall_confidence)}</td>
        <td><span class="badge ${c.status}">${c.status}</span></td>
      </tr>`;
  }).join("");
  if (!state.firstLoad) {
    items.filter((c) => !state.knownIds.has(c.id)).forEach((c) => toast(`Nuevo cheque analizado: ${c.file_name}`, "ok"));
  }
  items.forEach((c) => state.knownIds.add(c.id));
  state.firstLoad = false;
}

function renderSummary(s) {
  $("statTotal").textContent = s.total;
  $("statOk").textContent = s.completos;
  $("statReview").textContent = s.revisar;
  $("statError").textContent = s.errores;
  $("inputDir").textContent = s.input_dir;

  const status = $("engineStatus");
  if (!s.engine_ready) {
    status.className = "engine-status busy";
    $("engineText").textContent = "Cargando motor OCR…";
  } else if (s.queue_size > 0) {
    status.className = "engine-status busy";
    $("engineText").textContent = `Procesando ${s.current_file || ""} · en cola: ${s.queue_size}`;
  } else {
    status.className = "engine-status idle";
    const extras = [s.handwriting_model ? "IA manuscritos" : null, s.vlm_model ? `IA visión (${s.vlm_model})` : null].filter(Boolean);
    $("engineText").textContent = `Vigilando carpeta${extras.length ? " · " + extras.join(" · ") : ""}`;
  }
}

async function poll() {
  try {
    const summary = await Api.summary();
    renderSummary(summary);
    if (summary.version !== state.version) {
      state.version = summary.version;
      await loadChecks();
    }
  } catch (err) {
    $("engineStatus").className = "engine-status offline";
    $("engineText").textContent = "Sin conexión con el backend";
  } finally {
    setTimeout(poll, POLL_MS);
  }
}

// ---------------------------------------------------------------- detalle
async function openDetail(id) {
  const check = await Api.getCheck(id);
  state.current = check;
  $("detailTitle").textContent = check.file_name;
  $("detailMeta").innerHTML =
    `<span class="badge ${check.status}">${check.status}</span> · Confianza ${Math.round(check.overall_confidence * 100)}%` +
    ` · ${check.processing_ms} ms · ${check.processed_at.replace("T", " ")}${check.edited ? " · corregido manualmente" : ""}`;
  $("detailImage").src = Api.imageUrl(check);
  $("rawText").textContent = check.raw_text || "(sin texto)";

  const obs = check.observations.length
    ? check.observations.map((o) => `<div class="obs">⚠ ${escapeHtml(o)}</div>`).join("")
    : '<div class="obs ok">✔ Todos los datos clave se extrajeron y validaron correctamente.</div>';
  $("observations").innerHTML = obs;

  renderBoxes(check);
  renderFields(check);
  $("detailModal").hidden = false;
}

function renderBoxes(check) {
  $("overlay").innerHTML = FIELDS.filter((f) => !f.noBox && check.fields[f.key]?.bbox && check.fields[f.key]?.value)
    .map((f) => {
      const [x0, y0, x1, y1] = check.fields[f.key].bbox;
      return `<div class="box" data-key="${f.key}" style="left:${x0 * 100}%;top:${y0 * 100}%;width:${(x1 - x0) * 100}%;height:${(y1 - y0) * 100}%;border-color:${f.color}">
                <span style="background:${f.color}">${f.label}</span></div>`;
    }).join("");
}

function renderFields(check) {
  $("fieldsContainer").innerHTML = FIELDS.map((f) => {
    const data = check.fields[f.key] || {};
    const value = escapeHtml(data.value ?? "");
    const input = f.multiline
      ? `<textarea name="${f.key}" rows="2">${value}</textarea>`
      : `<input name="${f.key}" type="${f.type || "text"}" value="${value}" ${f.readonly ? "readonly" : ""}>`;
    const words = f.key === "monto_letras" && check.amount_words_value
      ? `<span>= ${money(check.amount_words_value)}</span>${check.amount_match === false ? ' <span class="mismatch">no coincide</span>' : check.amount_match ? " ✔" : ""}` : "";
    const meta = data.value
      ? `${confBar(data.confidence)} <span class="tag ${data.source === "manual" ? "manual" : ""}">${SOURCE_LABELS[data.source] || data.source}</span>
         ${data.writing ? `<span class="tag ${data.writing}">${data.writing}</span>` : ""} ${words}`
      : '<span>No detectado</span>';
    return `
      <div class="field-row" data-key="${f.key}">
        <label><i style="background:${f.color}"></i>${f.label}</label>
        ${input}
        <div class="field-meta">${meta}</div>
      </div>`;
  }).join("");
}

async function saveCorrections(event) {
  event.preventDefault();
  const check = state.current;
  const form = new FormData($("detailForm"));
  const changes = {};
  FIELDS.filter((f) => !f.readonly).forEach((f) => {
    const value = (form.get(f.key) ?? "").toString().trim();
    const original = (check.fields[f.key]?.value ?? "").toString().trim();
    if (value !== original) changes[f.key] = value;
  });
  if (!Object.keys(changes).length && check.status === "COMPLETO") {
    toast("No hay cambios para guardar");
    return;
  }
  try {
    changes.status = "COMPLETO";
    await Api.updateCheck(check.id, changes);
    toast("Correcciones guardadas", "ok");
    closeDetail();
  } catch (err) {
    toast(err.message, "err");
  }
}

function closeDetail() {
  $("detailModal").hidden = true;
  state.current = null;
}

// ---------------------------------------------------------------- eventos
function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function bindEvents() {
  const reload = () => { state.page = 1; loadChecks().catch((e) => toast(e.message, "err")); };
  $("search").addEventListener("input", debounce(reload, 300));
  $("statusFilter").addEventListener("change", reload);
  $("sortBy").addEventListener("change", reload);
  $("prevPage").addEventListener("click", () => { state.page--; loadChecks(); });
  $("nextPage").addEventListener("click", () => { state.page++; loadChecks(); });

  $("btnScan").addEventListener("click", async () => {
    try {
      const r = await Api.scanFolder();
      toast(r.enqueued ? `${r.enqueued} archivo(s) nuevo(s) en cola` : "No hay archivos nuevos en la carpeta");
    } catch (err) { toast(err.message, "err"); }
  });

  $("btnExcel").addEventListener("click", () => {
    const { search, status, sortBy, order } = currentFilters();
    window.location.href = Api.excelUrl({ search, status, sortBy, order });
  });

  $("checksBody").addEventListener("click", (e) => {
    const row = e.target.closest("tr[data-id]");
    if (row) openDetail(Number(row.dataset.id)).catch((err) => toast(err.message, "err"));
  });

  document.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", closeDetail));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("detailModal").hidden) closeDetail(); });
  $("toggleBoxes").addEventListener("change", (e) => $("overlay").classList.toggle("hidden", !e.target.checked));
  $("detailForm").addEventListener("submit", saveCorrections);

  $("fieldsContainer").addEventListener("focusin", (e) => {
    const key = e.target.closest(".field-row")?.dataset.key;
    document.querySelectorAll(".box").forEach((b) => b.classList.toggle("active", b.dataset.key === key));
  });

  $("btnReprocess").addEventListener("click", async () => {
    try {
      const r = await Api.reprocessCheck(state.current.id);
      toast(r.enqueued ? "Cheque enviado a reanálisis" : "No se encontró el archivo original", r.enqueued ? "ok" : "err");
      closeDetail();
    } catch (err) { toast(err.message, "err"); }
  });

  $("btnDelete").addEventListener("click", async () => {
    if (!confirm("¿Eliminar este cheque del reporte? (no se borra el archivo original)")) return;
    try {
      await Api.deleteCheck(state.current.id);
      toast("Cheque eliminado del reporte");
      closeDetail();
    } catch (err) { toast(err.message, "err"); }
  });
}

bindEvents();
poll();
