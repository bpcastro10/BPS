"""Reglas de cheques: fechas, montos y armado de cada fila del informe.

No depende del modelo. Recibe el JSON que ya extrajo el lector y decide
si el archivo tiene observaciones.
"""

import json
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

_CENTAVO = Decimal("0.01")
_NEGATIVOS = {
    "no",
    "n",
    "false",
    "falso",
    "0",
    "ausente",
    "sin firma",
    "no presente",
    "no detectada",
    "no detectado",
    "ninguna",
    "ninguno",
    "null",
    "none",
}

_MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
_ABREVIADOS = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "sept": 9,
    "set": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}
_ROMANOS = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
    "xi": 11,
    "xii": 12,
}

# Cada formato del archivo de reglas apunta a uno o mas patrones.
# Los grupos se interpretan segun el orden indicado.
_FORMATOS = {
    "aaaa/mm/dd": ("ymd", re.compile(r"(?<!\d)(\d{4})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})(?!\d)")),
    "aaaa-mm-dd": ("ymd", re.compile(r"(?<!\d)(\d{4})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})(?!\d)")),
    "aaaa, mm, dd": ("ymd", re.compile(r"(?<!\d)(\d{4})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})(?!\d)")),
    "aaaa, mes, dd": ("ymd", re.compile(r"(?<!\d)(\d{4})\s*,\s*([a-z]{3,})\s*,\s*(\d{1,2})(?!\d)")),
    "aaaa, mes abreviado, dd": (
        "ymd",
        re.compile(r"(?<!\d)(\d{4})\s*,\s*([a-z]{3,4}\.?)\s*,\s*(\d{1,2})(?!\d)"),
    ),
    "aaaa, mes romano, dd": (
        "ymd",
        re.compile(r"(?<!\d)(\d{4})\s*,\s*(xii|xi|x|ix|viii|vii|vi|v|iv|iii|ii|i)\s*,\s*(\d{1,2})(?!\d)"),
    ),
    "dd de mes de aaaa": ("dmy", re.compile(r"(?<!\d)(\d{1,2})\s+de\s+([a-z]{4,})\s+de\s+(\d{4})(?!\d)")),
    "dd de mes del aaaa": ("dmy", re.compile(r"(?<!\d)(\d{1,2})\s+de\s+([a-z]{4,})\s+del\s+(\d{4})(?!\d)")),
    "dd de mes abreviado. de aaaa": (
        "dmy",
        re.compile(r"(?<!\d)(\d{1,2})\s+de\s+([a-z]{3,4}\.?)\s+de\s+(\d{4})(?!\d)"),
    ),
    "dd de mes abreviado. del aaaa": (
        "dmy",
        re.compile(r"(?<!\d)(\d{1,2})\s+de\s+([a-z]{3,4}\.?)\s+del\s+(\d{4})(?!\d)"),
    ),
    "dd de mes romano de aaaa": (
        "dmy",
        re.compile(
            r"(?<!\d)(\d{1,2})\s+de\s+(xii|xi|x|ix|viii|vii|vi|v|iv|iii|ii|i)\s+de\s+(\d{4})(?!\d)"
        ),
    ),
    "dd de mes abreviado. aaaa": (
        "dmy",
        re.compile(r"(?<!\d)(\d{1,2})\s+de\s+([a-z]{3,4}\.?)\s+(\d{4})(?!\d)"),
    ),
    "mes dd, aaaa": ("mdy", re.compile(r"(?<!\d)([a-z]{3,})\s+(\d{1,2})\s*,\s*(\d{4})(?!\d)")),
    "dd de mes/ aaaa": ("dmy", re.compile(r"(?<!\d)(\d{1,2})\s+de\s+([a-z]{3,}\.?)\s*/\s*(\d{4})(?!\d)")),
    "mes abreviado. dd/aaaa": ("mdy", re.compile(r"(?<!\d)([a-z]{3,4}\.?)\s+(\d{1,2})\s*/\s*(\d{4})(?!\d)")),
    "aaaa mes dd": ("ymd", re.compile(r"(?<!\d)(\d{4})\s+([a-z]{3,}\.?)\s+(\d{1,2})(?!\d)")),
    "dd mes aaaa": ("dmy", re.compile(r"(?<!\d)(\d{1,2})\s+([a-z]{3,}\.?)\s+(\d{4})(?!\d)")),
}

