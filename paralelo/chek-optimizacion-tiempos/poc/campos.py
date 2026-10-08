"""Interpretación y validación cruzada de cada campo a partir de las lecturas de sus zonas.

Cada función recibe las lecturas (varias versiones de la misma zona) y devuelve un dict:
{valor, confianza, revisar, nota}. Ningún campo se inventa: si no hay una lectura coherente,
el valor queda vacío y marcado para revisar.
"""

import itertools
import math
import re
from collections import Counter
from datetime import date
from difflib import SequenceMatcher, get_close_matches

from poc import parsers
from poc.nombres import APELLIDOS, NOMBRES, PARTICULAS

UMBRAL_REVISAR = 0.80
MARGEN_NOMBRE_OK = 3.0
N_LECTURAS_PRINCIPALES = 3   # las 3 primeras lecturas son del lector principal

CIUDADES = [
    "Quito", "Guayaquil", "Cuenca", "Ambato", "Riobamba", "Loja", "Machala", "Manta", "Portoviejo",
    "Esmeraldas", "Ibarra", "Latacunga", "Quevedo", "Santo Domingo", "Babahoyo", "Milagro", "Tulcan",
    "Otavalo", "Cayambe", "Sangolqui", "Salinas", "La Libertad", "Santa Elena", "Duran", "Daule",
    "Samborondon", "Azogues", "Guaranda", "Puyo", "Tena", "Macas", "Zamora", "Nueva Loja", "Lago Agrio",
    "Coca", "Francisco de Orellana", "Puerto Ayora", "Puerto Baquerizo Moreno", "Chone", "Jipijapa",
    "Montecristi", "Bahia de Caraques", "El Carmen", "Pelileo", "Banos", "Salcedo", "Pujili",
    "Atuntaqui", "Cotacachi", "Huaquillas", "Pasaje", "Santa Rosa", "El Guabo", "Arenillas", "Catamayo",
    "Gualaceo", "Paute", "Cañar", "La Troncal", "Ventanas", "Vinces", "Naranjal", "Playas", "Machachi",
    "Tumbaco", "Cumbaya", "Conocoto", "Rumiñahui", "Yaguachi", "Balzar", "El Empalme", "Pedernales",
]

_UNI = ["", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once",
        "doce", "trece", "catorce", "quince", "dieciseis", "diecisiete", "dieciocho", "diecinueve",
        "veinte", "veintiuno", "veintidos", "veintitres", "veinticuatro", "veinticinco", "veintiseis",
        "veintisiete", "veintiocho", "veintinueve"]
_DEC = ["", "", "", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa"]
_CEN = ["", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos", "seiscientos",
        "setecientos", "ochocientos", "novecientos"]


def _menor_mil(n):
    if n == 100:
        return "cien"
    c, r = divmod(n, 100)
    partes = [_CEN[c]] if c else []
    if r < 30:
        partes.append(_UNI[r])
    else:
        d, u = divmod(r, 10)
        partes.append(_DEC[d] + (f" y {_UNI[u]}" if u else ""))
    return " ".join(p for p in partes if p)


def numero_a_letras(valor):
    """475.60 -> 'cuatrocientos setenta y cinco 60/100' (forma canónica para comparar)."""
    entero, cent = int(valor), round((valor - int(valor)) * 100)
    if entero == 0:
        texto = "cero"
    else:
        millones, resto = divmod(entero, 1_000_000)
        miles, unidades = divmod(resto, 1000)
        partes = []
        if millones:
            partes.append("un millon" if millones == 1 else f"{_menor_mil(millones)} millones")
        if miles:
            partes.append("mil" if miles == 1 else f"{_menor_mil(miles)} mil")
        if unidades:
            partes.append(_menor_mil(unidades))
        texto = " ".join(partes)
    return f"{texto} {cent:02d}/100"


def _sim(a, b):
    return SequenceMatcher(None, a, b).ratio()


def _digitos(texto):
    return re.sub(r"\D", "", (texto or "").translate(parsers.LETRA_A_DIGITO))


def _campo(valor, confianza, nota="", revisar=None, **extra):
    confianza = round(float(confianza), 3)
    if revisar is None:
        revisar = valor in (None, "") or confianza < UMBRAL_REVISAR
    return {"valor": valor, "confianza": confianza, "revisar": bool(revisar), "nota": nota, **extra}


# ---------------------------------------------------------------------------
# MICR, número de cheque, cuenta y banco
# ---------------------------------------------------------------------------

_MICR_A_DIGITO = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "C": "4", "S": "5", "s": "5",
                                "B": "8", "I": "1", "l": "1", "|": "1", "Z": "2", "G": "6", "b": "6"})
BLANCO_MICR = " -=*#^AaKkt⑆⑇⑈⑉:;.,'`\"_~!"


def _tokens_micr(texto):
    return re.findall(r"\d+", (texto or "").translate(_MICR_A_DIGITO))


def _vecinos_texto(d):
    for i in range(len(d)):
        for x in "0123456789":
            if x != d[i]:
                yield d[:i] + x + d[i + 1:]


def _verificar(candidatos, zonas, puntuador):
    """Puntúa candidatos en varias zonas [(matrices, como_blanco, peso)]. Devuelve (mejor, margen, top)."""
    total = {c: sum(peso * puntuador.puntuar(P, c, blanco) for mats, blanco, peso in zonas for P in mats)
             for c in candidatos}
    orden = sorted(total, key=total.get, reverse=True)
    margen = total[orden[0]] - total[orden[1]] if len(orden) > 1 else 99.0
    return orden[0], margen, {c: round(total[c], 2) for c in orden[:3]}


