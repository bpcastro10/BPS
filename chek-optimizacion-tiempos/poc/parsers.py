"""Funciones de parseo: normalización de texto, montos, montos en letras y fechas."""

import re
import unicodedata
from datetime import date
from difflib import get_close_matches

from poc.reglas import (ANIO_MINIMO, CARACTERES_NUMERO, CENTENAS, DECENAS, DIGITO_A_LETRA, IGNORAR,  # noqa: F401
                     LETRA_A_DIGITO, MESES, MESES_Y_ROMANOS, PALABRAS_NUMERICAS, PATRONES_FECHA, ROMANOS,
                     SIMILITUD_MINIMA, UNIDADES, VOCABULARIO_MONTO)


def normalizar(texto: str) -> str:
    """Pasa a minúsculas y quita tildes (la ñ se convierte en n).

    Conserva la longitud del texto para que las posiciones (offsets) sigan
    siendo válidas respecto al texto original.
    """
    if texto is None:
        return ""
    resultado = []
    for car in texto:
        base = unicodedata.normalize("NFD", car)[0]
        resultado.append(base.lower()[:1] or car)
    return "".join(resultado)


def limpiar_relleno(texto: str) -> str:
    """Quita asteriscos, guiones y signos de relleno de los extremos del texto."""
    if texto is None:
        return ""
    texto = re.sub(r"[*=_~]+", " ", texto)
    texto = re.sub(r"(?:^|\s)[-.]{2,}|[-.]{2,}(?:\s|$)", " ", texto)
    texto = texto.strip(" -.:;,")
    return re.sub(r"\s+", " ", texto).strip()


# ---------------------------------------------------------------------------
# Montos en números
# ---------------------------------------------------------------------------

def _numero_en_texto(texto):
    """Primer número del texto (dígitos, letras confundibles y separadores), o None.

    Las palabras pegadas por espacios que no tienen ningún dígito no son parte del
    número (ej. en "1000 son" se toma "1000", no "1000 50n").
    """
    for m in re.finditer(rf"[\dOoIlSsBZ|]{CARACTERES_NUMERO}*", texto):
        partes = m.group(0).split()
        while partes and not re.search(r"\d", partes[0]):
            partes.pop(0)
        while partes and not re.search(r"\d", partes[-1]):
            partes.pop()
        if partes:
            return " ".join(partes)
    return None


def parsear_monto(texto: str):
    """Convierte un monto en cifras ('US$ 1.250,50') a float con 2 decimales.

    Reglas de formato de un monto en cifras:
    - Letras que el OCR confunde con dígitos se corrigen dentro del número (O→0, l→1, S→5, B→8, Z→2).
    - El separador decimal es el último '.' o ',' seguido de 1 o 2 dígitos al final
      (máximo 2 decimales: '1250.5' = 1250,50).
    - Los separadores de miles ('.', ',' o espacio) separan grupos de exactamente 3 dígitos.
    Devuelve None si no hay número o si el formato no es válido (ej. '12.50.000'),
    para que el monto quede "sin comparar" en lugar de interpretarse mal.
    """
    if not texto:
        return None
    numero = _numero_en_texto(texto)
    if not numero:
        return None
    numero = numero.translate(LETRA_A_DIGITO).strip(" .,")

    decimal = re.search(r"[.,]\s*(\d{1,2})$", numero) or re.search(r"(?<=\d{3})\s+(\d{2})$", numero)
    if decimal:
        # "1.250,50" o centavos en superíndice separados por espacio tras un grupo de miles ("1000 000 00")
        entero, centavos = numero[:decimal.start()], decimal.group(1).ljust(2, "0")
    else:
        entero, centavos = numero, "00"
    grupos = [g for g in re.split(r"[.,\s]+", entero) if g]
    if not grupos or not all(g.isdigit() for g in grupos):
        return None
    solo_espacios = not re.search(r"[.,]", entero)
    if len(grupos) > 1 and (any(len(g) != 3 for g in grupos[1:]) or (len(grupos[0]) > 3 and not solo_espacios)):
        return None   # grupos de miles mal formados: probable error de lectura
    return round(float("".join(grupos) + "." + centavos), 2)


# ---------------------------------------------------------------------------
# Montos en letras
# ---------------------------------------------------------------------------