_ALIAS = {
    "cuenta_no": (
        "cuenta_no",
        "numero_cuenta",
        "numero_de_cuenta",
        "nro_cuenta",
        "num_cuenta",
        "no_cuenta",
        "cuenta",
        "cta",
        "cuenta_corriente",
    ),
    "cheque_no": (
        "cheque_no",
        "numero_cheque",
        "numero_de_cheque",
        "nro_cheque",
        "num_cheque",
        "no_cheque",
        "cheque",
    ),
    "a_la_orden_de": (
        "a_la_orden_de",
        "a_la_orden",
        "pagese_a",
        "paguese_a",
        "pague_a",
        "beneficiario",
        "orden_de",
        "nombre_beneficiario",
    ),
    "valor_numero": (
        "valor_numero",
        "valor_numerico",
        "valor",
        "monto",
        "importe",
        "cantidad",
        "valor_en_numeros",
    ),
    "valor_texto": (
        "valor_texto",
        "valor_letras",
        "valor_en_letras",
        "monto_letras",
        "importe_letras",
        "cantidad_letras",
    ),
    "cliente": (
        "cliente",
        "nombre_cliente",
        "girador",
        "librador",
        "titular",
        "cuenta_habiente",
        "ordenante",
    ),
    "fecha": ("fecha", "fecha_emision", "fecha_cheque", "fecha_del_cheque"),
    "lugar": ("lugar", "ciudad", "plaza", "lugar_emision"),
    "endoso": ("endoso", "endosos", "endoso_texto", "texto_endoso", "detalle_endoso"),
    "endoso_flag": ("endoso_presente", "tiene_endoso", "endosado", "endoso"),
    "firma": ("firma_presente", "tiene_firma", "firma", "firmas"),
}

_UNIDADES = {
    "cero": 0,
    "un": 1,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "veintiun": 21,
    "veintiuno": 21,
    "veintidos": 22,
    "veintitres": 23,
    "veinticuatro": 24,
    "veinticinco": 25,
    "veintiseis": 26,
    "veintisiete": 27,
    "veintiocho": 28,
    "veintinueve": 29,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
    "cien": 100,
    "ciento": 100,
    "doscientos": 200,
    "docientos": 200,
    "trescientos": 300,
    "tresientos": 300,
    "cuatrocientos": 400,
    "quinientos": 500,
    "seiscientos": 600,
    "setecientos": 700,
    "ochocientos": 800,
    "novecientos": 900,
}
_RELLENO = {"y", "dolares", "dolar", "usd", "ctvs", "centavos", "centavo", "son", "la", "suma", "de"}


def cargar_reglas(ruta: Path) -> dict:
    """Lee el archivo de reglas y deja una estructura lista para evaluar."""
    try:
        contenido = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"No encuentro el archivo de reglas: {ruta}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"El archivo de reglas no es un JSON valido: {exc}") from exc

    fecha = contenido.get("fecha") or {}
    meses = fecha.get("meses_maximos")
    if not isinstance(meses, int) or meses < 0:
        raise ValueError("En reglas.json, fecha.meses_maximos debe ser un numero entero mayor o igual a 0.")

    formatos = fecha.get("formatos") or []
    if not isinstance(formatos, list) or not formatos:
        raise ValueError("En reglas.json, fecha.formatos debe incluir al menos un formato.")

    desconocidos = [nombre for nombre in formatos if _clave_formato(nombre) not in _FORMATOS]
    if desconocidos:
        raise ValueError("Hay formatos de fecha que este lector no reconoce: " + ", ".join(map(str, desconocidos)))

    validaciones = {}
    for nombre in ("firma", "beneficiario", "coincide_valor", "fecha_correcta", "endoso"):
        bloque = (contenido.get("validaciones") or {}).get(nombre) or {}
        validaciones[nombre] = bool(bloque.get("activa", True))

    return {
        "meses_maximos": meses,
        "regla_fecha": str(fecha.get("regla") or ""),
        "formatos": [str(nombre) for nombre in formatos],
        "validaciones": validaciones,
    }


