"""Ubicación de los campos POR CONTENIDO, no por posición.

Cada caja de texto que encontró el detector se clasifica según lo que dice:
- una fecha (dd/mm/aaaa, "24 diciembre 2024", con errores de OCR) -> fecha (+ ciudad antes de ella)
- palabras de número ("mil", "trescientos", "centavos") -> monto en letras (todas las cajas, en cualquier renglón)
- casi todo dígitos -> monto en cifras (+ cajas chicas vecinas: centavos en superíndice)
- nombres/apellidos o palabras en mayúscula sin números -> beneficiario
- texto impreso conocido (banco, leyendas, etiquetas) -> se descarta

La posición solo desempata (pequeño bono si la caja está cerca de su etiqueta). Así funciona aunque
la persona escriba fuera de la línea, en otro renglón o con otro diseño de cheque.
"""

import copy
import re
from difflib import SequenceMatcher, get_close_matches

import numpy as np

from poc import parsers
from poc.nombres import APELLIDOS, NOMBRES, PARTICULAS

# Texto impreso que nunca es un dato escrito a mano
IMPRESO = ("banco", "compania", "anonima", "invadir", "rasgos", "caligraf", "sellos", "superintendencia",
           "formulario", "agencia", "didactico", "comercial", "ctacte", "valor", "seguros")
PALABRAS_NUMERO = sorted(parsers.PALABRAS_NUMERICAS | {"centavos", "centavo", "dolares", "dolar", "cientos"})
MESES = sorted(parsers.MESES)
DICCIONARIO = {parsers.normalizar(w) for w in NOMBRES + APELLIDOS}


def _palabras(texto):
    return re.findall(r"[a-záéíóúñü]+", parsers.normalizar(texto))


def _sin_etiqueta(caja):
    """Texto de la caja sin la etiqueta impresa del comienzo (proporción de caracteres)."""
    frac = (caja.fin_etiqueta - caja.x0) / max(1.0, caja.x1 - caja.x0)
    return caja.texto[int(round(frac * len(caja.texto))):].strip()


LEYENDAS = ("companiaanonima", "bancoestudiantilvenus", "noinvadirestazonaconrasgoscaligraficosnisellos",
            "lugaryfechadeemision", "paguesealaordende", "usdolares")


def es_impreso(caja):
    if caja.etiqueta is not None or any(p in caja.compacto for p in IMPRESO):
        return True
    # leyendas impresas mal leídas ("COMPANA ANONMA")
    return len(caja.compacto) >= 8 and any(SequenceMatcher(None, caja.compacto, l).ratio() >= 0.7 for l in LEYENDAS)


def puntaje_letras(texto):
    """Cantidad de palabras de número (con tolerancia a errores de lectura)."""
    n = 0
    for w in _palabras(texto):
        if len(w) >= 3 and (w in PALABRAS_NUMERO or get_close_matches(w, PALABRAS_NUMERO, n=1, cutoff=0.78)):
            n += 1
    return n


def buscar_fecha(texto):
    """(fecha, inicio) si el texto contiene una fecha, tolerando errores de OCR y meses mal leídos."""
    from poc.campos import SEPARADOR_LEIDO_COMO_1, _arreglar_fecha
    t = _arreglar_fecha(re.sub(r"(?<=[A-Za-z.])(?=\d)", " ", texto))
    # meses en palabras mal leídos: "eneco" -> "enero"
    t = re.sub(r"[A-Za-záéíóúñ]{3,}", lambda m: (get_close_matches(parsers.normalizar(m.group(0)), MESES, n=1, cutoff=0.7)
                                                  or [m.group(0)])[0], t)
    for alt in [t] + [re.sub(p, c, t) for p, c in SEPARADOR_LEIDO_COMO_1]:
        r = parsers.buscar_fecha(alt)
        if r:
            return r[0], r[1]
    return None


def puntaje_cifras(texto):
    alnum = re.sub(r"[^0-9a-zA-Z]", "", texto)
    digitos = sum(c.isdigit() for c in alnum)
    if digitos < 2 or digitos / max(1, len(alnum)) < 0.6:
        return 0.0
    return 2.0 + (1.0 if re.search(r"\d[.,]\s*\d", texto) else 0.0) + (0.5 if "$" in texto else 0.0)