def limpiar_monto_letras(texto: str) -> str:
    """Interpreta un monto en letras leído por OCR aplicando sus reglas de escritura.

    Un monto en letras no lleva ',' '.' ':' ni dígitos entre las palabras (solo "NN/100"
    o "NN centavos"). Por eso:
    - se quita la puntuación de cada palabra ("con." -> "con", "y . nueve." -> "y nueve");
    - en palabras que mezclan letras y dígitos, los dígitos se leen como letras ("m1" -> "mi");
    - cada palabra desconocida se aproxima a la palabra más parecida del vocabulario de
      montos si el parecido es alto ("mi" -> "mil", "setecientoss" -> "setecientos").
    Devuelve el texto interpretado en minúsculas y sin tildes. El texto original no se modifica.
    """
    if not texto:
        return ""
    t = normalizar(texto)
    # Los centavos en cifras ("50/100") se conservan tal cual
    centavos = re.search(r"\d{1,2}\s*/\s*100", t)
    if centavos:
        t = t[:centavos.start()] + " " + t[centavos.end():]

    palabras = []
    for bruta in t.split():
        palabra = re.sub(r"[^a-z0-9]", "", bruta)
        if not palabra:
            continue
        if re.search(r"[a-z]", palabra) and re.search(r"\d", palabra):
            palabra = palabra.translate(DIGITO_A_LETRA)
        if not palabra.isdigit() and palabra not in VOCABULARIO_MONTO:
            parecidas = get_close_matches(palabra, VOCABULARIO_MONTO, n=1, cutoff=SIMILITUD_MINIMA)
            if parecidas:
                palabra = parecidas[0]
        palabras.append(palabra)
    if centavos:
        palabras.append(re.sub(r"\s", "", centavos.group(0)))
    return " ".join(palabras)


def _palabras_a_entero(palabras):
    """Convierte una lista de palabras numéricas a entero. None si no hay ninguna."""
    total = 0
    actual = 0
    encontrado = False
    for p in palabras:
        if p in UNIDADES:
            actual += UNIDADES[p]
        elif p in DECENAS:
            actual += DECENAS[p]
        elif p in ("cientos", "cientas") and 1 < actual % 100 < 10:
            # Centena escrita en dos palabras: "cuatro cientos" = 400
            actual += (actual % 100) * 100 - actual % 100
        elif p in CENTENAS:
            actual += CENTENAS[p]
        elif p == "mil":
            actual = (actual or 1) * 1000
            total += actual
            actual = 0
        elif p in ("millon", "millones"):
            # El millón multiplica todo lo acumulado hasta aquí
            total = (total + (actual or 1)) * 1_000_000
            actual = 0
        else:
            continue
        encontrado = True
    return total + actual if encontrado else None


def letras_a_numero(texto: str):
    """Convierte un monto escrito en letras en español a float.

    Ejemplos: 'mil doscientos cincuenta 50/100' -> 1250.50,
    'cero dólares con 75/100' -> 0.75, 'veintidós dólares' -> 22.0.
    """
    if not texto:
        return None
    t = limpiar_monto_letras(texto)

    # Centavos en palabras sin "con": "novecientos cincuenta dolares y veinticuatro centavos"
    if "centavo" in t and not re.search(r"\bcon\b", t) and not re.search(r"\d", t):
        antes, _, despues = t.rpartition("dolares")
        if antes and "centavo" in despues:
            t = f"{antes} con {despues}"

    # Centavos en cifras: "50/100" o "50 centavos"
    centavos = 0
    m = re.search(r"(\d{1,2})\s*/\s*100", t) or re.search(r"\b(\d{1,2})\s*(?:centavos?|ctvs?)\b", t)
    if m:
        centavos = int(m.group(1))
        t = t[: m.start()] + " " + t[m.end():]

    # Lo que va después de "con" son los centavos escritos en palabras, con o sin la palabra
    # "centavos": "con cincuenta centavos", "con noventa y nueve" (también "y . nueve." del OCR)
    partes = re.split(r"\bcon\b", t, maxsplit=1)
    parte_entera = partes[0]
    if len(partes) > 1 and not m:
        c = _palabras_a_entero(re.findall(r"[a-z]+", partes[1]))
        if c is not None and c < 100:
            centavos = c

    palabras = [p for p in re.findall(r"[a-z]+", parte_entera) if p not in IGNORAR]
    entero = _palabras_a_entero(palabras)
    if entero is None:
        if not m:
            return None
        entero = 0
    return round(entero + centavos / 100, 2)


def contar_palabras_numericas(texto: str) -> int:
    return sum(1 for p in re.findall(r"[a-z]+", normalizar(texto)) if p in PALABRAS_NUMERICAS)


# ---------------------------------------------------------------------------
# Fechas
# ---------------------------------------------------------------------------

def buscar_fecha(texto: str):
    """Busca la primera fecha válida en el texto.

    Devuelve (fecha: date, inicio, fin) con posiciones relativas al texto,
    o None si no hay fecha válida. Descarta fechas inválidas como 31/02.
    """
    if not texto:
        return None
    t = normalizar(texto)
    candidatos = []
    for patron, extraer in PATRONES_FECHA:
        for m in patron.finditer(t):
            try:
                d, mes, anio = extraer(m)
                if anio < ANIO_MINIMO:   # "0116" no es un año (ej. número de oficio en la leyenda legal)
                    continue
                candidatos.append((m.start(), date(anio, mes, d), m.end()))
            except ValueError:
                continue
    if not candidatos:
        return None
    inicio, fecha, fin = min(candidatos, key=lambda c: c[0])
    return fecha, inicio, fin


def parsear_fecha(texto: str):
    """Convierte un texto de fecha a ISO 'YYYY-MM-DD'. None si no es válida."""
    r = buscar_fecha(texto)
    return r[0].isoformat() if r else None
