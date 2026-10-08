"""Búsqueda de los campos en cualquier formato de cheque, sin plantilla fija.

1. Un detector de texto liviano (PP-OCRv6 tiny, ~0,2 s) encuentra todas las cajas de texto.
2. Se leen las cajas y se identifican las ETIQUETAS IMPRESAS que todo cheque ecuatoriano trae
   ("Páguese a la orden de", "La suma de", "US$", "Ciudad y fecha" / "Lugar y fecha",
   "Cheque N°", "Cuenta N°", "Dólares") aunque el OCR las lea con errores.
3. La zona de cada campo se calcula a partir de su etiqueta (a la derecha, encima o debajo según
   lo que haya tinta), y la MICR es la franja inferior con casi todo dígitos.

Todas las coordenadas que devuelve son de la imagen de trabajo (ancho ANCHO_TRABAJO).
"""

import re
from difflib import SequenceMatcher

import cv2
import numpy as np
from rapidocr import ModelType, OCRVersion, RapidOCR

from poc.clasificador import clasificar
from poc.lector import MODELOS
from poc.parsers import normalizar

ANCHO_TRABAJO = 592     # ancho al que se lleva todo cheque (igual que el escaneo de 100 dpi)
ESCALA_DETECCION = 2    # el detector trabaja al doble para no perder letras pequeñas

# Etiquetas impresas: nombre -> formas (texto normalizado, sin espacios)
ETIQUETAS = {
    "paguese": ["paguesea", "pagueseala", "paguese", "paguesealaordende", "paguesealaorden"],
    "orden": ["laordende", "ordende", "alaordende", "laorden"],
    "suma": ["lasumade", "sumade", "lacantidadde", "son"],
    "dolares": ["usdolares", "dolares", "usdolar", "dolaresamericanos"],
    "ciudad": ["ciudad", "ciudadyfecha", "lugaryfecha", "lugaryfechadeemision", "lugar"],
    "fecha": ["yfecha", "fecha", "fechadeemision"],
    "cheque": ["chequen", "chequeno", "chequenro", "cheque", "chn"],
    "cuenta": ["cuentan", "cuentano", "cuenta", "ctacte", "cta"],
    "firma": ["firma", "firmas"],
}
SIMILITUD_ETIQUETA = 0.72
SOLAS = ("firma", "dolares", "fecha")
LIMITE_SUPERIOR = 0.35   # fracción del alto donde están cheque n.º y cuenta
RE_MONEDA = re.compile(r"^(u\.?\s*s\.?\s*[$s5]|usd|\$)", re.I)
BANCOS = [
    "Banco Pichincha", "Banco Guayaquil", "Banco del Pacifico", "Produbanco", "Banco Bolivariano",
    "Banco Internacional", "Banco del Austro", "Banco General Ruminahui", "Banco de Machala", "Banco de Loja",
    "Banco Amazonas", "Banco Solidario", "Banco ProCredit", "Citibank", "Banco Capital", "Banco Diners Club",
    "Banco Comercial de Manabi", "Banco del Litoral", "Banco D-Miro", "Banco Delbank", "BanEcuador",
    "Banco Codesarrollo", "Banco Coopnacional", "Banco Visionfund", "Banco Estudiantil Venus",
]


def preparar_imagen(gris):
    """Imagen de trabajo: el cheque llevado a ANCHO_TRABAJO de ancho (no necesita modelos)."""
    h = round(gris.shape[0] * ANCHO_TRABAJO / gris.shape[1])
    interp = cv2.INTER_AREA if gris.shape[1] > ANCHO_TRABAJO else cv2.INTER_CUBIC
    return cv2.resize(gris, (ANCHO_TRABAJO, h), interpolation=interp)


def _compacto(texto):
    return re.sub(r"[^a-z0-9$]", "", normalizar(texto))


def _parecido_prefijo(compacto, forma):
    """Parecido entre la forma de la etiqueta y el comienzo del texto (la etiqueta puede venir
    pegada a lo escrito a mano: 'lasumadenovecientos...')."""
    if not compacto:
        return 0.0, 0
    mejor, largo = 0.0, 0
    for n in range(max(1, len(forma) - 2), min(len(compacto), len(forma) + 2) + 1):
        r = SequenceMatcher(None, compacto[:n], forma).ratio()
        if r > mejor:
            mejor, largo = r, n
    return mejor, largo