def puntaje_nombre(texto):
    palabras = [w for w in re.findall(r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü]{2,}", texto)]
    if not palabras or re.search(r"\d", texto) or puntaje_letras(texto) >= max(1, len(palabras) // 2):
        return 0.0
    en_dic = sum(1 for w in palabras if parsers.normalizar(w) in DICCIONARIO
                 or get_close_matches(parsers.normalizar(w), DICCIONARIO, n=1, cutoff=0.8))
    mayus = sum(1 for w in palabras if w[0].isupper())
    return 1.0 + 1.5 * en_dic + 0.3 * mayus + 0.3 * min(len(palabras), 4)


def _union(cajas, W, H, h, margen_y=0.35):
    x0 = min(c.x0 for c in cajas) - 4
    x1 = max(c.x1 for c in cajas) + 4
    y0 = min(c.y0 for c in cajas) - margen_y * h
    y1 = max(c.y1 for c in cajas) + margen_y * h
    return (max(0, int(x0)), max(0, int(y0)), min(W, int(x1)), min(H, int(y1)))


def _renglones(cajas, h):
    """Agrupa cajas en renglones (por altura del centro) y las ordena de arriba abajo, izquierda a derecha."""
    filas = []
    for c in sorted(cajas, key=lambda c: c.cy):
        if filas and abs(c.cy - np.mean([x.cy for x in filas[-1]])) < 0.7 * h:
            filas[-1].append(c)
        else:
            filas.append([c])
    return [sorted(f, key=lambda c: c.x0) for f in filas]


def clasificar(cajas, etiquetas, W, H, h):
    """Devuelve (zonas, fuente) con las zonas encontradas por contenido. etiquetas: nombre -> Caja."""
    # Cajas con la etiqueta pegada a lo escrito ("LA SUMA DE veinticinco...", "US$ 25,40"): la parte
    # escrita a mano se clasifica como cualquier otra caja
    partes = []
    for c in cajas:
        if c.etiqueta and c.fin_etiqueta < c.x1 - 12:
            p = copy.copy(c)
            p.etiqueta, p.x0 = None, c.fin_etiqueta
            p.texto = _sin_etiqueta(c)
            p.compacto = re.sub(r"[^a-z0-9$]", "", parsers.normalizar(p.texto))
            if p.compacto:
                partes.append(p)
    libres = [c for c in cajas + partes if not es_impreso(c) and c.cy < 0.82 * H and len(c.compacto) >= 1]
    zonas, usadas = {}, set()

    def alto_manuscrito(c):
        return 1.0 if c.alto > 1.25 * h else 0.0

    def cerca(c, nombre, dx=0.45, dy=2.5):
        e = etiquetas.get(nombre)
        return e is not None and abs(c.cy - e.cy) < dy * h and -0.05 * W < c.x0 - e.fin_etiqueta < dx * W

    # 1. Fecha (y ciudad antes de ella, en la misma caja o en la vecina de la izquierda)
    fechas = []
    for c in libres:
        r = buscar_fecha(c.texto)
        forma = re.search(r"\d{1,4}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{1,4}", c.texto)   # "226-05-29": año incompleto
        if r or forma:
            p = (2 if r else 1.5) + (1 if cerca(c, "ciudad") or cerca(c, "fecha") else 0)
            # lo escrito a mano es bastante más alto que lo impreso (ej. la fecha impresa de la agencia)
            p += 2 * alto_manuscrito(c) - (2 if c.alto < 1.15 * h else 0)
            fechas.append((p, c))
    if fechas:
        _, cf = max(fechas, key=lambda x: (x[0], -x[1].y0))
        grupo = [cf] + [c for c in libres if c is not cf and abs(c.cy - cf.cy) < 0.7 * h
                        and cf.x0 - 0.35 * W < c.x1 <= cf.x0 + 4 and not re.search(r"\d", c.texto)]
        zonas["ciudad_fecha"] = _union(grupo, W, H, h)
        usadas.update(id(c) for c in grupo)

    # 2. Monto en letras: todas las cajas con palabras de número, por renglones
    letras = [c for c in libres if id(c) not in usadas and puntaje_letras(c.texto) >= 1 and puntaje_cifras(c.texto) == 0]
    if letras:
        filas = _renglones(letras, h)
        # Lo que sigue a la derecha en el mismo renglón es parte del monto aunque no tenga palabras de
        # número: los centavos ("60/100", "con 60 ctvs.") que el OCR lee como basura ("Go1)ce")
        fila0 = filas[0]
        cy0 = np.mean([c.cy for c in fila0])
        while True:
            fin = max(c.x1 for c in fila0)
            sigue = [c for c in libres if id(c) not in usadas and c not in fila0 and abs(c.cy - cy0) < 0.7 * h
                     and fin - 6 <= c.x0 <= fin + 0.12 * W]
            if not sigue:
                break
            fila0 = fila0 + [min(sigue, key=lambda c: c.x0)]
        zonas["monto_letras"] = _union(fila0, W, H, h)
        # Segundo renglón: solo el que sigue de cerca (no una leyenda impresa más abajo que el OCR leyó
        # parecida a un número, ej. "...sellos" -> "seis")
        siguientes = [f for f in filas[1:3] if np.mean([c.cy for c in f]) - cy0 < 2.5 * h]
        if siguientes:
            zonas["monto_letras_2"] = _union([c for f in siguientes for c in f], W, H, h)
        letras = fila0 + [c for f in siguientes for c in f]
        usadas.update(id(c) for c in letras)

    # 3. Monto en cifras: la caja más "numérica" (fuera del encabezado del n.º de cheque) + vecinas chicas
    cifras = []
    for c in libres:
        if id(c) in usadas or cerca(c, "cheque", dx=0.35, dy=1.6) or c.cy < 0.12 * H:
            continue
        p = puntaje_cifras(c.texto)
        if p:
            p += alto_manuscrito(c) - (1.5 if c.alto < 1.15 * h else 0)
            p += 1.5 if cerca(c, "moneda", dx=0.4, dy=1.5) else 0
            p += 0.5 if c.x0 > 0.55 * W else 0
            cifras.append((p, c))
    if cifras:
        _, cc = max(cifras, key=lambda x: x[0])
        # centavos en superíndice o separados: cajas con dígitos a la derecha, en el mismo renglón o un poco arriba.
        # El superíndice suele montarse sobre el final de la cifra ("475." termina en 524 y "60" empieza en 514):
        # basta con que empiece en la mitad derecha de la cifra y termine más allá de ella
        vecinas = [c for c in libres if c is not cc and id(c) not in usadas and re.search(r"\d", c.texto)
                   and (cc.x0 + cc.x1) / 2 <= c.x0 <= cc.x1 + 0.15 * W and c.x1 > cc.x1
                   and cc.y0 - 1.2 * h <= c.cy <= cc.y1]
        zonas["monto_numeros"] = _union([cc] + vecinas, W, H, h, margen_y=0.6)
        usadas.update(id(c) for c in [cc] + vecinas)

    # 4. Beneficiario: el texto con más pinta de nombre (bono si está cerca de "orden de").
    # Orden de todo cheque: va DEBAJO de "Páguese a" (no en el encabezado) y ENCIMA del monto en letras
    techo = etiquetas["paguese"].y0 - 1.2 * h if etiquetas.get("paguese") else 0.12 * H
    piso = min([c.y0 for c in letras] + ([etiquetas["suma"].cy] if etiquetas.get("suma") else []) + [H])
    nombres = []
    for c in libres:
        if id(c) in usadas or c.cy < techo or c.cy > piso:
            continue
        p = puntaje_nombre(c.texto)
        if p:
            p += alto_manuscrito(c) - (2 if c.alto < 1.15 * h else 0)
            p += 2.0 if (cerca(c, "orden") or cerca(c, "paguese")) else 0
            nombres.append((p, c))
    if nombres:
        _, cn = max(nombres, key=lambda x: x[0])
        grupo = [cn] + [c for c in libres if c is not cn and id(c) not in usadas and abs(c.cy - cn.cy) < 0.6 * h
                        and puntaje_nombre(c.texto) > 0 and abs(c.x0 - cn.x1) < 0.12 * W]
        zonas["beneficiario"] = _union(grupo, W, H, h)
    return zonas
