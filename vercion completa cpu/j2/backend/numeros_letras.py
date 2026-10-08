"""
Convierte un monto escrito en letras (español) a número.

Ejemplo: "MIL QUINIENTOS VEINTE DOLARES CON 50/100" -> Decimal("1520.50")

Tolera errores típicos del OCR en letra manuscrita ("QUlNIENTOS", "VEINTF")
corrigiendo cada palabra con la más parecida del vocabulario (difflib).
"""
import re
import unicodedata
from decimal import Decimal
from difflib import SequenceMatcher, get_close_matches
from functools import lru_cache

VALORES = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11,
    "doce": 12, "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16,
    "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "veintiun": 21, "veintiuno": 21, "veintiuna": 21, "veintidos": 22,
    "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30,
    "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70,
    "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100,
    "doscientos": 200, "doscientas": 200, "trescientos": 300, "trescientas": 300,
    "cuatrocientos": 400, "cuatrocientas": 400, "quinientos": 500, "quinientas": 500,
    "seiscientos": 600, "seiscientas": 600, "setecientos": 700, "setecientas": 700,
    "ochocientos": 800, "ochocientas": 800, "novecientos": 900, "novecientas": 900,
}
MULTIPLICADORES = {"mil": 1_000, "millon": 1_000_000, "millones": 1_000_000}

# Palabras que pueden aparecer en el monto pero no aportan valor
IGNORADAS = {
    "y", "de", "del", "los", "las", "la", "el", "son", "suma", "cantidad",
    "dolares", "dolar", "pesos", "peso", "soles", "sol", "bolivares", "quetzales",
    "colones", "lempiras", "guaranies", "reales", "euros", "moneda", "nacional",
    "americanos", "norteamericanos", "estados", "unidos", "usd", "us", "exactos",
    "solamente", "centavos", "centavo", "con", "m/n", "mn", "cts", "ctvs",
}

VOCABULARIO = list(VALORES) + list(MULTIPLICADORES) + list(IGNORADAS)
VOCABULARIO_SET = set(VOCABULARIO)
PALABRAS_NUMERICAS = set(VALORES) | set(MULTIPLICADORES)


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes."""
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


# Letras que el OCR confunde con dígitos (solo se aplican dentro de "xx/100")
LETRAS_A_DIGITOS = str.maketrans("oOdDiIlLsSzZbgq", "000011115522699")
RE_FRACCION = re.compile(r"([0-9oOdDiIlLsSzZbgq]{1,2})\s*/\s*[1iIlL][0oO]{2}")


COSTO_PIEZA = 0.3   # penaliza dividir en muchas piezas
COSTO_SALTO = 1.1   # costo de descartar una letra; alto para no 'comerse' veinte/mil


@lru_cache(maxsize=4096)
def _parecida(pieza: str) -> tuple[str, float] | None:
    """Palabra del vocabulario más parecida a `pieza` y su costo (0 = idéntica)."""
    if pieza in VOCABULARIO_SET:
        return pieza, 0.0
    if len(pieza) < 4:
        return None
    opciones = get_close_matches(pieza, VOCABULARIO, n=1, cutoff=0.68)
    if not opciones:
        return None
    return opciones[0], 2 * (1 - SequenceMatcher(None, pieza, opciones[0]).ratio())


@lru_cache(maxsize=2048)
def corregir_palabra(palabra: str) -> tuple[str, ...]:
    """
    Convierte lo leído por el OCR en palabras del vocabulario, separando las que vienen pegadas
    y corrigiendo errores: "treycientoscincuentadolares" -> ("trescientos", "cincuenta", "dolares").

    Programación dinámica: elige la división de menor costo (piezas exactas o parecidas).
    """
    if palabra in VOCABULARIO_SET or len(palabra) < 3:
        return (palabra,)
    n = len(palabra)
    costo = [float("inf")] * (n + 1)
    piezas: list[tuple[str, ...]] = [()] * (n + 1)
    costo[0] = 0.0
    for fin in range(1, n + 1):
        if costo[fin - 1] + COSTO_SALTO < costo[fin]:  # descartar una letra
            costo[fin], piezas[fin] = costo[fin - 1] + COSTO_SALTO, piezas[fin - 1]
        for inicio in range(max(0, fin - 16), fin):
            coincidencia = _parecida(palabra[inicio:fin])
            if coincidencia is None:
                continue
            total = costo[inicio] + coincidencia[1] + COSTO_PIEZA
            if total < costo[fin]:
                costo[fin], piezas[fin] = total, piezas[inicio] + (coincidencia[0],)
    if not piezas[n] or costo[n] > 0.25 * n + COSTO_PIEZA:
        return (palabra,)  # demasiada basura: no es un número en letras
    return piezas[n]


def tokenizar(texto: str) -> list[str]:
    texto = normalizar(texto).replace("+", "t")  # el OCR lee la "t" manuscrita como "+"
    for origen, destino in (("rn", "m"), ("vv", "w"), ("ii", "u"), ("cl", "d")):
        texto = texto.replace(origen, destino)
    return [p for palabra in re.findall(r"[a-z]+", texto) for p in corregir_palabra(palabra)]


def texto_normalizado(texto: str) -> str:
    """Monto en letras reescrito con palabras correctas: 'MIL QUINIENTOS VEINTE DOLARES CON 50/100'."""
    limpio = normalizar(texto)
    fraccion = RE_FRACCION.search(limpio)
    sufijo = ""
    if fraccion:
        sufijo = f" {int(fraccion.group(1).translate(LETRAS_A_DIGITOS)):02d}/100"
        limpio = limpio[: fraccion.start()]
    return (" ".join(tokenizar(limpio)) + sufijo).upper().strip()


def contar_palabras_numericas(texto: str) -> int:
    """Cuántas palabras de un texto son números en letras (sirve para detectar el renglón del monto)."""
    return sum(1 for p in tokenizar(texto) if p in PALABRAS_NUMERICAS)


def _palabras_a_entero(palabras: list[str]) -> int | None:
    total, actual, encontrado = 0, 0, False
    for palabra in palabras:
        if palabra in VALORES:
            actual += VALORES[palabra]
            encontrado = True
        elif palabra == "mil":
            total += (actual or 1) * 1_000
            actual = 0
            encontrado = True
        elif palabra in ("millon", "millones"):
            total = (total + (actual or 1)) * 1_000_000
            actual = 0
            encontrado = True
    return total + actual if encontrado else None


def letras_a_numero(texto: str) -> Decimal | None:
    """Convierte el texto del monto en letras a Decimal. Devuelve None si no se reconoce."""
    if not texto:
        return None
    limpio = normalizar(texto)

    # Centavos en formato "50/100" (tolera "5o/1oo" y similares)
    centavos = 0
    fraccion = RE_FRACCION.search(limpio)
    if fraccion:
        centavos = int(fraccion.group(1).translate(LETRAS_A_DIGITOS))
        limpio = limpio[: fraccion.start()]

    palabras = tokenizar(limpio)

    # Centavos en letras: "... con cincuenta centavos"
    if not fraccion and "con" in palabras:
        corte = len(palabras) - 1 - palabras[::-1].index("con")
        parte_centavos = _palabras_a_entero(palabras[corte + 1:])
        if parte_centavos is not None and parte_centavos < 100:
            centavos = parte_centavos
            palabras = palabras[:corte]

    entero = _palabras_a_entero(palabras)
    if entero is None:
        return None
    return (Decimal(entero) + Decimal(centavos) / Decimal(100)).quantize(Decimal("0.01"))