class Caja:
    def __init__(self, puntos, texto, confianza):
        p = np.asarray(puntos, dtype=np.float32) / ESCALA_DETECCION
        self.x0, self.y0 = float(p[:, 0].min()), float(p[:, 1].min())
        self.x1, self.y1 = float(p[:, 0].max()), float(p[:, 1].max())
        self.texto, self.confianza = texto, float(confianza)
        self.compacto = _compacto(texto)
        self.etiqueta = None
        self.fin_etiqueta = self.x1   # x donde termina la etiqueta si viene pegada a lo escrito

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2

    @property
    def alto(self):
        return self.y1 - self.y0

    def __repr__(self):
        return f"Caja({self.texto!r} {self.x0:.0f},{self.y0:.0f}-{self.x1:.0f},{self.y1:.0f} {self.etiqueta})"


class Localizador:
    def __init__(self, modelo_lectura="v6_small", detector="tiny", onnx=None):
        tipo = {"tiny": ModelType.TINY, "small": ModelType.SMALL}[detector]
        params = {"Global.log_level": "error", "Global.use_cls": False,
                  "Det.ocr_version": OCRVersion.PPOCRV6, "Det.model_type": tipo}
        params.update(MODELOS[modelo_lectura])
        params.update(onnx or {})   # hilos / GPU (ver lector.params_onnx); vacío = modo original
        self.motor = RapidOCR(params=params)
        self.motor(np.full((64, 256, 3), 255, np.uint8), use_det=True, use_rec=True, use_cls=False)

    def preparar(self, gris):
        """Imagen de trabajo: el cheque llevado a ANCHO_TRABAJO de ancho."""
        return preparar_imagen(gris)

    def cajas(self, img):
        grande = cv2.resize(img, None, fx=ESCALA_DETECCION, fy=ESCALA_DETECCION, interpolation=cv2.INTER_CUBIC)
        r = self.motor(cv2.cvtColor(grande, cv2.COLOR_GRAY2BGR), use_det=True, use_rec=True, use_cls=False)
        if r.boxes is None:
            return []
        return [Caja(b, t, s) for b, t, s in zip(r.boxes, r.txts, r.scores)]

    # ------------------------------------------------------------------
    def _marcar_etiquetas(self, cajas, alto_imagen):
        """Asigna a cada caja la etiqueta que mejor coincide con su comienzo (si alguna)."""
        for c in cajas:
            if RE_MONEDA.match(normalizar(c.texto).strip()) and "dol" not in c.compacto:
                c.etiqueta = "moneda"
                m = re.match(r"^\W*u\W*s\W*[$s5]?|^\W*usd|^\W*\$", c.texto, re.I)
                largo = len(m.group(0)) if m else 3
                c.fin_etiqueta = c.x0 + (c.x1 - c.x0) * min(1.0, largo / max(len(c.texto), 1))
                continue
            mejor = (0.0, None, 0)
            for nombre, formas in ETIQUETAS.items():
                for f in formas:
                    if len(f) <= 4:   # formas cortas ('cta', 'son'): solo al pie de la letra
                        s, largo = (1.0, len(f)) if c.compacto.startswith(f) else (0.0, 0)
                    else:
                        s, largo = _parecido_prefijo(c.compacto, f)
                    if s > mejor[0]:
                        mejor = (s, nombre, largo)
            # El n.º de cheque y la cuenta están impresos en la franja superior
            if mejor[1] in ("cheque", "cuenta") and c.y1 > LIMITE_SUPERIOR * alto_imagen:
                mejor = (0.0, None, 0)
            # "Firma", "Dólares" y "y fecha" van solas: un texto largo que empieza parecido es manuscrito
            # (ej. "Franklin Moya Zurita" no es "Firma")
            if mejor[1] in SOLAS and len(c.compacto) > mejor[2] + 3:
                mejor = (0.0, None, 0)
            if mejor[0] >= SIMILITUD_ETIQUETA:
                c.etiqueta = mejor[1]
                resto = len(c.compacto) - mejor[2]
                if resto >= 3:   # etiqueta pegada a lo escrito: se corta en proporción a las letras
                    c.fin_etiqueta = c.x0 + (c.x1 - c.x0) * mejor[2] / len(c.compacto)

    @staticmethod
    def _primera(cajas, *nombres):
        cands = [c for c in cajas if c.etiqueta in nombres]
        return min(cands, key=lambda c: (c.y0, c.x0)) if cands else None

    def localizar(self, img):
        """Devuelve (zonas, cajas, info). zonas: nombre -> (x0, y0, x1, y1) en px de la imagen de trabajo."""
        H, W = img.shape
        cajas = self.cajas(img)
        self._marcar_etiquetas(cajas, H)
        etiq = [c for c in cajas if c.etiqueta]
        h = float(np.median([c.alto for c in etiq])) if etiq else 0.05 * H
        izquierda = [c for c in etiq if c.etiqueta in ("paguese", "orden", "suma", "ciudad", "fecha")
                     and c.x0 < 0.2 * W and c.fin_etiqueta == c.x1]
        if izquierda:
            borde = float(np.median([c.x1 for c in izquierda]))
            for c in etiq:
                if c.fin_etiqueta < c.x1 and c.x0 < 0.2 * W:   # pegada: el corte proporcional suele pasarse
                    c.fin_etiqueta = min(c.fin_etiqueta, borde + 0.01 * W)
        zonas, notas, info_extra = {}, [], {}

        def rect(x0, y0, x1, y1):
            x0, x1 = max(0, int(x0)), min(W, int(x1))
            y0, y1 = max(0, int(y0)), min(H, int(y1))
            return (x0, y0, x1, y1) if x1 - x0 > 8 and y1 - y0 > 6 else None

        paguese, orden = self._primera(cajas, "paguese"), self._primera(cajas, "orden")
        moneda = self._primera(cajas, "moneda")
        suma, dolares = self._primera(cajas, "suma"), self._primera(cajas, "dolares")
        ciudad = [c for c in cajas if c.etiqueta in ("ciudad", "fecha")]
        cheque, cuenta = self._primera(cajas, "cheque"), self._primera(cajas, "cuenta")

        # Beneficiario: a la derecha de "Páguese a / la orden de", hasta el US$
        ref = [c for c in (paguese, orden) if c]
        if ref:
            y0 = min(c.y0 for c in ref) - 0.4 * h
            y1 = max(c.y1 for c in ref) + 0.5 * h
            x0 = max(c.fin_etiqueta for c in ref) + 2
            x1 = moneda.x0 - 3 if moneda and moneda.x0 > x0 + 40 else 0.76 * W
            zonas["beneficiario"] = rect(x0, y0, x1, y1)
        else:
            notas.append("no se encontró 'Páguese a la orden de'")

        # Monto en cifras: a la derecha de US$ (con espacio arriba para centavos en superíndice)
        if moneda:
            zonas["monto_numeros"] = rect(moneda.fin_etiqueta + 1, moneda.y0 - 1.3 * h, W, moneda.y1 + 0.6 * h)
        elif ref:
            # Sin "US$" legible: el monto es la tinta con dígitos a la derecha, en el renglón del beneficiario.
            # La zona puede incluir el "US$" impreso; el analizador lo recorta (empieza en el primer dígito)
            y0, y1 = min(c.y0 for c in ref) - 1.0 * h, max(c.y1 for c in ref) + 0.5 * h
            fila0 = min(c.y0 for c in ref)
            # El monto en cifras va en el extremo derecho, después de donde termina el beneficiario
            con_digitos = [c for c in cajas if not c.etiqueta and c.x0 > 0.7 * W and fila0 - 0.5 * h < c.cy < y1
                           and any(ch.isdigit() for ch in c.compacto)]
            x0 = min([c.x0 - 0.12 * W for c in con_digitos] + [0.74 * W])
            zonas["monto_numeros"] = rect(max(x0, 0.6 * W), y0, W, y1)
            info_extra["recortar_prefijo_monto"] = True
            notas.append("no se encontró 'US$': monto en cifras buscado a la derecha del beneficiario")
        else:
            notas.append("no se encontró 'US$'")

        # Monto en letras: renglón de "La suma de" + segundo renglón hasta "Dólares"
        fin_letras = None
        if suma:
            y0, y1 = suma.y0 - 0.7 * h, suma.y1 + 0.5 * h
            derecha = dolares.x0 - 2 if dolares and abs(dolares.cy - suma.cy) < h else W
            # Se empieza un poco antes del fin de la etiqueta: lo escrito suele montarse sobre ella
            zonas["monto_letras"] = rect(suma.fin_etiqueta - 0.03 * W, y0, derecha, y1)
            if dolares and dolares.cy > suma.y1:
                r2 = rect(0, y1, dolares.x0 - 2, dolares.y1 + 0.3 * h)
                fin_letras = dolares.y1 + 0.3 * h
            else:
                r2 = rect(0, y1, 0.9 * W, y1 + 1.4 * h)
                fin_letras = y1 + 1.4 * h
            # Segundo renglón solo si el detector vio texto escrito ahí (no las líneas impresas)
            if r2 and any(not c.etiqueta and r2[0] <= (c.x0 + c.x1) / 2 <= r2[2] and r2[1] <= c.cy <= r2[3]
                          and len(c.compacto) >= 2 for c in cajas):
                zonas["monto_letras_2"] = r2
        else:
            notas.append("no se encontró 'La suma de'")

        # Ciudad y fecha: a la derecha de la etiqueta (Pichincha) o encima de ella (Lugar y fecha...)
        if ciudad:
            ey0, ey1 = min(c.y0 for c in ciudad), max(c.y1 for c in ciudad)
            ex1 = max(c.fin_etiqueta for c in ciudad)
            # "Lugar y fecha de emisión" va DEBAJO de lo escrito; "Ciudad / y fecha" va a la izquierda
            debajo = any("lugar" in c.compacto or "emision" in c.compacto for c in ciudad)
            limite_x = min([c.x0 for c in cajas if c.etiqueta == "firma" and c.x0 > ex1] + [0.62 * W])
            a_la_derecha = [] if debajo else [
                c for c in cajas if not c.etiqueta and (c.x0 + c.x1) / 2 > ex1 and c.x0 < limite_x
                and ey0 - h < c.cy < ey1 + 0.5 * h]
            if a_la_derecha:
                zonas["ciudad_fecha"] = rect(ex1 + 2, ey0 - 0.5 * h, max(c.x1 for c in a_la_derecha) + 6, ey1 + 0.4 * h)
            else:
                arriba = (fin_letras or ey0 - 3 * h)
                x1 = max([c.x1 for c in cajas if not c.etiqueta and arriba - h < c.cy < ey0 and c.x0 < 0.6 * W]
                         or [0.6 * W])
                zonas["ciudad_fecha"] = rect(0, arriba, x1 + 6, ey0 + 0.2 * h)
        else:
            notas.append("no se encontró 'Ciudad y fecha' / 'Lugar y fecha'")

        # N.º de cheque y cuenta impresos: a la derecha de su etiqueta
        for nombre, c in (("cheque_impreso", cheque), ("cuenta_impresa", cuenta)):
            if c:
                zonas[nombre] = rect(c.fin_etiqueta + 1, c.y0 - 0.4 * h, min(W, c.fin_etiqueta + 0.3 * W), c.y1 + 0.4 * h)

        # MICR: franja inferior con casi todo dígitos
        micr = [c for c in cajas if c.cy > 0.75 * H and len(c.compacto) >= 4
                and sum(ch.isdigit() for ch in c.compacto) / len(c.compacto) >= 0.5]
        if micr:
            zonas["micr"] = rect(0, min(c.y0 for c in micr) - 0.3 * h, W, max(c.y1 for c in micr) + 0.3 * h)

        # Banco: caja impresa con "banco" o parecida a un banco conocido
        banco = None
        for c in sorted(cajas, key=lambda c: c.y0)[:8]:
            n = normalizar(c.texto)
            for b in BANCOS:
                if SequenceMatcher(None, n, normalizar(b)).ratio() > 0.8 or (len(n) > 5 and n in normalizar(b)):
                    banco = b
                    break
            if banco:
                break
        if not banco:
            banco = next((c.texto.title() for c in cajas if "banco" in normalizar(c.texto)), None)

        zonas = {k: v for k, v in zonas.items() if v}
        # Por CONTENIDO: lo que dice cada caja manda; las zonas por etiqueta quedan de respaldo
        primeras = {}
        for c in sorted(etiq, key=lambda c: c.y0):
            primeras.setdefault(c.etiqueta, c)
        por_contenido = clasificar(cajas, primeras, W, H, h)
        if "monto_numeros" in por_contenido:
            info_extra.pop("recortar_prefijo_monto", None)
        if "monto_letras" in por_contenido and "monto_letras_2" not in por_contenido:
            zonas.pop("monto_letras_2", None)
        zonas.update(por_contenido)
        fuente = {k: ("contenido" if k in por_contenido else "etiqueta") for k in zonas}
        # Rectángulos de texto impreso (etiquetas y leyendas) para borrarlos de los recortes manuscritos
        from poc.clasificador import es_impreso
        impresos = [(int(c.x0), int(c.y0), int(c.fin_etiqueta if c.etiqueta else c.x1), int(c.y1))
                    for c in cajas if es_impreso(c)]
        # El n.º de cheque y de cuenta impresos también: los centavos en superíndice del monto en cifras
        # quedan a su altura y el recorte del monto alcanza a tomar sus últimos dígitos
        for z in ("cheque_impreso", "cuenta_impresa"):
            if z in zonas:
                x0, y0, x1, y1 = zonas[z]
                impresos += [(int(c.x0), int(c.y0), int(c.x1), int(c.y1)) for c in cajas
                             if not es_impreso(c) and x0 <= (c.x0 + c.x1) / 2 <= x1 and y0 <= c.cy <= y1]
        info_extra["impresos"] = impresos
        info = {"banco_impreso": banco, "notas": notas, **info_extra, "fuente_zonas": fuente,
                "etiquetas": {c.etiqueta: c.texto for c in etiq}, "cajas": len(cajas)}
        return zonas, cajas, info
