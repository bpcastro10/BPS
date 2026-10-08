"""
Extrae los campos de un cheque a partir de las cajas de texto del OCR.

Se usan reglas simples y explicables:
  1. Etiquetas impresas ("PÁGUESE A LA ORDEN DE", "LA SUMA DE", "CTA."...) -> el valor
     es lo que está a su derecha o en el renglón de abajo.
  2. Expresiones regulares para fechas, montos y números.
  3. Posición en el cheque (arriba-derecha = número/monto, abajo = línea MICR).
  4. Validación cruzada: el monto en números se compara con el monto en letras.
"""
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from difflib import get_close_matches

from numeros_letras import contar_palabras_numericas, letras_a_numero, texto_normalizado
from ocr_motor import Caja, agrupar_en_renglones

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7,
    "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}

# Clave: texto sin espacios en minúsculas -> nombre oficial a mostrar
BANCOS_CONOCIDOS = {
    "pichincha": "Banco Pichincha", "guayaquil": "Banco de Guayaquil", "pacifico": "Banco del Pacífico",
    "produbanco": "Produbanco", "bolivariano": "Banco Bolivariano", "internacional": "Banco Internacional",
    "austro": "Banco del Austro", "machala": "Banco de Machala", "loja": "Banco de Loja",
    "procredit": "Banco ProCredit", "solidario": "Banco Solidario", "amazonas": "Banco Amazonas",
    "bbva": "BBVA", "santander": "Banco Santander", "bancolombia": "Bancolombia",
    "davivienda": "Davivienda", "banamex": "Banamex", "banorte": "Banorte", "hsbc": "HSBC",
    "citibank": "Citibank", "scotiabank": "Scotiabank", "interbank": "Interbank",
    "galicia": "Banco Galicia", "bancoestado": "BancoEstado", "chase": "Chase",
    "wellsfargo": "Wells Fargo", "bankofamerica": "Bank of America", "banesco": "Banesco",
    "mercantil": "Banco Mercantil", "banreservas": "Banreservas",
}

# Ciudades frecuentes: corrigen lecturas manuscritas aproximadas ("Guayagwil" -> "Guayaquil")
CIUDADES = [
    "Quito", "Guayaquil", "Cuenca", "Ambato", "Machala", "Manta", "Portoviejo", "Loja", "Riobamba",
    "Ibarra", "Esmeraldas", "Latacunga", "Santo Domingo", "Quevedo", "Milagro", "Babahoyo",
    "Tulcán", "Otavalo", "Salinas", "Lima", "Bogotá", "Medellín", "Cali", "Caracas", "Santiago",
    "Buenos Aires", "Ciudad de México", "Panamá", "San José", "La Paz", "Asunción", "Montevideo",
]

# Letras que el OCR suele confundir con dígitos dentro de fechas y montos
LETRAS_A_DIGITOS = str.maketrans("oOdDiIlL|sSzZbgqa", "00001111155226999")
RE_POSIBLE_FECHA = re.compile(r"\d[\doOdDiIlL|sSzZbgqa]{0,3}(?:\s*[/\-.]\s*[\doOdDiIlL|sSzZbgqa]{1,4}){2}")

ETIQUETAS_BENEFICIARIO = [
    r"pa[gq]u?[eéa]?s[eé]\s*a\s*la\s*orden\s*de", r"a\s*la\s*orden\s*de", r"pa[gq]u?[eéa]?s[eé]\s*a",
    r"pay\s*to\s*the\s*order\s*of", r"beneficiario", r"orden\s*de",
    r"pagu?esealaordende", r"pagueseala",
]
ETIQUETAS_LETRAS = [
    r"la\s*suma\s*de", r"la\s*cantidad\s*de", r"the\s*sum\s*of", r"\bson\s*:?",
    r"lasumade", r"lacantidadde",
]
ETIQUETAS_CONCEPTO = [
    r"por\s*concepto\s*de", r"concepto\s*:?", r"memo\s*:?", r"motivo\s*:?", r"concepto",
]

