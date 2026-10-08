"""Comparación de resultados contra las respuestas correctas (verdad.csv)."""

import re

from poc.parsers import letras_a_numero, normalizar

CAMPOS = ["numero_cheque", "cuenta", "banco", "micr", "monto_numeros", "monto_letras", "ciudad", "fecha",
          "beneficiario"]


def normalizar_valor(campo, valor):
    """Forma comparable de un valor (montos como número, números sin guiones, texto sin tildes)."""
    if valor in (None, ""):
        return ""
    v = str(valor).strip().lower()
    if campo in ("monto_numeros", "monto_letras"):
        if campo == "monto_letras" and not re.fullmatch(r"[\d.]+", v):
            n = letras_a_numero(v)
            return f"{n:.2f}" if n is not None else v
        try:
            return f"{float(v):.2f}"
        except ValueError:
            return v
    if campo in ("numero_cheque", "cuenta", "micr"):
        return re.sub(r"\D", "", v)
    return normalizar(v)


def clasificar(campo, detalle, esperado):
    """ok_auto / ok_revisar / error_revisar / error_auto, o None si no hay respuesta correcta."""
    if not esperado:
        return None
    correcto = normalizar_valor(campo, detalle["valor"]) == normalizar_valor(campo, esperado)
    return ("ok" if correcto else "error") + ("_revisar" if detalle["revisar"] else "_auto")