def evaluar_cheque(nombre_archivo: str, datos, reglas: dict, hoy: date | None = None) -> dict:
    """Convierte la lectura de un cheque en la fila del informe."""
    hoy = hoy or date.today()
    indice = _indexar(datos if isinstance(datos, dict) else {})

    cuenta = _primer_texto(indice, "cuenta_no")
    cheque = _primer_texto(indice, "cheque_no")
    orden = _primer_texto(indice, "a_la_orden_de")
    valor_numero = _buscar(indice, "valor_numero")
    valor_texto = _primer_texto(indice, "valor_texto")
    cliente = _primer_texto(indice, "cliente")
    fecha_texto = _fecha_visible(_buscar(indice, "fecha"), _buscar(indice, "lugar"))
    endoso_bruto = _buscar(indice, "endoso")
    endoso_leido = endoso_bruto.strip() if isinstance(endoso_bruto, str) else ""
    endoso_texto = "" if _es_bandera(endoso_leido) else endoso_leido

    firma = _si_no(_presente_en(indice, "firma"))
    beneficiario = _si_no(bool(orden))
    coincide = _si_no(_montos_coinciden(valor_numero, valor_texto))
    fecha_ok = _si_no(_fecha_es_valida(fecha_texto, reglas, hoy))
    endoso = _si_no(_endoso_presente(indice, endoso_leido))

    fila = {
        "nombre_archivo": nombre_archivo,
        "cuenta_no": cuenta,
        "cheque_no": cheque,
        "a_la_orden_de": orden,
        "valor_numero": _numero_o_texto(valor_numero),
        "valor_texto": valor_texto,
        "cliente": cliente,
        "fecha": fecha_texto,
        "endoso_texto": endoso_texto,
        "firma": firma,
        "beneficiario": beneficiario,
        "coincide_valor": coincide,
        "fecha_correcta": fecha_ok,
        "endoso": endoso,
    }
    fila["incluir"] = _tiene_observacion(fila, reglas)
    return fila


def fila_no_leida(nombre_archivo: str) -> dict:
    """Fila de un archivo que no se pudo leer. Siempre entra al informe."""
    return {
        "nombre_archivo": nombre_archivo,
        "cuenta_no": "",
        "cheque_no": "",
        "a_la_orden_de": "",
        "valor_numero": "",
        "valor_texto": "",
        "cliente": "",
        "fecha": "",
        "endoso_texto": "",
        "firma": "NO",
        "beneficiario": "NO",
        "coincide_valor": "NO",
        "fecha_correcta": "NO",
        "endoso": "NO",
        "incluir": True,
    }


def valores_fila(fila: dict) -> list:
    """Orden exacto de las columnas del Excel."""
    return [
        fila["nombre_archivo"],
        fila["cuenta_no"],
        fila["cheque_no"],
        fila["a_la_orden_de"],
        fila["valor_numero"],
        fila["valor_texto"],
        fila["cliente"],
        fila["fecha"],
        fila["endoso_texto"],
        fila["firma"],
        fila["beneficiario"],
        fila["coincide_valor"],
        fila["fecha_correcta"],
        fila["endoso"],
    ]