RE_FECHA_DMA = re.compile(r"(?<!\d)(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4}|\d{2})(?!\d)")
RE_FECHA_AMD = re.compile(r"(?<!\d)(\d{4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})(?!\d)")
RE_FECHA_TEXTO = re.compile(r"(?<!\d)(\d{1,2})\s*(?:de\s*)?([a-z]{3,10})\.?\s*(?:de[l]?\s*)?(\d{4})(?!\d)")
RE_MONTO = re.compile(r"\d{1,3}(?:[.,\s]\d{3})+(?:[.,]\d{1,2})?|\d+[.,]\d{1,2}|\d+")
RE_SIMBOLO_MONEDA = re.compile(r"us\s*\$|\$|\busd\b|\bs/\.?|\bbs\.|₡|€")


# --------------------------------------------------------------------------- #
# Utilidades de texto
# --------------------------------------------------------------------------- #
def norm(texto: str) -> str:
    """Minúsculas y sin tildes conservando la MISMA longitud (para poder recortar el original)."""
    return "".join(
        unicodedata.normalize("NFD", c)[0].lower() if c.isalpha() else c.lower()
        for c in texto
    )


def limpiar(texto: str) -> str:
    texto = re.sub(r"[*_=#~|]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip(" .,:;-")


def separar_nombre(texto: str) -> str:
    """'Juan CarlosPerez' -> 'Juan Carlos Perez'; 'AndinaS.A.' -> 'Andina S.A.'"""
    return re.sub(r"(?<=[a-záéíóúñ])(?=[A-ZÁÉÍÓÚÑ])", " ", texto)


def corregir_ciudad(texto: str) -> str:
    ciudades_norm = {norm(c): c for c in CIUDADES}
    parecida = get_close_matches(norm(texto), list(ciudades_norm), n=1, cutoff=0.68)
    return ciudades_norm[parecida[0]] if parecida else texto.title()


def corregir_digitos(texto: str) -> str:
    """En trozos con forma de fecha ('28/0a/2026') cambia letras confundidas por dígitos."""
    def reemplazo(m):
        trozo = m.group(0)
        return trozo.translate(LETRAS_A_DIGITOS) if sum(c.isdigit() for c in trozo) >= 4 else trozo
    return RE_POSIBLE_FECHA.sub(reemplazo, texto)


def texto_renglon(renglon: list[Caja]) -> str:
    return " ".join(c.texto for c in renglon)


def confianza(cajas: list[Caja]) -> float:
    return round(sum(c.confianza for c in cajas) / len(cajas), 3) if cajas else 0.0


def parsear_monto(texto: str) -> Decimal | None:
    """'1.500,00' / '1,500.00' / '***1500.5' -> Decimal. Decide el separador decimal por contexto."""
    numeros = RE_MONTO.findall(texto.replace("O", "0").replace("o", "0"))
    if not numeros:
        return None
    crudo = max(numeros, key=len).replace(" ", "")
    if "," in crudo and "." in crudo:
        decimal_sep = "," if crudo.rfind(",") > crudo.rfind(".") else "."
    elif re.search(r"[.,]\d{1,2}$", crudo):
        decimal_sep = crudo[-3] if crudo[-3] in ".," else crudo[-2]
    else:
        decimal_sep = None
    if decimal_sep:
        entero, _, dec = crudo.rpartition(decimal_sep)
        crudo = re.sub(r"[.,]", "", entero) + "." + dec
    else:
        crudo = re.sub(r"[.,]", "", crudo)
    try:
        return Decimal(crudo).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def es_parecido_a_fecha(texto: str) -> bool:
    t = norm(texto)
    return bool(RE_FECHA_DMA.search(t) or RE_FECHA_AMD.search(t) or RE_FECHA_TEXTO.search(t))


# --------------------------------------------------------------------------- #
# Búsqueda por etiqueta
# --------------------------------------------------------------------------- #
def valor_por_etiqueta(renglones, patrones, corte_derecha=None):
    """
    Busca una etiqueta impresa y devuelve (texto_valor, cajas_usadas, caja_etiqueta).
    El valor es: el resto de la misma caja -> las cajas a la derecha -> el renglón de abajo.
    `corte_derecha(caja)` permite detenerse antes de cajas que no pertenecen al valor.
    """
    for i, renglon in enumerate(renglones):
        for j, caja in enumerate(renglon):
            texto_n = norm(caja.texto)
            coincidencia = next((m for p in patrones if (m := re.search(p, texto_n))), None)
            if not coincidencia:
                continue

            partes, usadas = [], []
            resto = limpiar(caja.texto[coincidencia.end():])
            if len(resto) > 1:
                partes.append(resto)
                usadas.append(caja)
            for vecina in renglon[j + 1:]:
                if corte_derecha and corte_derecha(vecina):
                    break
                partes.append(vecina.texto)
                usadas.append(vecina)

            if not partes and i + 1 < len(renglones):
                abajo = [c for c in renglones[i + 1]
                         if c.cy - caja.cy < 0.15 and c.x1 > caja.x0
                         and not (corte_derecha and corte_derecha(c))]
                partes = [c.texto for c in abajo]
                usadas = abajo

            valor = limpiar(" ".join(partes))
            if valor:
                return valor, usadas, caja
    return None, [], None


def es_caja_de_monto(caja: Caja) -> bool:
    t = norm(caja.texto)
    return bool(RE_SIMBOLO_MONEDA.search(t)) or bool(re.fullmatch(r"[\s*#$]*[\d.,\s]+[\s*#]*", t) and re.search(r"\d", t))


# --------------------------------------------------------------------------- #
# Extractores de cada campo
# --------------------------------------------------------------------------- #
def extraer_banco(cajas):
    candidatos = []
    for caja in cajas:
        t = re.sub(r"\s", "", norm(caja.texto))
        conocido = next((nombre for clave, nombre in BANCOS_CONOCIDOS.items() if clave in t), None)
        if "banco" in t or "bank" in t or conocido:
            # Preferir: dice "banco" > banco conocido > lo que está más arriba y es más grande
            prioridad = ("banco" in t or "bank" in t, conocido is not None, -caja.cy + caja.alto * 3)
            candidatos.append((prioridad, conocido, caja))
    if not candidatos:
        return None, []
    _, conocido, caja = max(candidatos, key=lambda x: x[0])
    texto = re.sub(r"(?i)\s*cheque.*$", "", limpiar(caja.texto))  # "BANCO X CHEQUE No..." -> "BANCO X"
    return conocido or separar_nombre(texto), [caja]


def extraer_fecha(cajas, renglones):
    """Devuelve (fecha_dd/mm/aaaa, ciudad, cajas)."""
    for renglon in renglones:
        for k, caja in enumerate(renglon):
            # Se une la caja con sus vecinas para cubrir fechas cortadas en varias cajas
            texto = corregir_digitos(" ".join(c.texto for c in renglon[k:k + 3]))
            t = norm(texto)
            fecha, inicio = None, None

            if m := RE_FECHA_AMD.search(t):
                a, mes, d = int(m[1]), int(m[2]), int(m[3])
                fecha, inicio = (d, mes, a), m.start()
            elif m := RE_FECHA_DMA.search(t):
                d, mes, a = int(m[1]), int(m[2]), int(m[3])
                fecha, inicio = (d, mes, a), m.start()
            elif m := re.search(r"(?<!\d)(\d{1,2})[1li](\d{1,2})[/\-.](\d{4}|\d{2})(?!\d)", t):
                # El OCR a veces lee la barra de la fecha como "1": 15/03/2026 -> 15103/2026
                d, mes, a = int(m[1]), int(m[2]), int(m[3])
                fecha, inicio = (d, mes, a), m.start()
            elif m := RE_FECHA_TEXTO.search(t):
                nombre = get_close_matches(m[2], list(MESES), n=1, cutoff=0.7)
                if nombre:
                    fecha, inicio = (int(m[1]), MESES[nombre[0]], int(m[3])), m.start()

            if not fecha:
                continue
            d, mes, a = fecha
            if a < 100:
                a += 2000
            if not (1 <= d <= 31 and 1 <= mes <= 12 and 1950 <= a <= 2100):
                continue

            ciudad = limpiar(re.sub(r"(?i)lugar\s*y\s*fecha|fecha|date", "", texto[:inicio]))
            if k > 0 and not ciudad:
                ciudad = limpiar(renglon[k - 1].texto)
            ciudad = re.sub(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ .]", "", ciudad or "").strip()
            ciudad = re.sub(r"(?i)^(lugar|echa|fecha|date)\s*", "", ciudad).strip()
            ciudad = corregir_ciudad(ciudad) if re.fullmatch(r"[A-Za-zÁÉÍÓÚÑáéíóúñ .]{3,30}", ciudad or "") else None
            return f"{d:02d}/{mes:02d}/{a}", ciudad, renglon[k:k + 3]
    return None, None, []


def extraer_monto_letras(renglones):
    valor, usadas, _ = valor_por_etiqueta(renglones, ETIQUETAS_LETRAS)
    if not valor or contar_palabras_numericas(valor) == 0:
        # Sin etiqueta: el renglón con más palabras numéricas ("quinientos", "mil"...)
        mejor = max(renglones, key=lambda r: contar_palabras_numericas(texto_renglon(r)), default=[])
        if not mejor or contar_palabras_numericas(texto_renglon(mejor)) == 0:
            return None, None, []
        valor = limpiar(texto_renglon(mejor))
        valor = re.sub(r"(?i)^.*?(la\s*suma\s*de|son)\s*:?", "", valor).strip()
        usadas = mejor
    return texto_normalizado(valor), letras_a_numero(valor), usadas


def extraer_monto_numero(cajas, renglones, valor_esperado):
    """Busca el monto en números. Si hay monto en letras, prefiere el candidato que coincide."""
    candidatos = []
    for renglon in renglones:
        for j, caja in enumerate(renglon):
            t = norm(caja.texto)
            if es_parecido_a_fecha(caja.texto):
                continue
            texto = caja.texto
            tiene_simbolo = bool(RE_SIMBOLO_MONEDA.search(t))
            # "$" suelto: el número está en la caja siguiente
            if tiene_simbolo and not re.search(r"\d", t) and j + 1 < len(renglon):
                texto = renglon[j + 1].texto
            monto = parsear_monto(texto)
            if monto is None or monto <= 0:
                continue
            digitos = re.sub(r"\D", "", texto)
            tiene_decimales = bool(re.search(r"[.,]\d{2}\b", texto))
            if not tiene_simbolo and (len(digitos) > 9 or not tiene_decimales):
                continue  # descarta números de cuenta, cheque o MICR
            puntaje = (3 if tiene_simbolo else 0) + (2 if tiene_decimales else 0) + caja.cx
            if valor_esperado is not None and monto == valor_esperado:
                puntaje += 10
            candidatos.append((puntaje, monto, caja))
    if not candidatos:
        return None, []
    _, monto, caja = max(candidatos, key=lambda x: x[0])
    return monto, [caja]


def extraer_beneficiario(renglones):
    valor, usadas, _ = valor_por_etiqueta(renglones, ETIQUETAS_BENEFICIARIO, corte_derecha=es_caja_de_monto)
    if valor:
        # Si el monto quedó pegado al nombre ("JUAN PEREZ $1.500,00"), se recorta
        simbolo = RE_SIMBOLO_MONEDA.search(norm(valor))
        if simbolo:
            valor = valor[:simbolo.start()]
        valor = separar_nombre(limpiar(re.sub(r"[\d.,\s]+$", "", valor)))
    return (valor or None), usadas


def extraer_concepto(renglones):
    valor, usadas, _ = valor_por_etiqueta(renglones, ETIQUETAS_CONCEPTO)
    return valor, usadas


def extraer_micr(renglones):
    """Línea de caracteres magnéticos al pie del cheque (muchos dígitos, parte inferior)."""
    for renglon in reversed(renglones):
        texto = texto_renglon(renglon)
        if renglon[0].cy > 0.65 and len(re.sub(r"\D", "", texto)) >= 10:
            return limpiar(texto), re.findall(r"\d{3,}", texto), renglon
    return None, [], []


def extraer_numero_cheque(cajas, grupos_micr):
    for caja in cajas:
        t = norm(caja.texto)
        if m := re.search(r"(?:cheque|ch\.?|serie|n[o°º]\.?|nro\.?|num\.?)\s*[:#]?\s*(\d{3,10})\b", t):
            if caja.cy < 0.6:
                return m[1], [caja], "etiqueta"
    # Número aislado en la esquina superior derecha
    for caja in sorted(cajas, key=lambda c: (c.cy, -c.cx)):
        if caja.cy < 0.35 and caja.cx > 0.55 and re.fullmatch(r"[N°#º\s.:]*\d{4,10}", caja.texto.strip()):
            return re.sub(r"\D", "", caja.texto), [caja], "posicion"
    numeros = [g for g in grupos_micr if 4 <= len(g) <= 10]
    if numeros:
        return numeros[0], [], "micr"
    return None, [], None


def extraer_cuenta(cajas, grupos_micr):
    for caja in cajas:
        t = norm(caja.texto)
        if m := re.search(r"(?:cta|cuenta|account|acc)[^\d]{0,25}(\d[\d\-\s]{4,20}\d)", t):
            return re.sub(r"\s", "", m[1]), [caja]
    if grupos_micr:
        return max(grupos_micr, key=len), []
    return None, []


# --------------------------------------------------------------------------- #
# Función principal
# --------------------------------------------------------------------------- #
def extraer_campos(cajas: list[Caja]) -> dict:
    renglones = agrupar_en_renglones(cajas)

    banco, c_banco = extraer_banco(cajas)
    fecha, ciudad, c_fecha = extraer_fecha(cajas, renglones)
    letras, valor_letras, c_letras = extraer_monto_letras(renglones)
    monto, c_monto = extraer_monto_numero(cajas, renglones, valor_letras)
    beneficiario, c_benef = extraer_beneficiario(renglones)
    concepto, c_concepto = extraer_concepto(renglones)
    micr, grupos_micr, c_micr = extraer_micr(renglones)
    numero, c_numero, _ = extraer_numero_cheque(cajas, grupos_micr)
    cuenta, c_cuenta = extraer_cuenta(cajas, grupos_micr)

    if monto is None and valor_letras is not None:
        monto, c_monto = valor_letras, c_letras

    if monto is not None and valor_letras is not None:
        validacion = "COINCIDE" if monto == valor_letras else "NO COINCIDE"
    else:
        validacion = "SIN VERIFICAR"

    campos_clave = (banco, numero, fecha, beneficiario, monto)
    avisos = []
    if validacion == "NO COINCIDE":
        avisos.append("El monto en números no coincide con el monto en letras")
    if validacion == "SIN VERIFICAR":
        avisos.append("No se pudo cruzar el monto en números con el de letras")
    if sum(1 for v in campos_clave if v) < 3:
        avisos.append("Faltan campos clave (banco, número, fecha, beneficiario o monto)")
    if confianza(cajas) < 0.65:
        avisos.append("La lectura OCR tiene baja confianza (letra o imagen poco clara)")

    campos = {
        "banco": banco,
        "numero_cheque": numero,
        "cuenta": cuenta,
        "ciudad": ciudad,
        "fecha": fecha,
        "beneficiario": beneficiario,
        "monto": str(monto) if monto is not None else None,
        "monto_letras": letras,
        "monto_letras_valor": str(valor_letras) if valor_letras is not None else None,
        "validacion_monto": validacion,
        "concepto": concepto,
        "linea_micr": micr,
    }
    confianzas = {
        "banco": confianza(c_banco), "numero_cheque": confianza(c_numero),
        "cuenta": confianza(c_cuenta), "ciudad": confianza(c_fecha), "fecha": confianza(c_fecha),
        "beneficiario": confianza(c_benef), "monto": confianza(c_monto),
        "monto_letras": confianza(c_letras), "concepto": confianza(c_concepto),
        "linea_micr": confianza(c_micr),
    }
    return {
        "campos": campos,
        "confianzas": confianzas,
        "confianza_general": confianza(cajas),
        "texto_completo": "\n".join(texto_renglon(r) for r in renglones),
        "avisos": avisos,
        "requiere_revision": bool(avisos),
    }