def _numero_verificado(nombre, largo, leidos_impreso, leidos_micr, zonas, puntuador, formato=str):
    base = {d for d in leidos_impreso + leidos_micr if len(d) == largo}
    if not base:
        return _campo(None, 0, f"sin lectura de {largo} dígitos para {nombre}")
    # Candidatos: combinaciones de los dígitos que se vieron en cada posición (impresos son nítidos:
    # basta con resolver las posiciones donde las lecturas no coinciden)
    posiciones = [sorted({d[i] for d in base}) for i in range(largo)]
    candidatos = {"".join(c) for c in itertools.islice(itertools.product(*posiciones), MAX_COMBINACIONES)}
    candidatos |= base
    if len(candidatos) == 1:   # todas las lecturas iguales: se compara contra sus vecinos
        candidatos.update(_vecinos_texto(next(iter(base))))
    mejor, margen, top = _verificar(candidatos, zonas, puntuador)
    impreso_y_micr = mejor in leidos_impreso and mejor in leidos_micr
    conf = 1 - 0.5 * math.exp(-margen / 3)
    if impreso_y_micr:
        conf = max(conf, 0.99)
    # Que lo impreso y la MICR digan lo mismo no basta: con imagen borrosa ambos confunden 8/9/3
    ok = margen >= MARGEN_NUMERO_OK or (impreso_y_micr and margen >= MARGEN_NUMERO_OK / 2)
    nota = ("impreso = MICR; " if impreso_y_micr else "") + f"verificado en la imagen, ventaja {margen:.1f}"
    return _campo(formato(mejor), conf if ok else min(conf, 0.79), nota, revisar=not ok, top3=top)


MARGEN_NUMERO_OK = 4.0
MAX_COMBINACIONES = 64
PESO_IMPRESO = 0.4


def _desde_plantillas(lectura_micr, impreso_cheque, impreso_cuenta):
    """Grupos de la MICR leídos por el lector de plantillas E-13B, si todos son confiables.

    Estructura esperada: cheque (6) · ruta (8) · cuenta (10) · tipo (2) [· serial].
    """
    from poc.micr import grupos
    g = grupos(lectura_micr)
    if len(g) < 4 or [len(x) for x, _ in g[:3]] != [6, 8, 10] or not all(ok for _, ok in g[:4]):
        return None
    cheque, ruta, cuenta, tipo = g[0][0], g[1][0], g[2][0], g[3][0][:2]
    nota = "MICR leída por plantillas E-13B"
    campo_cheque = _campo(cheque, 0.99, nota + ("; = impreso" if cheque in impreso_cheque
                                                 else f"; impreso leído {impreso_cheque[0] if impreso_cheque else '-'}"))
    campo_cuenta = _campo(f"{cuenta[:-2]}-{cuenta[-2:]}", 0.99,
                          nota + ("; = impresa" if cuenta in impreso_cuenta else "; impresa no coincide"))
    micr = _campo(f"{cheque} {ruta} {cuenta} {tipo}", 0.99, nota,
                  grupos={"cheque": cheque, "ruta": ruta, "cuenta": cuenta, "tipo": tipo})
    return micr, campo_cheque, campo_cuenta


def datos_impresos(lect, mats, puntuador, lectura_micr=None):
    """MICR, n.º de cheque y cuenta, cruzando lo impreso arriba con la línea MICR.

    1. Si el lector de plantillas E-13B leyó toda la MICR sin dudas, se usa (es lo más fiable).
    2. Si no, se verifican candidatos con el OCR general sobre la MICR y lo impreso.
    `lect` y `mats` tienen las lecturas y matrices de las zonas micr, cheque_impreso y cuenta_impresa.
    """
    impreso_cheque = [_digitos(l["texto"]) for l in lect["cheque_impreso"]]
    impreso_cuenta = [_digitos(l["texto"]) for l in lect["cuenta_impresa"]]
    if lectura_micr:   # None si la MICR tiene caracteres dudosos (el analizador pasa al OCR general)
        return _desde_plantillas(lectura_micr, impreso_cheque, impreso_cuenta)
    tokens = [_tokens_micr(l["texto"]) for l in lect["micr"]]

    def de_largo(n):
        # Un símbolo MICR (⑈ ⑆) leído como dígito deja el grupo con un dígito de más a un lado
        out = [t for ts in tokens for t in ts if len(t) == n]
        out += [x for ts in tokens for t in ts if len(t) == n + 1 for x in (t[1:], t[:-1])]
        return out
    micr_cheque, micr_ruta, micr_cuenta = de_largo(6), de_largo(8), de_largo(10)
    # Tipo de cuenta: los 2 primeros dígitos del grupo que sigue a la cuenta (a veces pegado al serial)
    micr_tipo = [ts[i + 1][:2] for ts in tokens for i, t in enumerate(ts[:-1])
                 if len(t) in (10, 11) and len(ts[i + 1]) >= 2]

    # La MICR (fuente E-13B, hecha para máquinas) pesa más que lo impreso arriba (matriz de puntos)
    zona_micr = (mats["micr"], BLANCO_MICR, 1.0)
    cheque = _numero_verificado("n.º de cheque", 6, impreso_cheque, micr_cheque,
                                [zona_micr, (mats["cheque_impreso"], " -", PESO_IMPRESO)], puntuador)
    cuenta = _numero_verificado("cuenta", 10, impreso_cuenta, micr_cuenta,
                                [zona_micr, (mats["cuenta_impresa"], " -", PESO_IMPRESO)], puntuador,
                                formato=lambda d: f"{d[:-2]}-{d[-2:]}")
    ruta = _numero_verificado("ruta", 8, [], micr_ruta, [zona_micr], puntuador)
    tipo = Counter(micr_tipo).most_common(1)[0][0] if micr_tipo else None
    partes = [cheque["valor"], ruta["valor"], (cuenta["valor"] or "").replace("-", ""), tipo]
    conf = min(cheque["confianza"], ruta["confianza"], cuenta["confianza"])
    micr = _campo(" ".join(p for p in partes if p) if all(partes) else None, conf,
                  "armada con los grupos verificados", grupos={"cheque": partes[0], "ruta": partes[1],
                                                               "cuenta": partes[2], "tipo": partes[3]})
    return micr, cheque, cuenta


