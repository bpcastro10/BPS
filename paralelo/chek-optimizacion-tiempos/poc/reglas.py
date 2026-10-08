"""Reglas que se aplican a los datos del cheque, reunidas en un solo lugar.

Aquí están los parámetros de las reglas (campos, vocabularios, patrones, umbrales y
tablas). La lógica que los aplica sigue en su módulo:

- parsers.py      -> montos en cifras, montos en letras y fechas
- extraccion.py   -> búsqueda de cada campo en el OCR (estrategia A) y detección de firma
- confianza.py    -> nivel de confianza y confianza general
- validaciones.py -> normalización, validaciones y estado OK / REVISAR

Las reglas que se ajustan por entorno se leen del .env en config.py:
MESES_VIGENCIA (13), UMBRAL_CONFIANZA_ALTA (0.90) y UMBRAL_CONFIANZA_MEDIA (0.75).
"""

import re

# ---------------------------------------------------------------------------
# Campos del cheque
# ---------------------------------------------------------------------------

# Orden de los campos (sección 6) y nombres para mostrar
CAMPOS = [
    ("banco", "Banco"),
    ("numero_cheque", "N.º de cheque"),
    ("cuenta", "Cuenta"),
    ("ciudad", "Ciudad"),
    ("fecha", "Fecha"),
    ("beneficiario", "Beneficiario"),
    ("monto_numeros", "Monto en números"),
    ("monto_letras", "Monto en letras"),
    ("firma", "Firma"),
    ("micr", "Línea MICR"),
]
NOMBRES_CAMPOS = dict(CAMPOS)
# Si falta alguno, el cheque queda en REVISAR
CAMPOS_OBLIGATORIOS = ["banco", "fecha", "beneficiario", "monto_numeros", "monto_letras"]

# ---------------------------------------------------------------------------
# Confianza
# ---------------------------------------------------------------------------

# Peso de cada campo en la confianza general (promedio ponderado)
PESO_OBLIGATORIO = 2
PESO_OPCIONAL = 1

# ---------------------------------------------------------------------------
# Montos
# ---------------------------------------------------------------------------

# Cifras y letras coinciden si difieren en menos de un centavo
TOLERANCIA_MONTO = 0.01

# Letras que el OCR confunde con dígitos dentro de un número (ej. "1.25O,5O", "l.250")
LETRA_A_DIGITO = str.maketrans({"o": "0", "O": "0", "l": "1", "I": "1", "|": "1",
                                "s": "5", "S": "5", "B": "8", "Z": "2"})
CARACTERES_NUMERO = r"[\dOoIlSsBZ|.,\s]"

# Palabras de un monto en letras
UNIDADES = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
    "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
    "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18,
    "diecinueve": 19, "veinte": 20, "veintiun": 21, "veintiuno": 21,
    "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
    "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28,
    "veintinueve": 29,
    # "veinti" / "venti" separados (ej. "venti cuatro"): 20 + la unidad siguiente
    "veinti": 20, "venti": 20,
}
DECENAS = {
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
    "setenta": 70, "ochenta": 80, "noventa": 90,
}
CENTENAS = {
    "cien": 100, "ciento": 100, "doscientos": 200, "doscientas": 200,
    "trescientos": 300, "trescientas": 300, "cuatrocientos": 400,
    "cuatrocientas": 400, "quinientos": 500, "quinientas": 500,
    "seiscientos": 600, "seiscientas": 600, "setecientos": 700,
    "setecientas": 700, "ochocientos": 800, "ochocientas": 800,
    "novecientos": 900, "novecientas": 900,
}
IGNORAR = {"y", "de", "dolares", "dolar", "usd", "us", "moneda", "americanos",
           "norteamericanos", "exactos", "son", "la", "suma", "los", "estados",
           "unidos", "america", "00", "pesos", "m"}

PALABRAS_NUMERICAS = set(UNIDADES) | set(DECENAS) | set(CENTENAS) | {"mil", "millon", "millones"}

# Vocabulario cerrado de un monto en letras. Las palabras de relleno ("de", "los", "estados"...)
# están incluidas para que nunca se "corrijan" a un número (ej. "de" no debe volverse "diez").
VOCABULARIO_MONTO = PALABRAS_NUMERICAS | IGNORAR | {"con", "centavo", "centavos", "ctvs", "cts", "del", "solo",
                                                    "cientos", "cientas"}
# Dígitos que el OCR mete dentro de palabras (ej. "M:1" en lugar de "Mil")
DIGITO_A_LETRA = str.maketrans({"1": "i", "0": "o", "5": "s", "3": "e", "4": "a", "8": "b"})
# Parecido mínimo para corregir una palabra desconocida a la del vocabulario
SIMILITUD_MINIMA = 0.75

# ---------------------------------------------------------------------------
# Fechas
# ---------------------------------------------------------------------------

MESES = {
    "enero": 1, "ene": 1, "febrero": 2, "feb": 2, "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4, "mayo": 5, "may": 5, "junio": 6, "jun": 6,
    "julio": 7, "jul": 7, "agosto": 8, "ago": 8, "septiembre": 9,
    "setiembre": 9, "sep": 9, "sept": 9, "set": 9, "octubre": 10, "oct": 10,
    "noviembre": 11, "nov": 11, "diciembre": 12, "dic": 12,
}

# Meses en números romanos (ej. "2025, IX, 04")
ROMANOS = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7,
           "viii": 8, "ix": 9, "x": 10, "xi": 11, "xii": 12}
