import re

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
CAMPOS_OBLIGATORIOS = ["banco", "fecha", "beneficiario", "monto_numeros", "monto_letras"]

PESO_OBLIGATORIO = 2
PESO_OPCIONAL = 1

TOLERANCIA_MONTO = 0.01

LETRA_A_DIGITO = str.maketrans({"o": "0", "O": "0", "l": "1", "I": "1", "|": "1",
                                "s": "5", "S": "5", "B": "8", "Z": "2"})
CARACTERES_NUMERO = r"[\dOoIlSsBZ|.,\s]"

UNIDADES = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
    "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
    "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18,
    "diecinueve": 19, "veinte": 20, "veintiun": 21, "veintiuno": 21,
    "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
    "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28,
    "veintinueve": 29,
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

VOCABULARIO_MONTO = PALABRAS_NUMERICAS | IGNORAR | {"con", "centavo", "centavos", "ctvs", "cts", "del", "solo",
                                                    "cientos", "cientas"}
DIGITO_A_LETRA = str.maketrans({"1": "i", "0": "o", "5": "s", "3": "e", "4": "a", "8": "b"})
SIMILITUD_MINIMA = 0.75

MESES = {
    "enero": 1, "ene": 1, "febrero": 2, "feb": 2, "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4, "mayo": 5, "may": 5, "junio": 6, "jun": 6,
    "julio": 7, "jul": 7, "agosto": 8, "ago": 8, "septiembre": 9,
    "setiembre": 9, "sep": 9, "sept": 9, "set": 9, "octubre": 10, "oct": 10,
    "noviembre": 11, "nov": 11, "diciembre": 12, "dic": 12,
}

ROMANOS = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7,
           "viii": 8, "ix": 9, "x": 10, "xi": 11, "xii": 12}
MESES_Y_ROMANOS = {**MESES, **ROMANOS}

ANIO_MINIMO = 1000

_MES = "(" + "|".join(sorted(MESES_Y_ROMANOS, key=len, reverse=True)) + r")(?![a-z])\.?"
_SEP = r"\s*[,/\-.\s]\s*"
_SEP_ANIO = rf"(?:\s*\bdel?\s+|{_SEP})"

PATRONES_FECHA = [
    (re.compile(rf"\b(\d{{1,2}})(?:\s*\bde\s+|{_SEP}){_MES}{_SEP_ANIO}(\d{{4}})\b"),
     lambda m: (int(m.group(1)), MESES_Y_ROMANOS[m.group(2)], int(m.group(3)))),
    (re.compile(rf"\b(\d{{4}}){_SEP}{_MES}{_SEP}(\d{{1,2}})\b"),
     lambda m: (int(m.group(3)), MESES_Y_ROMANOS[m.group(2)], int(m.group(1)))),
    (re.compile(rf"\b{_MES}{_SEP}(\d{{1,2}}){_SEP}(\d{{4}})\b"),
     lambda m: (int(m.group(2)), MESES_Y_ROMANOS[m.group(1)], int(m.group(3)))),
    (re.compile(r"\b(\d{4})\s*[/\-.,]\s*(\d{1,2})\s*[/\-.,]\s*(\d{1,2})\b"),
     lambda m: (int(m.group(3)), int(m.group(2)), int(m.group(1)))),
    (re.compile(r"\b(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})\b"),
     lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3)))),
]

RE_BANCO = re.compile(r"banco")

RE_LEYENDA_LEGAL = re.compile(r"superintendencia|oficio|resolucion|formulario|didactico|no tiene valor")

RE_MONEDA = r"us\.?\s*\$|usd|\$"

ETIQUETA_CHEQUE = r"\b(cheque|ch)\.?\s*(nro|no|n°|nº|#|n)\b\.?"
ETIQUETA_CUENTA = r"\b(cta|cuenta)"
ETIQUETA_BENEFICIARIO = r"orden\s+de"
ETIQUETA_MONTO_LETRAS = r"suma\s+de"
RE_ETIQUETA_CIUDAD = re.compile(r"^\s*(ciudad\s*(y\s*fecha)?|lugar\s*y\s*fecha|fecha)\s*:?\s*")

RE_NUMERO_CHEQUE = r"(?<![\d-])\d{2,10}(?![\d-])"
RE_NUMERO_CUENTA = r"\b\d[\d-]{5,19}\d\b"
DIGITOS_MINIMOS_CUENTA_MICR = 8

LINEAS_FINALES_MICR = 4
MICR_DIGITOS_MINIMOS = 12
MICR_PROPORCION_DIGITOS = 0.6

UMBRAL_TINTA_PRESENTE = 0.012
UMBRAL_TINTA_AUSENTE = 0.003

FIRMA_MODELO = {"signed": "presente", "unsigned": "ausente"}