def banco(plantilla, micr):
    ruta = (micr.get("grupos") or {}).get("ruta") or ""
    if ruta.startswith(plantilla["codigo_banco_micr"]):
        return _campo(plantilla["banco"], 0.99, f"plantilla + código {plantilla['codigo_banco_micr']} en la MICR")
    return _campo(plantilla["banco"], 0.85, "según la plantilla (MICR no confirma el código del banco)")


def banco_encontrado(banco_impreso, micr=None):
    """Banco leído en el encabezado; si es Pichincha y la MICR trae su código (10), queda confirmado."""
    ruta = ((micr or {}).get("grupos") or {}).get("ruta") or ""
    if banco_impreso == "Banco Pichincha" and ruta.startswith("10"):
        return _campo(banco_impreso, 0.99, "encabezado + código 10 en la MICR")
    if banco_impreso:
        conocido = banco_impreso.startswith(("Banco", "Produbanco", "Citibank", "BanEcuador"))
        return _campo(banco_impreso, 0.9 if conocido else 0.6, "leído en el encabezado del cheque")
    return _campo(None, 0, "no se encontró el nombre del banco en el encabezado")


def impresos_sin_micr(lect):
    """N.º de cheque y cuenta cuando el cheque no trae MICR: solo lo leído junto a su etiqueta.

    Sin una segunda fuente para cruzar, se aceptan solo si todas las lecturas coinciden con buena confianza.
    """
    salida = []
    for zona, largos, fmt in (("cheque_impreso", range(2, 11), str),
                              ("cuenta_impresa", range(6, 13), lambda d: f"{d[:-2]}-{d[-2:]}")):
        lecturas = lect.get(zona) or []
        digitos = [(_digitos(l["texto"]), l["confianza"]) for l in lecturas]
        validos = [(d, c) for d, c in digitos if len(d) in largos]
        if not validos:
            salida.append(_campo(None, 0, "sin MICR y sin número legible junto a la etiqueta"))
            continue
        conteo = Counter(d for d, _ in validos)
        d, votos = conteo.most_common(1)[0]
        conf = votos / len(lecturas) * min(c for x, c in validos if x == d)
        ok = votos == len(lecturas) and conf >= 0.9
        salida.append(_campo(fmt(d), conf if ok else min(conf, 0.79),
                             f"sin MICR para cruzar; {votos}/{len(lecturas)} lecturas coinciden", revisar=not ok))
    return tuple(salida)


# ---------------------------------------------------------------------------
# Montos: números y letras se validan entre sí
# ---------------------------------------------------------------------------

_CENTAVOS_OCR = re.compile(r"(?<!\d)(\d{2})\s*(?:[/|)(\]\[{}!1lI]\s*){1,3}[0oOcCQ]{2}(?![a-z])"
                           r"|(?<!\d)(\d{2})\s+[cC][oO0](?![a-z])")
# Fragmento de centavos: solo dígitos y letras que el OCR confunde con ellos ('6o100', '601)00')
_FRAGMENTO_CIFRAS = re.compile(r"(?<![a-zA-Z])[\doO][\doOcClI/|)(\]\[]*(?![a-zA-Z])")


def _preparar_letras(texto):
    """Arregla cómo el OCR suele leer 'NN/100' ('601)00', '6o )co') antes de interpretar."""
    t = _FRAGMENTO_CIFRAS.sub(lambda m: m.group(0).replace("o", "0").replace("O", "0")
                              if re.search(r"\d", m.group(0)) else m.group(0), texto)
    return _CENTAVOS_OCR.sub(lambda m: f" {m.group(1) or m.group(2)}/100 ", t)


def _valores_numeros(lecturas):
    """Montos posibles desde la zona de cifras. Centavos en superíndice pueden venir pegados."""
    vals = Counter()
    for l in lecturas:
        t = re.sub(r"^\D*\$?", "", l["texto"])           # quita 'US$' si se coló
        t = re.sub(r"(?<=\d)[cCoODQ]+|[cCoODQ]+(?=\d)", lambda m: "0" * len(m.group(0)), t)   # '24cco' -> '24000'
        v = parsers.parsear_monto(t)
        if v is not None and v > 0:
            vals[v] += l["confianza"]
        # El "$" impreso se lee como 5/S: '5475.60' también puede ser 475.60 (las letras deciden)
        if re.match(r"^[5Ss$]\d{2,}", t):
            v2 = parsers.parsear_monto(t[1:])
            if v2:
                vals[v2] += l["confianza"] * 0.8
        d = _digitos(t)
        if len(d) >= 3:                                   # '47560' -> 475.60 (centavos arriba)
            vals[round(int(d) / 100, 2)] += l["confianza"] * 0.5
    return vals


AJUSTE_LETRAS_MINIMO = float(__import__('os').environ.get('AJUSTE_LETRAS_MINIMO', -0.5))
GLM_PARECIDO_MONTO = 0.75
MONTO_MAXIMO = 999_999_999.99   # hasta cientos de millones
MARGEN_MONTO_OK = 5.0      # diferencia mínima de puntaje entre el 1.º y el 2.º candidato
MAX_CANDIDATOS_LETRAS = 12


