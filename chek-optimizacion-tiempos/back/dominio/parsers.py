import re
import unicodedata
from datetime import date
from difflib import get_close_matches

from back.dominio.reglas import (ANIO_MINIMO, CARACTERES_NUMERO, CENTENAS, DECENAS, DIGITO_A_LETRA, IGNORAR,
                     LETRA_A_DIGITO, MESES, PALABRAS_NUMERICAS, PATRONES_FECHA,
                     SIMILITUD_MINIMA, UNIDADES, VOCABULARIO_MONTO)

def normalizar(texto: str) -> str:
    if texto is None:
        return ""
    resultado = []
    for car in texto:
        base = unicodedata.normalize("NFD", car)[0]
        resultado.append(base.lower()[:1] or car)
    return "".join(resultado)

def _numero_en_texto(texto):
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
    if not texto:
        return None
    numero = _numero_en_texto(texto)
    if not numero:
        return None
    numero = numero.translate(LETRA_A_DIGITO).strip(" .,")

    decimal = re.search(r"[.,]\s*(\d{1,2})$", numero) or re.search(r"(?<=\d{3})\s+(\d{2})$", numero)
    if decimal:
        entero, centavos = numero[:decimal.start()], decimal.group(1).ljust(2, "0")
    else:
        entero, centavos = numero, "00"
    grupos = [g for g in re.split(r"[.,\s]+", entero) if g]
    if not grupos or not all(g.isdigit() for g in grupos):
        return None
    solo_espacios = not re.search(r"[.,]", entero)
    if len(grupos) > 1 and (any(len(g) != 3 for g in grupos[1:]) or (len(grupos[0]) > 3 and not solo_espacios)):
        return None
    return round(float("".join(grupos) + "." + centavos), 2)

def limpiar_monto_letras(texto: str) -> str:
    if not texto:
        return ""
    t = normalizar(texto)
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
    total = 0
    actual = 0
    encontrado = False
    for p in palabras:
        if p in UNIDADES:
            actual += UNIDADES[p]
        elif p in DECENAS:
            actual += DECENAS[p]
        elif p in ("cientos", "cientas") and 1 < actual % 100 < 10:
            actual += (actual % 100) * 100 - actual % 100
        elif p in CENTENAS:
            actual += CENTENAS[p]
        elif p == "mil":
            actual = (actual or 1) * 1000
            total += actual
            actual = 0
        elif p in ("millon", "millones"):
            total = (total + (actual or 1)) * 1_000_000
            actual = 0
        else:
            continue
        encontrado = True
    return total + actual if encontrado else None

def letras_a_numero(texto: str):
    if not texto:
        return None
    t = limpiar_monto_letras(texto)

    if "centavo" in t and not re.search(r"\bcon\b", t) and not re.search(r"\d", t):
        antes, _, despues = t.rpartition("dolares")
        if antes and "centavo" in despues:
            t = f"{antes} con {despues}"

    centavos = 0
    m = re.search(r"(\d{1,2})\s*/\s*100", t) or re.search(r"\b(\d{1,2})\s*(?:centavos?|ctvs?)\b", t)
    if m:
        centavos = int(m.group(1))
        t = t[: m.start()] + " " + t[m.end():]

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

def buscar_fecha(texto: str):
    if not texto:
        return None
    t = normalizar(texto)
    candidatos = []
    for patron, extraer in PATRONES_FECHA:
        for m in patron.finditer(t):
            try:
                d, mes, anio = extraer(m)
                if anio < ANIO_MINIMO:
                    continue
                candidatos.append((m.start(), date(anio, mes, d), m.end()))
            except ValueError:
                continue
    if not candidatos:
        return None
    inicio, fecha, fin = min(candidatos, key=lambda c: c[0])
    return fecha, inicio, fin