MESES_Y_ROMANOS = {**MESES, **ROMANOS}

# Un año de menos de 4 cifras no es fecha ("0116" es un número de oficio en la leyenda legal)
ANIO_MINIMO = 1000

# Mes escrito (nombre, abreviatura con punto opcional o romano), como palabra completa
_MES = "(" + "|".join(sorted(MESES_Y_ROMANOS, key=len, reverse=True)) + r")(?![a-z])\.?"
# Separador entre partes: coma, barra, guion, punto o espacios, con espacios opcionales
_SEP = r"\s*[,/\-.\s]\s*"
# Antes del año: "de", "del" o un separador
_SEP_ANIO = rf"(?:\s*\bdel?\s+|{_SEP})"

# Formatos de fecha aceptados (sobre texto normalizado). Cada patrón devuelve (dia, mes, anio)
PATRONES_FECHA = [
    # 04 de Septiembre de 2025 / 04 de Sep. del 2025 / 04 de IX de 2025 /
    # 04 de Septiembre/ 2025 / 20 Septiembre 2025 / 05 oct 2026 / 5-oct-2026
    (re.compile(rf"\b(\d{{1,2}})(?:\s*\bde\s+|{_SEP}){_MES}{_SEP_ANIO}(\d{{4}})\b"),
     lambda m: (int(m.group(1)), MESES_Y_ROMANOS[m.group(2)], int(m.group(3)))),
    # 2025, Septiembre, 04 / 2025, Sep, 04 / 2025, IX, 04 / 2025 Septiembre 04
    (re.compile(rf"\b(\d{{4}}){_SEP}{_MES}{_SEP}(\d{{1,2}})\b"),
     lambda m: (int(m.group(3)), MESES_Y_ROMANOS[m.group(2)], int(m.group(1)))),
    # Septiembre 04, 2025 / Sep. 04/2025
    (re.compile(rf"\b{_MES}{_SEP}(\d{{1,2}}){_SEP}(\d{{4}})\b"),
     lambda m: (int(m.group(2)), MESES_Y_ROMANOS[m.group(1)], int(m.group(3)))),
    # 2025/09/04, 2026-10-05, 2026 - 10 - 2, 2026, 09, 30 (año/mes/día)
    (re.compile(r"\b(\d{4})\s*[/\-.,]\s*(\d{1,2})\s*[/\-.,]\s*(\d{1,2})\b"),
     lambda m: (int(m.group(3)), int(m.group(2)), int(m.group(1)))),
    # 05/10/2026, 05-10-2026, 05.10.2026 (día/mes/año, formato ecuatoriano)
    (re.compile(r"\b(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})\b"),
     lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3)))),
]

# ---------------------------------------------------------------------------
# Extracción por etiquetas (estrategia A: OCR + reglas)
# ---------------------------------------------------------------------------

# Banco: la primera línea del OCR que contiene la palabra "banco" (ej. "BANCO PICHINCHA", "PRODUBANCO").
# Se devuelve la línea tal cual la leyó el OCR, sin compararla con ninguna lista.
RE_BANCO = re.compile(r"banco")

# Leyendas legales impresas (pie del cheque): no contienen datos del cheque
RE_LEYENDA_LEGAL = re.compile(r"superintendencia|oficio|resolucion|formulario|didactico|no tiene valor")

RE_MONEDA = r"us\.?\s*\$|usd|\$"

# Etiquetas impresas que preceden a cada valor (sobre texto normalizado)
ETIQUETA_CHEQUE = r"\b(cheque|ch)\.?\s*(nro|no|n°|nº|#|n)\b\.?"
ETIQUETA_CUENTA = r"\b(cta|cuenta)"
ETIQUETA_BENEFICIARIO = r"orden\s+de"
ETIQUETA_MONTO_LETRAS = r"suma\s+de"
RE_ETIQUETA_CIUDAD = re.compile(r"^\s*(ciudad\s*(y\s*fecha)?|lugar\s*y\s*fecha|fecha)\s*:?\s*")

# Número de cheque junto a la etiqueta: desde 2 dígitos (ej. "CHEQUE Nº 05).
# Sin guiones alrededor: "00-011" es el código de la agencia, no el número de cheque
RE_NUMERO_CHEQUE = r"(?<![\d-])\d{2,10}(?![\d-])"
# Número de cuenta: de 7 a 21 caracteres entre dígitos y guiones
RE_NUMERO_CUENTA = r"\b\d[\d-]{5,19}\d\b"
# Fuera de la etiqueta, un número es la cuenta si tiene al menos estos dígitos y aparece en la MICR
DIGITOS_MINIMOS_CUENTA_MICR = 8

# Línea MICR: una de las 4 últimas líneas, casi toda dígitos y símbolos
LINEAS_FINALES_MICR = 4
MICR_DIGITOS_MINIMOS = 12
MICR_PROPORCION_DIGITOS = 0.6

# ---------------------------------------------------------------------------
# Firma
# ---------------------------------------------------------------------------

# Fracción de píxeles oscuros en la zona de firma (heurística de la estrategia A)
UMBRAL_TINTA_PRESENTE = 0.012
UMBRAL_TINTA_AUSENTE = 0.003

# Valor de firma de los modelos de Azure -> valor propio
FIRMA_MODELO = {"signed": "presente", "unsigned": "ausente"}