def _vecinos(v):
    """Montos que difieren en un dígito (errores típicos del OCR: 4↔9, 7↔1, 3↔8...)."""
    texto = f"{v:.2f}"
    for i, ch in enumerate(texto):
        if ch.isdigit():
            for d in "0123456789":
                if d != ch:
                    nv = float(texto[:i] + d + texto[i + 1:])
                    if nv > 0:
                        yield round(nv, 2)


def formas_letras(v, con_dolares=False, con_con=False):
    """Formas habituales de escribir un monto en letras (sin '/100', que cuenta como vacío).

    475.60 -> 'cuatrocientos setenta y cinco 60', ...; 24000 -> 'veinticuatro mil 00',
    'veinte y cuatro mil', 'veinticuatro mil', ...
    """
    base = numero_a_letras(v).rsplit(" ", 1)[0]
    if re.match(r"mil\b", base):
        bases = [base, "un " + base]
    else:
        bases = [base]
    cc = f"{round((v - int(v)) * 100):02d}"
    colas = [f" {cc}"]
    if con_con:
        colas.append(f" con {cc}")
    if con_dolares:
        colas += [f" dolares {cc}", f" dolares con {cc}"]
    if cc == "00":
        colas.append("")
        if con_dolares:
            colas.append(" dolares")
    else:   # centavos en palabras: "y veinticuatro centavos", "con cincuenta centavos"
        cp = _menor_mil(int(cc))
        colas += [f" y {cp} centavos", f" con {cp} centavos", f" {cc} centavos"]
        if con_dolares:
            colas += [f" dolares y {cp} centavos", f" dolares con {cp} centavos"]
    formas = {b + c for b in bases for c in colas}
    for f in list(formas):   # "veinticuatro" también se escribe "veinte y cuatro"; "dieciseis", "diez y seis"
        formas.add(re.sub(r"\bveinti(\w+)", r"veinte y \1", f))
        formas.add(re.sub(r"\bdieci(\w+)", r"diez y \1", f))
    return sorted(formas)


def formas_cifras(v):
    """'475.60' -> ['47560']; 24000.00 -> ['2400000', '24000'] (centavos a veces no se escriben)."""
    d = f"{v:.2f}".replace(".", "")
    return [d, d[:-2]] if d.endswith("00") else [d]


