"""Utilidades puras (sin torch) para interpretar la salida del modelo.

La "confianza" se calcula a partir de las probabilidades que el modelo dio a
cada token que generó. Para un dato (por ejemplo, el valor numérico) es la
media geométrica de las probabilidades de los tokens que lo forman.
"""

import json
import math
from typing import Callable, Optional, Sequence

_DECODER = json.JSONDecoder(strict=False)
_WS = " \n\r\t"


def parse_json(text: str):
    """Devuelve el primer objeto JSON que aparezca en el texto, o None."""
    start = text.find("{")
    if start == -1:
        return None
    try:
        obj, _ = _DECODER.raw_decode(text, start)
    except ValueError:
        return None
    return obj


def top_level_value_spans(text: str) -> dict:
    """Mapa clave -> (inicio, fin) del valor de cada clave del JSON de primer nivel."""
    spans = {}
    start = text.find("{")
    if start == -1:
        return spans

    i, n = start + 1, len(text)
    while i < n:
        while i < n and text[i] in _WS + ",":
            i += 1
        if i >= n or text[i] != '"':
            break
        try:
            key, i = _DECODER.raw_decode(text, i)
        except ValueError:
            break
        while i < n and text[i] in _WS:
            i += 1
        if i >= n or text[i] != ":":
            break
        i += 1
        while i < n and text[i] in _WS:
            i += 1
        value_start = i
        try:
            _, i = _DECODER.raw_decode(text, i)
        except ValueError:
            break
        spans[key] = (value_start, i)
    return spans


def build_token_groups(
    ids: Sequence[int],
    logprobs: Sequence[float],
    decode: Callable[[Sequence[int]], str],
):
    """Relaciona cada token con el tramo de texto que produjo.

    Devuelve (grupos, texto). Cada grupo es (inicio, fin, [logprobs]).
    Si un carácter se reparte entre varios tokens (bytes de un UTF-8), sus
    probabilidades se agrupan en el primer token que completa el carácter.
    """
    groups = []
    pending = []
    previous_length = 0
    text = ""

    for i in range(len(ids)):
        pending.append(logprobs[i])
        text = decode(ids[: i + 1])
        if text.endswith("\ufffd"):
            continue
        start = min(previous_length, len(text))
        groups.append((start, len(text), pending))
        pending = []
        previous_length = len(text)

    if pending:
        groups.append((min(previous_length, len(text)), len(text), pending))
    return groups, text


def mean_probability(logprobs: Sequence[float]) -> Optional[float]:
    if not logprobs:
        return None
    return math.exp(sum(logprobs) / len(logprobs))


def compute_confidence(text: str, groups, all_logprobs: Sequence[float]):
    """Calcula la confianza global y por campo (valores entre 0 y 1).

    La global usa solo los tokens que forman los valores de los campos, para
    que las llaves, comillas y nombres de campo (casi siempre seguros) no
    inflen el resultado. Si no se pudo leer ningún campo, usa todos los tokens.
    """
    per_field = {}
    content_logprobs = []

    for key, (start, end) in top_level_value_spans(text).items():
        # Para cadenas, medir solo el contenido y no las comillas.
        if end - start > 2 and text[start] == '"':
            start, end = start + 1, end - 1
        lps = [
            lp
            for g_start, g_end, group in groups
            if g_start < end and g_end > start
            for lp in group
        ]
        value = mean_probability(lps)
        if value is not None:
            per_field[key] = value
            content_logprobs.extend(lps)

    overall = mean_probability(content_logprobs) or mean_probability(all_logprobs)
    return overall, per_field