def parsear_fecha(texto: str, formatos: list[str]) -> date | None:
    """Devuelve la primera fecha reconocida con los formatos habilitados."""
    plano = _plano(texto)
    if not plano:
        return None
    for nombre in formatos:
        patron = _FORMATOS.get(_clave_formato(nombre))
        if patron is None:
            continue
        orden, expresion = patron
        for hallazgo in expresion.finditer(plano):
            partes = hallazgo.groups()
            convertida = _armar_fecha(orden, partes)
            if convertida is not None:
                return convertida
    return None


def meses_transcurridos(desde: date, hasta: date) -> int:
    """Meses completos entre dos fechas. Negativo si la fecha del cheque es futura."""
    meses = (hasta.year - desde.year) * 12 + (hasta.month - desde.month)
    if hasta.day < desde.day:
        meses -= 1
    return meses


def parsear_valor_numerico(valor) -> Decimal | None:
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float, Decimal)):
        try:
            return Decimal(str(valor)).quantize(_CENTAVO, rounding=ROUND_HALF_UP)
        except InvalidOperation:
            return None
    texto = str(valor).strip()
    if not texto:
        return None
    texto = texto.replace(" ", "")
    texto = re.sub(r"[^\d,.\-]", "", texto)
    if not texto or texto in {"-", ".", ","}:
        return None
    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        parte_decimal = texto.split(",")[-1]
        texto = texto.replace(",", ".") if len(parte_decimal) <= 2 else texto.replace(",", "")
    try:
        return Decimal(texto).quantize(_CENTAVO, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def parsear_valor_texto(texto: str) -> Decimal | None:
    """Interpreta un monto escrito en espanol, por ejemplo 'ciento treinta y cuatro con 00/100'."""
    plano = _plano(texto)
    if not plano:
        return None
    centavos = 0
    hallazgo = re.search(r"\bcon\s+(\d{1,2})(?:\s*/\s*\d+)?", plano)
    if hallazgo:
        centavos = int(hallazgo.group(1))
        plano = plano[: hallazgo.start()]
    else:
        fraccion = re.search(r"(\d{1,2})\s*/\s*100\b", plano)
        if fraccion:
            centavos = int(fraccion.group(1))
            plano = plano[: fraccion.start()]
    if centavos > 99:
        return None

    tokens = [token for token in re.split(r"[^a-z0-9]+", plano) if token and token not in _RELLENO]
    if not tokens:
        return None
    entero = _entero_en_espanol(tokens)
    if entero is None:
        return None
    return (Decimal(entero) + (Decimal(centavos) / Decimal(100))).quantize(_CENTAVO, rounding=ROUND_HALF_UP)


def _fecha_es_valida(texto: str, reglas: dict, hoy: date) -> bool:
    reconocida = parsear_fecha(texto, reglas["formatos"])
    if reconocida is None:
        return False
    return meses_transcurridos(reconocida, hoy) < reglas["meses_maximos"]


def _montos_coinciden(numero, texto: str) -> bool:
    valor = parsear_valor_numerico(numero)
    letras = parsear_valor_texto(texto)
    if valor is None or letras is None:
        return False
    return valor == letras


def _tiene_observacion(fila: dict, reglas: dict) -> bool:
    activas = reglas["validaciones"]
    controles = (
        ("firma", "firma"),
        ("beneficiario", "beneficiario"),
        ("coincide_valor", "coincide_valor"),
        ("fecha_correcta", "fecha_correcta"),
        ("endoso", "endoso"),
    )
    return any(activas.get(regla, True) and fila[campo] == "NO" for regla, campo in controles)


def _endoso_presente(indice: dict, texto: str) -> bool:
    if texto and not _es_negativo(texto):
        return True
    for clave in ("endoso_presente", "tiene_endoso", "endosado"):
        if clave in indice and _es_presente(indice[clave]):
            return True
    valor = indice.get("endoso")
    if isinstance(valor, str):
        return bool(valor.strip()) and not _es_negativo(valor)
    return _es_presente(valor)


def _presente_en(indice: dict, grupo: str) -> bool:
    for clave in _ALIAS[grupo]:
        if clave in indice and _es_presente(indice[clave]):
            return True
    return False


def _es_presente(valor) -> bool:
    if valor is None:
        return False
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return valor != 0
    if isinstance(valor, (list, tuple, set)):
        return any(_es_presente(item) for item in valor)
    if isinstance(valor, dict):
        return any(_es_presente(item) for item in valor.values())
    return not _es_negativo(str(valor))


_BANDERAS = {"si", "yes", "true", "verdadero", "presente"}


def _es_negativo(texto: str) -> bool:
    plano = _plano(texto)
    return plano in _NEGATIVOS or plano.startswith("no ")


def _es_bandera(texto: str) -> bool:
    return _plano(texto) in _BANDERAS or _es_negativo(texto)


def _fecha_visible(fecha, lugar) -> str:
    texto = _texto(fecha)
    plaza = _texto(lugar)
    if not texto:
        return plaza
    if not plaza or plaza.lower() in texto.lower():
        return texto
    return f"{plaza}, {texto}"


def _numero_o_texto(valor):
    if isinstance(valor, str) and not valor.strip():
        return ""
    numero = parsear_valor_numerico(valor)
    if numero is None:
        return _texto(valor)
    return float(numero)


def _indexar(datos: dict) -> dict:
    indice = {}
    for clave, valor in datos.items():
        indice.setdefault(_clave_formato(clave).replace(" ", "_"), valor)
    return indice


def _buscar(indice: dict, grupo: str):
    for clave in _ALIAS[grupo]:
        if clave in indice and indice[clave] not in (None, ""):
            return indice[clave]
    return None


def _primer_texto(indice: dict, grupo: str) -> str:
    for clave in _ALIAS[grupo]:
        valor = indice.get(clave)
        if isinstance(valor, str) and valor.strip() and not _es_negativo(valor):
            return valor.strip()
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            return str(valor).strip()
    return ""


def _texto(valor) -> str:
    if valor is None or isinstance(valor, (bool, list, dict)):
        return ""
    return str(valor).strip()


def _si_no(condicion: bool) -> str:
    return "SI" if condicion else "NO"


def _plano(texto: str) -> str:
    base = unicodedata.normalize("NFD", str(texto))
    sin_tilde = "".join(caracter for caracter in base if unicodedata.category(caracter) != "Mn")
    return re.sub(r"\s+", " ", sin_tilde).strip().lower()


def _clave_formato(nombre: str) -> str:
    return re.sub(r"\s+", " ", _plano(nombre))


def _mes(token: str) -> int | None:
    limpio = token.strip().strip(".")
    if limpio.isdigit():
        numero = int(limpio)
        return numero if 1 <= numero <= 12 else None
    if limpio in _MESES:
        return _MESES[limpio]
    if limpio in _ABREVIADOS:
        return _ABREVIADOS[limpio]
    if limpio in _ROMANOS:
        return _ROMANOS[limpio]
    return None


def _armar_fecha(orden: str, partes: tuple[str, str, str]) -> date | None:
    try:
        if orden == "ymd":
            anio, mes, dia = int(partes[0]), _mes(partes[1]), int(partes[2])
        elif orden == "dmy":
            dia, mes, anio = int(partes[0]), _mes(partes[1]), int(partes[2])
        else:
            mes, dia, anio = _mes(partes[0]), int(partes[1]), int(partes[2])
        if mes is None:
            return None
        return date(anio, mes, dia)
    except (TypeError, ValueError):
        return None


def _entero_en_espanol(tokens: list[str]) -> int | None:
    total = 0
    actual = 0
    for token in tokens:
        if token == "mil":
            actual = 1000 if actual == 0 else actual * 1000
            total += actual
            actual = 0
        elif token in {"millon", "millones"}:
            actual = 1_000_000 if actual == 0 else actual * 1_000_000
            total += actual
            actual = 0
        elif token in _UNIDADES:
            actual += _UNIDADES[token]
        else:
            return None
    return total + actual