def montos(lecturas_num, lecturas_letras, matrices_num, matrices_letras, puntuador):
    """Decide el monto puntuando candidatos sobre las dos zonas de la imagen.

    1. Candidatos: lo que se leyó en cifras y en letras, y sus variantes de un dígito.
    2. Cada candidato se puntúa en la zona de cifras ("47560") y los mejores en la zona de
       letras ("cuatrocientos setenta y cinco 60"), con todas sus formas habituales de escritura.
    3. Gana el de mayor puntaje total; la confianza sale de la ventaja sobre el segundo.
    4. Seguridad: un monto que ninguna zona leyó por sí sola nunca se acepta automáticamente.
    """
    num = _valores_numeros(lecturas_num)
    letras_txt = [_preparar_letras(l["texto"]) for l in lecturas_letras]
    let = Counter()
    for l, t in zip(lecturas_letras, letras_txt):
        v = parsers.letras_a_numero(t)
        if v:
            let[v] += l["confianza"]
    leidos_igual = set(num) & set(let)

    base = {v for v in set(num) | set(let) if 0 < v <= MONTO_MAXIMO}
    if not base:
        nota = "sin lectura: " + " | ".join(l["texto"] for l in lecturas_num + lecturas_letras)
        return _campo(None, 0, nota), _campo(None, 0, nota), {"coinciden": False}
    candidatos = set(base)
    for v in base:
        candidatos.update(x for x in _vecinos(v) if x <= MONTO_MAXIMO)

    texto_letras = " ".join(parsers.normalizar(t) for t in letras_txt)
    con_dolares = bool(re.search(r"d[o0]l", texto_letras))
    con_con = bool(re.search(r"\bc[o0]n\b", texto_letras))

    def p_num(v):
        return sum(max(puntuador.puntuar(P, f, " .,-=_~'`^", digitos_manuscritos=True) for f in formas_cifras(v))
                   for P in matrices_num)

    def p_let(v):
        formas = formas_letras(v, con_dolares, con_con)
        return sum(max(puntuador.puntuar(P, f, " /|)(") for f in formas) for P in matrices_letras)

    pn = {v: p_num(v) for v in candidatos}
    finalistas = sorted(candidatos, key=pn.get, reverse=True)[:MAX_CANDIDATOS_LETRAS]
    # También los que más se parecen a lo leído en letras (barato: comparación de textos). Así entra
    # 475.60 aunque la zona de cifras esté sucia, si en letras se leyó algo como "...ntentay einco"
    letras_norm = [parsers.normalizar(t) for t in letras_txt]
    parecido = {v: max(_sim(numero_a_letras(v).rsplit(" ", 1)[0], t) for t in letras_norm) for v in candidatos}
    finalistas = set(finalistas) | set(sorted(candidatos, key=parecido.get, reverse=True)[:MAX_CANDIDATOS_LETRAS // 2])
    finalistas |= base
    pl = {v: p_let(v) for v in finalistas}
    total = {v: pn[v] + pl[v] for v in finalistas}
    orden = sorted(total, key=total.get, reverse=True)
    v = orden[0]
    margen = total[v] - total[orden[1]] if len(orden) > 1 else 99.0
    conf = 1 - 0.5 * math.exp(-margen / 3)
    if v in leidos_igual:
        conf = max(conf, 0.99)
    texto = numero_a_letras(v)
    leido = v in base
    # Ajuste absoluto: puntaje por letra del ganador en la zona de letras (cerca de 0 = encaja bien).
    # Ganarle al 2.º no basta si ninguno encaja (zona mal ubicada, letra ilegible)
    largo = min(len(f.replace(" ", "")) for f in formas_letras(v, con_dolares, con_con))
    ajuste = pl[v] / max(1, len(matrices_letras)) / max(1, largo)
    # Lectura profunda (GLM) del monto en letras parecida a una forma de escribir el candidato:
    # otro modelo, independiente, confirma lo mismo
    glm_letras = [parsers.normalizar(t) for l, t in zip(lecturas_letras, letras_txt) if l.get("variante") == "glm-ocr"]
    glm_confirma = bool(glm_letras) and max(_sim(f, g) for f in formas_letras(v, True, True) for g in glm_letras) >= GLM_PARECIDO_MONTO
    encaja = ajuste >= AJUSTE_LETRAS_MINIMO or glm_confirma
    # El cruce necesita las dos zonas: si en letras no se leyó ni una palabra de número, no hay cruce
    letras_legible = any(parsers.contar_palabras_numericas(parsers.limpiar_monto_letras(t)) >= 2 for t in letras_txt)
    # Centavos sin leer: "475." (separador final sin decimales) indica centavos en superíndice fuera de la
    # zona. Un monto ",00" así no se acepta salvo que las letras digan explícitamente 00/100 o "exactos"
    separador_suelto = any(re.search(r"\d[.,]\s*$", l["texto"].strip()) for l in lecturas_num)
    centavos_explicitos = any(re.search(r"00\s*/\s*100|exact|cero\s+centavos", parsers.normalizar(t)) for t in letras_txt)
    centavos_dudosos = round(v * 100) % 100 == 0 and separador_suelto and not centavos_explicitos
    ok = (encaja and letras_legible and not centavos_dudosos
          and (v in leidos_igual or (leido and margen >= MARGEN_MONTO_OK)))
    val = {"coinciden": ok, "monto_en_letras_esperado": texto, "margen": round(margen, 2),
           "lectura_libre_coincide": v in leidos_igual, "leido_en_alguna_zona": leido,
           "ajuste_letras": round(ajuste, 3), "glm_confirma": glm_confirma,
           "top3": {f"{c:.2f}": round(total[c], 2) for c in orden[:3]}}
    nota = (f"verificado en la imagen: ventaja {margen:.1f} sobre {orden[1]:.2f}" if len(orden) > 1
            else "único candidato")
    if not leido:
        nota += "; ninguna zona lo leyó por sí sola"
    if not encaja:
        nota += f"; encaja mal con lo escrito en letras ({ajuste:.2f} por letra)"
    if not letras_legible:
        nota += "; monto en letras ilegible: sin cruce"
    if centavos_dudosos:
        nota += "; centavos sin leer (posible superíndice fuera de la zona)"
    if not ok:
        conf = min(conf, 0.79)
    return (_campo(f"{v:.2f}", conf, nota, revisar=not ok),
            _campo(texto, conf, nota, revisar=not ok), val)


# ---------------------------------------------------------------------------
# Ciudad y fecha
# ---------------------------------------------------------------------------

# Letras que el OCR lee en lugar de dígitos manuscritos dentro de una fecha ('20a6-0s-29')
_FECHA_OCR = str.maketrans({"o": "0", "O": "0", "D": "0", "l": "1", "I": "1", "|": "1", "i": "1",
                            "Z": "2", "z": "2", "a": "2", "s": "5", "S": "5", "b": "6", "G": "6",
                            "g": "9", "q": "9", "B": "8", "T": "7"})
# El separador "/" manuscrito suele leerse como 1: se prueban también esas lecturas
SEPARADOR_LEIDO_COMO_1 = [
    (r"\b(\d{1,2})[1lI|](\d{1,2})([/\-.])(\d{4})\b", r"\1\3\2\3\4"),   # 01101/2008 -> 01/01/2008
    (r"\b(\d{1,2})([/\-.])(\d{1,2})[1lI|](\d{4})\b", r"\1\2\3\2\4"),   # 20/112018 -> 20/1/2018
    (r"\b(\d{1,2})([/\-.])(\d)1(\d{4})\b", r"\1\2\3\2\4"),
]
_GRUPO_FECHA = re.compile(r"(?<![a-zA-Z])[\doODlIi|ZzasSbGgqBT]{1,4}(?![a-zA-Z])")
BLANCO_FECHA = " -/.,_"
MARGEN_FECHA_OK = 3.0
ANIOS_ATRAS = 10
MARGEN_CIUDAD_OK = 3.0
PARECIDO_CIUDAD_MINIMO = 0.72


def _arreglar_fecha(texto):
    """Corrige letras dentro de grupos numéricos de una fecha ('20a6-0s-29' -> '2026-05-29')."""
    def grupo(m):
        g = m.group(0)
        return g.translate(_FECHA_OCR) if re.search(r"\d", g) else g
    return _GRUPO_FECHA.sub(grupo, texto)


def _orden_fecha(texto_fecha):
    """'2026-05-29' -> ('a', 'm', 'd'); '29/05/2026' -> ('d', 'm', 'a'). None si no son 3 grupos numéricos."""
    grupos = re.findall(r"\d+", texto_fecha)
    if len(grupos) != 3:
        return None
    return ("a", "m", "d") if len(grupos[0]) == 4 else ("d", "m", "a")


def _escribir_fecha(d, orden, ceros=True):
    if ceros:
        partes = {"a": f"{d.year:04d}", "m": f"{d.month:02d}", "d": f"{d.day:02d}"}
    else:
        partes = {"a": f"{d.year:04d}", "m": str(d.month), "d": str(d.day)}
    return "".join(partes[k] for k in orden)


def _formas_fecha(d, orden):
    return {_escribir_fecha(d, orden, True), _escribir_fecha(d, orden, False)}


def _vecinas(d, orden):
    """Fechas válidas que difieren en un dígito de la escrita."""
    texto = _escribir_fecha(d, orden)
    for alt in _vecinos_texto(texto):
        pos = 0
        vals = {}
        for k in orden:
            n = 4 if k == "a" else 2
            vals[k] = int(alt[pos:pos + n])
            pos += n
        try:
            yield date(vals["a"], vals["m"], vals["d"])
        except ValueError:
            continue


def buscar_fecha_texto(texto):
    from poc.clasificador import buscar_fecha
    r = buscar_fecha(texto)
    return r[0] if r else None


def _fecha_glm(texto):
    """Fecha leída por GLM, tal cual: solo letras dentro de números ('2o25' -> 2025) y meses en palabras.
    No se reinterpreta la barra como 1: GLM lee bien los separadores."""
    t = _arreglar_fecha(re.sub(r"(?<=[A-Za-z.])(?=\d)", " ", texto or ""))
    r = parsers.buscar_fecha(t)
    if r:
        return r[0]
    from poc.clasificador import buscar_fecha
    r = buscar_fecha(texto or "")   # meses en palabras con errores ("diciembe")
    return r[0] if r else None


def _fecha(lecturas, mats, puntuador, hoy):
    glm = [l for l in lecturas if l.get("variante") == "glm-ocr"]
    d_glm = _fecha_glm(glm[0]["texto"]) if glm else None
    if d_glm:
        rapidas = set()
        for l in lecturas:
            if l in glm:
                continue
            t = _arreglar_fecha(re.sub(r"(?<=[A-Za-z.])(?=\d)", " ", l["texto"]))
            for alt in [t] + [re.sub(pt, c, t) for pt, c in SEPARADOR_LEIDO_COMO_1]:
                r = parsers.buscar_fecha(alt)
                if r:
                    rapidas.add(r[0])
        plausible = hoy.year - ANIOS_ATRAS <= d_glm.year <= hoy.year + 1
        confirma = d_glm in rapidas
        ok = plausible and confirma
        nota = ("fecha de GLM-OCR tal cual" + ("; confirmada por el lector rápido" if confirma else "; el lector rápido no la confirma")
                + ("" if plausible else f"; año fuera de rango ({hoy.year - ANIOS_ATRAS}-{hoy.year + 1})"))
        return _campo(d_glm.isoformat(), 0.95 if ok else 0.7, nota, revisar=not ok,
                      posdatado=d_glm > hoy, dias_desde_emision=(hoy - d_glm).days)
    return _fecha_sin_glm(lecturas, mats, puntuador, hoy)


def _fecha_sin_glm(lecturas, mats, puntuador, hoy):
    leidas, orden = Counter(), None
    for l in lecturas:
        t = _arreglar_fecha(re.sub(r"(?<=[A-Za-z.])(?=\d)", " ", l["texto"]))
        # Separador leído como 1/l/I: '01101/2008' -> '01/01/2008', '01/01l2008' -> '01/01/2008'
        alternativas = [t] + [re.sub(patron, cambio, t) for patron, cambio in SEPARADOR_LEIDO_COMO_1]
        vistas = set()
        for k, alt in enumerate(alternativas):
            r = parsers.buscar_fecha(alt)
            if r and r[0] not in vistas:
                vistas.add(r[0])
                leidas[r[0]] += 1 if k == 0 else 0.5
                orden = orden or _orden_fecha(alt[r[1]:r[2]])
    if not leidas:
        return _campo(None, 0, "sin fecha válida: " + " | ".join(l["texto"] for l in lecturas))
    extra = lambda d: {"posdatado": d > hoy, "dias_desde_emision": (hoy - d).days}   # noqa: E731
    if not orden or not mats:   # fecha con el mes en letras: se decide por votación
        d, votos = leidas.most_common(1)[0]
        glm = [l for l in lecturas if l.get("variante") == "glm-ocr"]
        r_glm = buscar_fecha_texto(glm[0]["texto"]) if glm else None
        ok = votos >= 2 and r_glm == d and hoy.year - ANIOS_ATRAS <= d.year <= hoy.year + 1
        return _campo(d.isoformat(), 0.95 if ok else min(votos / len(lecturas), 0.79),
                      "por votación entre lecturas" + ("; confirmada por la lectura profunda" if ok else ""),
                      revisar=not ok, **extra(d))
    candidatos = set(leidas)
    for d in list(leidas):
        candidatos.update(_vecinas(d, orden))
    # Fechas plausibles en un cheque que se está procesando hoy
    candidatos = {d for d in candidatos if hoy.year - ANIOS_ATRAS <= d.year <= hoy.year + 1} | set(leidas)
    total = {d: sum(max(puntuador.puntuar(P, f, BLANCO_FECHA, digitos_manuscritos=True) for f in _formas_fecha(d, orden))
                    for P in mats)
             for d in candidatos}
    rank = sorted(total, key=total.get, reverse=True)
    es_plausible = lambda x: hoy.year - ANIOS_ATRAS <= x.year <= hoy.year + 1   # noqa: E731
    if not es_plausible(rank[0]) and any(es_plausible(x) for x in rank):
        rank = sorted(rank, key=lambda x: (not es_plausible(x), -total[x]))   # la plausible mejor, primero
    d = rank[0]
    margen = total[d] - total[rank[1]] if len(rank) > 1 else 99.0
    unanime = leidas.get(d, 0) >= len(lecturas)
    # Una fecha fuera de rango (año 2076, 7019) se informa tal como se leyó, pero nunca es automática
    plausible = es_plausible(d)
    leida_tal_cual = d in leidas
    ok = plausible and leida_tal_cual and (unanime or margen >= MARGEN_FECHA_OK)
    conf = max(1 - 0.5 * math.exp(-margen / 2), 0.99 if unanime else 0)
    return _campo(d.isoformat(), conf if ok else min(conf, 0.79),
                  f"verificada en la imagen, ventaja {margen:.1f} sobre {rank[1] if len(rank) > 1 else '-'}"
                  + ("" if plausible else f"; año fuera de rango ({hoy.year - ANIOS_ATRAS}-{hoy.year + 1})")
                  + ("" if leida_tal_cual else "; propuesta: lo leído tenía un año imposible"),
                  revisar=not ok, **extra(d))


def _texto_ciudad(texto):
    """Lo escrito antes de la fecha, sin la etiqueta impresa ('Ciudad y fecha', 'Lugar y fecha')."""
    antes = re.split(r"\d", texto or "")[0]
    antes = re.sub(r"(?i)^\W*(ciudad\s*(y\s*fecha)?|lugar\s*y\s*fecha(\s*de\s*emisi[oó]n)?)\W*", "", antes)
    return re.sub(r"[^A-Za-zÁÉÍÓÚÑÜáéíóúñü .]", "", antes).strip(" .,")


def _ciudad(lecturas, mats=None, puntuador=None):
    """Ciudad TAL CUAL se leyó (sin lista de ciudades ni correcciones).

    Con lectura profunda se usa el texto de GLM-OCR; si no, la lectura del lector rápido que más se repite.
    Se marca para revisar si las lecturas no coinciden entre sí.
    """
    glm = [l for l in lecturas if l.get("variante") == "glm-ocr"]
    otras = [_texto_ciudad(l["texto"]) for l in lecturas if l not in glm]
    otras = [o for o in otras if o]
    if glm and _texto_ciudad(glm[0]["texto"]):
        valor = _texto_ciudad(glm[0]["texto"])
        coincidencia = max((_sim(parsers.normalizar(valor), parsers.normalizar(o)) for o in otras), default=0.0)
        return _campo(valor, 0.9 if coincidencia >= 0.7 else 0.6,
                      f"texto de GLM-OCR tal cual; coincide {coincidencia:.0%} con el lector rápido",
                      revisar=coincidencia < 0.7)
    if not otras:
        return _campo(None, 0, "no se leyó texto antes de la fecha")
    valor, votos = Counter(otras).most_common(1)[0]
    return _campo(valor, 0.6, f"lectura del lector rápido ({votos}/{len(otras)} iguales), sin lectura profunda",
                  revisar=True)


def ciudad_fecha(lecturas, mats=None, puntuador=None, hoy=None):
    hoy = hoy or date.today()
    return _ciudad(lecturas, mats, puntuador), _fecha(lecturas, mats, puntuador, hoy)



# ---------------------------------------------------------------------------
# Beneficiario (pendiente: por ahora solo la mejor lectura, siempre a confirmar si duda)
# ---------------------------------------------------------------------------

def _palabras_nombre(texto):
    """Palabras de un nombre leído: sin la etiqueta impresa, sin dígitos ni signos."""
    t = re.sub(r"^.*?(orden\s*de|ordende|ala\s*orden)\s*", "", texto or "", flags=re.I)
    t = re.sub(r"(?i)\bus\W*\$.*$", "", t)            # lo que va desde el US$ es el monto
    t = re.sub(r"[^A-Za-zÁÉÍÓÚÑÜáéíóúñü ]", " ", t)
    palabras = [w for w in t.split() if len(w) >= 2 or w.lower() in PARTICULAS]
    # Restos de la etiqueta mal leída al inicio ("a la oden de", "paguese")
    if len(palabras) > 2 and parsers.normalizar(palabras[1]) == "de" and _sim(parsers.normalizar(palabras[0]), "orden") >= 0.4:
        palabras = palabras[2:]   # "GROEM DE ..." = "orden de" mal leído
    while palabras and (parsers.normalizar(palabras[0]) in ("a", "la", "al", "de")
                        or max(_sim(parsers.normalizar(palabras[0]), e) for e in ("orden", "paguese", "ordende")) >= 0.6):
        palabras.pop(0)
    return palabras


_DICCIONARIO = {}


def _diccionario():
    """Nombres, apellidos y partículas indexados por su forma normalizada (sin tildes, minúsculas)."""
    if not _DICCIONARIO:
        for w in NOMBRES + APELLIDOS:
            _DICCIONARIO[parsers.normalizar(w)] = w
        for w in PARTICULAS:
            _DICCIONARIO[w] = w
    return _DICCIONARIO


def _separar_pegadas(palabra, dic):
    """'Camilasalaga' -> ['Camila', 'salaga'] si ambas partes se parecen a nombres del diccionario."""
    n = parsers.normalizar(palabra)
    if len(n) < 10 or n in dic:
        return [palabra]
    claves = list(dic)
    mejor, corte = 0.0, None
    for i in range(3, len(n) - 2):
        a = get_close_matches(n[:i], claves, n=1, cutoff=0.7)
        b = get_close_matches(n[i:], claves, n=1, cutoff=0.7)
        if a and b:
            s = _sim(n[:i], a[0]) + _sim(n[i:], b[0])
            if s > mejor:
                mejor, corte = s, i
    return [palabra[:corte], palabra[corte:]] if corte else [palabra]


def _alinear(base, otra):
    """Para cada palabra de `base`, la palabra más parecida de `otra` (o None)."""
    salida = []
    for w in base:
        nw = parsers.normalizar(w)
        mejor = max(otra, key=lambda x: _sim(nw, parsers.normalizar(x)), default=None)
        salida.append(mejor if mejor and _sim(nw, parsers.normalizar(mejor)) >= 0.45 else None)
    return salida


def beneficiario(lecturas, mats=None, puntuador=None):
    """Beneficiario palabra por palabra: candidatos de todas las lecturas + diccionario, verificados en la imagen.

    Una palabra es confiable si es un nombre/apellido conocido y le gana con ventaja a las demás opciones,
    o si todas las lecturas coinciden exactamente. El nombre es automático solo si todas sus palabras lo son.
    """
    # Con lectura profunda: el beneficiario es el texto de GLM TAL CUAL (solo sin la etiqueta impresa
    # ni el "US$..." que se haya colado). No se corrige con diccionario ni con otras lecturas.
    glm = [l for l in lecturas if l.get("variante") == "glm-ocr" and l["texto"].strip()]
    if glm:
        literal = re.sub(r"(?i)^\W*(p[aá]guese\s*a\s*)?(la\s*)?orden\s*de\W*", "", glm[0]["texto"].strip())
        literal = re.sub(r"(?i)\s*u\.?\s*s\.?\s*\$.*$", "", literal).strip(" .,-_")
        otras = [parsers.normalizar(" ".join(_palabras_nombre(l["texto"]))) for l in lecturas if l is not glm[0]]
        coincidencia = max((_sim(parsers.normalizar(literal), o) for o in otras if o), default=0.0)
        nota = f"texto de GLM-OCR tal cual; coincide {coincidencia:.0%} con el lector rápido"
        return _campo(literal or None, 0.9 if coincidencia >= 0.7 else 0.6, nota, revisar=coincidencia < 0.7 or not literal)
    dic = _diccionario()
    leidas = [([x for w in _palabras_nombre(l["texto"]) for x in _separar_pegadas(w, dic)], l["confianza"])
              for l in lecturas]
    leidas = [(p, c) for p, c in leidas if p]
    if not leidas:
        return _campo(None, 0, "sin texto legible junto a 'Páguese a la orden de'")
    # Base: la lectura más confiable del lector principal (las primeras); el segundo lector solo aporta
    # candidatos por palabra. Palabras repetidas seguidas (efecto de separar pegadas) se quitan
    principales = leidas[:N_LECTURAS_PRINCIPALES] or leidas
    base = max(principales, key=lambda pc: (pc[1], len(pc[0])))[0]
    base = [w for i, w in enumerate(base) if i == 0 or parsers.normalizar(w) != parsers.normalizar(base[i - 1])]
    alineadas = [_alinear(base, p) for p, _ in leidas]

    palabras, confs, notas = [], [], []
    for i, w in enumerate(base):
        vistas = [a[i] for a in alineadas if a[i]]
        candidatos = {}
        for v in vistas:
            candidatos.setdefault(parsers.normalizar(v), v)
            for m in get_close_matches(parsers.normalizar(v), list(dic), n=3, cutoff=0.6):
                candidatos.setdefault(m, dic[m])
        unanime = len({parsers.normalizar(v) for v in vistas}) == 1 and len(vistas) == len(leidas)
        # Si alguna lectura se parece a un nombre/apellido conocido, se elige entre esos (el puntaje sobre la
        # imagen usa el modelo rápido, que tiende a preferir sus propios errores: "Gracc" sobre "Grace")
        del_diccionario = {k: v for k, v in candidatos.items() if k in dic}
        if del_diccionario:
            candidatos = del_diccionario
        if mats and puntuador and len(candidatos) > 1:
            puntos = {k: sum(puntuador.puntuar(P, k, " ") for P in mats) for k in candidatos}
            rank = sorted(puntos, key=puntos.get, reverse=True)
            elegido, margen = rank[0], puntos[rank[0]] - puntos[rank[1]]
        else:
            elegido, margen = next(iter(candidatos)), (99.0 if unanime else 0.0)
        conocido = elegido in dic
        ok = (conocido and margen >= MARGEN_NOMBRE_OK) or (unanime and len(elegido) >= 3)
        texto = dic.get(elegido) or candidatos[elegido].capitalize()
        palabras.append(texto.lower() if texto.lower() in PARTICULAS and i > 0 else texto)
        confs.append((1 - 0.5 * math.exp(-margen / 2)) if ok else 0.6)
        if not ok:
            notas.append(f"'{texto}' dudosa" + ("" if conocido else " (no está en el diccionario)"))
    sin_repetir = [(w, c) for i, (w, c) in enumerate(zip(palabras, confs))
                   if i == 0 or parsers.normalizar(w) != parsers.normalizar(palabras[i - 1])]
    palabras, confs = [w for w, _ in sin_repetir], [c for _, c in sin_repetir]
    valor = " ".join(palabras)
    ok_total = all(c > 0.79 for c in confs) and len(palabras) >= 2
    nota = "verificado palabra por palabra con " + f"{len(leidas)} lecturas" + (f"; {', '.join(notas)}" if notas else "")
    return _campo(valor, min(confs) if ok_total else min(min(confs), 0.79), nota, revisar=not ok_total)
