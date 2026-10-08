// =====================================================================
// Analizador de Cheques - Frontend
// Consulta al backend cada pocos segundos y muestra los cheques nuevos.
// =====================================================================

const API = "/api/v1";
const INTERVALO_ACTUALIZACION_MS = 3000;

let resultados = [];
let idsConocidos = new Set();
let idSeleccionado = null;
let primeraCarga = true;

const $ = (id) => document.getElementById(id);

const ETIQUETAS_CAMPOS = {
  banco: "Banco",
  numero_cheque: "N° de cheque",
  cuenta: "Cuenta",
  ciudad: "Ciudad",
  fecha: "Fecha",
  beneficiario: "Beneficiario",
  monto: "Monto",
  monto_letras: "Monto en letras",
  monto_letras_valor: "Letras → número",
  validacion_monto: "Validación",
  concepto: "Concepto",
  linea_micr: "Línea MICR",
};

// ---------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------
function escapar(texto) {
  const div = document.createElement("div");
  div.textContent = texto ?? "";
  return div.innerHTML;
}

function celda(valor) {
  return valor ? escapar(valor) : '<span class="sin-dato">—</span>';
}

function formatearMonto(valor) {
  if (!valor) return '<span class="sin-dato">—</span>';
  return Number(valor).toLocaleString("es-EC", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function colorConfianza(porcentaje) {
  if (porcentaje >= 85) return "#1e8e3e";
  if (porcentaje >= 65) return "#f0a500";
  return "#c0392b";
}

function barraConfianza(valor) {
  const porcentaje = Math.round((valor || 0) * 100);
  return `<span class="barra-confianza"><div style="width:${porcentaje}%;background:${colorConfianza(porcentaje)}"></div></span>${porcentaje}%`;
}

function etiquetaValidacion(valor) {
  const clases = { "COINCIDE": "ok", "NO COINCIDE": "error" };
  return `<span class="etiqueta ${clases[valor] || "neutra"}">${escapar(valor || "SIN VERIFICAR")}</span>`;
}

// ---------------------------------------------------------------------
// Renderizado
// ---------------------------------------------------------------------
function renderizarResumen() {
  const validos = resultados.filter((r) => r.estado === "OK");
  const verificados = validos.filter((r) => r.campos.validacion_monto === "COINCIDE").length;
  const aRevisar = resultados.filter((r) => r.requiere_revision || r.estado === "ERROR").length;
  const confianza = validos.length
    ? validos.reduce((suma, r) => suma + (r.confianza_general || 0), 0) / validos.length
    : 0;

  $("total-cheques").textContent = resultados.length;
  $("montos-ok").textContent = `${verificados} / ${validos.length}`;
  $("requieren-revision").textContent = aRevisar;
  $("confianza-promedio").textContent = `${Math.round(confianza * 100)}%`;
}

function filaHtml(r, esNueva) {
  const c = r.campos || {};
  const clases = [r.id === idSeleccionado ? "seleccionada" : "", esNueva ? "nueva" : ""].join(" ");
  if (r.estado === "ERROR") {
    return `<tr data-id="${r.id}" class="${clases}">
      <td>${r.id}</td><td>${escapar(r.archivo)}</td>
      <td colspan="10"><span class="etiqueta error">ERROR</span> ${escapar(r.error)}</td></tr>`;
  }
  const revision = r.requiere_revision
    ? '<span class="etiqueta error">Revisar</span>'
    : '<span class="etiqueta ok">OK</span>';
  return `<tr data-id="${r.id}" class="${clases}">
    <td>${r.id}</td>
    <td>${escapar(r.archivo)}</td>
    <td>${celda(c.banco)}</td>
    <td>${celda(c.numero_cheque)}</td>
    <td>${celda(c.cuenta)}</td>
    <td>${celda(c.fecha)}</td>
    <td>${celda(c.beneficiario)}</td>
    <td class="derecha monto">${formatearMonto(c.monto)}</td>
    <td class="letras">${celda(c.monto_letras)}</td>
    <td>${etiquetaValidacion(c.validacion_monto)}</td>
    <td>${barraConfianza(r.confianza_general)}</td>
    <td>${revision}</td>
  </tr>`;
}

function coincideConFiltro(r, filtro) {
  if (!filtro) return true;
  const texto = [r.archivo, ...Object.values(r.campos || {})].join(" ").toLowerCase();
  return texto.includes(filtro);
}

function renderizarTabla(nuevos) {
  const filtro = $("filtro").value.trim().toLowerCase();
  const visibles = resultados.filter((r) => coincideConFiltro(r, filtro));
  $("cuerpo-tabla").innerHTML = visibles.length
    ? visibles.map((r) => filaHtml(r, nuevos.has(r.id))).join("")
    : `<tr><td colspan="12" class="vacio">${resultados.length ? "Sin coincidencias para el filtro." : "Coloque imágenes o PDF de cheques en la carpeta para analizarlos."}</td></tr>`;
}

function mostrarDetalle(id) {
  const r = resultados.find((x) => x.id === id);
  if (!r) return;
  idSeleccionado = id;
  document.querySelectorAll("#cuerpo-tabla tr").forEach((tr) =>
    tr.classList.toggle("seleccionada", Number(tr.dataset.id) === id));

  $("detalle").classList.remove("oculto");
  $("detalle-titulo").textContent = `#${r.id} · ${r.archivo}`;
  $("detalle-imagen").src = r.vista ? `${API}/vistas/${r.vista}` : "";
  $("detalle-imagen").style.display = r.vista ? "block" : "none";

  const avisos = r.avisos || [];
  $("detalle-avisos").innerHTML = avisos.map((a) => `<li>${escapar(a)}</li>`).join("");
  $("detalle-avisos").style.display = avisos.length ? "block" : "none";

  const confianzas = r.confianzas || {};
  $("detalle-campos").innerHTML = Object.entries(ETIQUETAS_CAMPOS).map(([clave, etiqueta]) => {
    const valor = (r.campos || {})[clave];
    let contenido = clave === "validacion_monto" ? etiquetaValidacion(valor)
      : clave === "monto" ? formatearMonto(valor) : celda(valor);
    if (confianzas[clave]) contenido += `<small>Confianza OCR: ${Math.round(confianzas[clave] * 100)}%</small>`;
    return `<dt>${etiqueta}</dt><dd>${contenido}</dd>`;
  }).join("") + `<dt>Tiempo</dt><dd>${r.tiempo_ms} ms</dd><dt>Procesado</dt><dd>${escapar(r.fecha_proceso)}</dd>`;

  $("detalle-texto").textContent = r.texto_completo || r.error || "";
}

function renderizarEstado(estado, carpeta) {
  $("ruta-carpeta").textContent = carpeta;
  const caja = $("estado");
  if (estado.procesando) {
    caja.classList.add("activo");
    caja.textContent = `Analizando ${estado.procesando} (${estado.pendientes} pendientes)`;
  } else {
    caja.classList.remove("activo");
    caja.textContent = `En espera · última revisión ${estado.ultima_revision || "-"}`;
  }
}

// ---------------------------------------------------------------------
// Comunicación con el backend
// ---------------------------------------------------------------------
async function actualizar() {
  try {
    const respuesta = await fetch(`${API}/cheques`);
    const datos = await respuesta.json();

    const nuevos = new Set(
      primeraCarga ? [] : datos.resultados.filter((r) => !idsConocidos.has(r.id)).map((r) => r.id));
    const huboCambios = primeraCarga || nuevos.size > 0 || datos.resultados.length !== resultados.length;

    resultados = datos.resultados;
    idsConocidos = new Set(resultados.map((r) => r.id));
    primeraCarga = false;

    renderizarEstado(datos.estado, datos.carpeta);
    if (huboCambios) {
      renderizarResumen();
      renderizarTabla(nuevos);
    }
  } catch (error) {
    $("estado").textContent = "Sin conexión con el servidor";
  }
}

async function subirArchivos(archivos) {
  if (!archivos.length) return;
  const formulario = new FormData();
  [...archivos].forEach((a) => formulario.append("archivos", a));
  await fetch(`${API}/cheques/archivos`, { method: "POST", body: formulario });
  actualizar();
}

// ---------------------------------------------------------------------
// Eventos
// ---------------------------------------------------------------------
$("cuerpo-tabla").addEventListener("click", (e) => {
  const fila = e.target.closest("tr[data-id]");
  if (fila) mostrarDetalle(Number(fila.dataset.id));
});
$("btn-cerrar").addEventListener("click", () => {
  $("detalle").classList.add("oculto");
  idSeleccionado = null;
  renderizarTabla(new Set());
});
$("filtro").addEventListener("input", () => renderizarTabla(new Set()));
$("subir").addEventListener("change", (e) => subirArchivos(e.target.files));
$("btn-procesar").addEventListener("click", async () => {
  await fetch(`${API}/procesamientos`, { method: "POST" });
  actualizar();
});
$("btn-reiniciar").addEventListener("click", async () => {
  if (!confirm("Se borrarán los resultados y se volverán a analizar todos los cheques. ¿Continuar?")) return;
  await fetch(`${API}/cheques`, { method: "DELETE" });
  primeraCarga = true;
  idSeleccionado = null;
  $("detalle").classList.add("oculto");
  actualizar();
});

actualizar();
setInterval(actualizar, INTERVALO_ACTUALIZACION_MS);
