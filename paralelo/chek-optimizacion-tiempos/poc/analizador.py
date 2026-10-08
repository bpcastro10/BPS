"""Análisis de un lado del cheque según la lista de selección, midiendo el tiempo de cada paso.

Los campos se BUSCAN en cada cheque (poc/localizador.py), no se toman de una plantilla fija:
así sirve para cualquier formato que traiga las etiquetas impresas habituales.
"""

import time
from pathlib import Path

import cv2
import numpy as np

from poc import campos
from poc.ctc import Matriz, Puntuador
from poc.lector import VARIANTES, Lector, params_onnx, proporcion_tinta, quitar_impreso_a_la_izquierda
from poc.localizador import ANCHO_TRABAJO, Localizador
from poc.micr import LectorMICR
from poc.plantilla import PICHINCHA_V1, Plantilla, leer_gris

# Si el segundo renglón del monto en letras tiene menos tinta que esto, está vacío
TINTA_MINIMA_RENGLON = 0.004
# Ancho mínimo de la imagen original (por debajo, los dígitos impresos ya se confunden)
ANCHO_MINIMO_PX = 0.85 * ANCHO_TRABAJO
# Versiones de cada zona que se leen y se usan para verificar candidatos
VARIANTES_TEXTO = ("limpio_x3", "gris_x3", "limpio_x2")
VARIANTES_VERIFICACION = ("limpio_x3", "gris_x3")

# Tiempo que puede tomar cada paso en el peor caso medido (3 núcleos); se usa para no pasarse
COSTO_ESTIMADO_S = {"micr_cheque_cuenta_banco": 1.5, "montos": 4.0, "ciudad_fecha": 1.0, "beneficiario": 1.5}
# Zonas manuscritas donde se suma el segundo lector
ZONAS_SEGUNDO_LECTOR = {"monto_letras", "monto_numeros", "ciudad_fecha", "beneficiario"}
CAMPOS_DEL_PASO = {"micr_cheque_cuenta_banco": ["micr", "numero_cheque", "cuenta", "banco"],
                   "montos": ["monto_numeros", "monto_letras"], "ciudad_fecha": ["ciudad", "fecha"],
                   "beneficiario": ["beneficiario"]}
# Zona que necesita cada paso (si el localizador no la encontró, sus campos van a revisión)
ZONA_DEL_PASO = {"montos": ["monto_letras", "monto_numeros"], "ciudad_fecha": ["ciudad_fecha"],
                 "beneficiario": ["beneficiario"]}
# Zona que lee GLM para cada paso, en el orden en que se apilan las tiras
ZONA_GLM_DEL_PASO = {"beneficiario": "beneficiario", "montos": "monto_letras", "ciudad_fecha": "ciudad_fecha"}


def _unir_renglones(a, b):
    """Pone el segundo renglón a continuación del primero (misma altura) para leerlos como uno."""
    alto = a.shape[0]
    b = cv2.resize(b, (max(1, round(b.shape[1] * alto / b.shape[0])), alto))
    return np.hstack([a, b])


class Analizador:
    def __init__(self, config, raiz="."):
        t = time.perf_counter()
        self.config = config
        modelo = config.get("modelo_lectura", "v6_small")
        # Dónde corre este proceso (lo arma poc/arranque.py). Sin la sección: CPU con los valores de siempre
        ej = config.get("ejecucion") or {}
        self.dispositivo = ej.get("dispositivo_proceso", "cpu")
        hilos = ej.get("hilos")
        if hilos:   # varios procesos en paralelo: cada uno con sus núcleos, sin pisarse
            import torch
            torch.set_num_threads(int(hilos))
            cv2.setNumThreads(int(hilos))
        gpu_onnx = int(self.dispositivo.split(":")[1]) if self.dispositivo.startswith("cuda") and ej.get("onnx_gpu") else None
        onnx = params_onnx(hilos, gpu_onnx)
        self.localizador = Localizador(modelo, config.get("detector", "tiny"), onnx)
        self.lector = Lector(modelo, onnx)
        # Segundo lector con otro modelo: comete errores distintos, suma candidatos (no se usa para puntuar)
        secundario = config.get("lector_secundario")
        self.lector2 = Lector(secundario, onnx) if secundario else None
        # Detector del servicio de firmas (mismo código y modelo de PR1/ServicioFirmas): ubica la firma para
        # borrarla de los recortes y detecta letra tan mala que parece firma (ilegible)
        self.firmas = None
        if config.get("servicio_firmas_src"):
            import sys
            ruta = Path(config["servicio_firmas_src"])
            sys.path.insert(0, str(ruta if ruta.is_absolute() else Path(raiz) / ruta))
            from firmas.detector import DetectorFirmas
            self.firmas = DetectorFirmas(dispositivo=self.dispositivo)
        # Lectura profunda (GLM-OCR): mucho mejor con letra manuscrita, pero ~12 s en CPU de 3 núcleos
        self.profundo = None
        if config.get("lectura_profunda"):
            from poc.profundo import LectorProfundo
            self.profundo = LectorProfundo(str(Path(raiz) / "modelos" / "GLM-OCR"), self.dispositivo,
                                           ej.get("precision_gpu", "float32"))
        self.puntuador = Puntuador(self.lector.caracteres)
        # Plantillas de la fuente MICR E-13B (la misma en todos los bancos), sacadas de un escaneo conocido
        ref = Plantilla(PICHINCHA_V1, raiz)
        self.micr = LectorMICR()
        if not self.micr.agregar(ref.recortar(ref.ref, "micr"), PICHINCHA_V1["micr_referencia"]):
            raise ValueError("No se pudieron crear las plantillas MICR desde la referencia")
        # Calentamiento: la primera inferencia de ONNX es más lenta; se hace al arrancar, no con un cheque
        r = self.analizar(Path(raiz) / PICHINCHA_V1["referencia"])
        if self.profundo and "lectura_profunda" not in r["tiempos_s"]:
            # El cheque de referencia no necesitó GLM: se calienta con un renglón corto (pocos tokens)
            self.profundo.leer([("beneficiario", ref.recortar(ref.ref, "beneficiario"))])
        self.segundos_carga = round(time.perf_counter() - t, 2)

    def analizar(self, ruta, seleccion=None):
        sel = {**self.config["anverso"], **(seleccion or {})}
        tiempos, crudo, res, validaciones = {}, {}, {}, {}
        presupuesto = self.config["presupuesto_segundos_por_lado"]
        omitidos, sin_zona = [], []
        t_total = time.perf_counter()

        def paso(nombre, fn):
            # Control duro de tiempo: si el paso podría pasarse del presupuesto, no se ejecuta
            # y sus campos quedan para revisión (mejor un campo pendiente que un cheque lento)
            if time.perf_counter() - t_total + COSTO_ESTIMADO_S.get(nombre, 1.0) > presupuesto:
                omitidos.append(nombre)
                tiempos[nombre] = 0.0
                return
            faltan = [z for z in ZONA_DEL_PASO.get(nombre, []) if z not in zonas]
            if faltan:
                sin_zona.append((nombre, faltan))
                return
            t = time.perf_counter()
            fn()
            tiempos[nombre] = round(time.perf_counter() - t, 3)
            hechos[nombre] = fn

        hechos = {}       # paso -> función, para volver a decidirlo con la lectura de GLM
        leidas = {}       # zona -> (lecturas rápidas, matrices): no se relee al volver a decidir
        profundo = {}     # zona -> texto de GLM

        def leer(nombre, recorte, verificar=True):
            if nombre not in leidas:
                # Cada versión de la zona se prepara una vez y pasa una sola vez por cada modelo:
                # el texto y la matriz para verificar salen de la misma pasada
                imagenes = {v: VARIANTES[v](recorte) for v in VARIANTES_TEXTO}
                lecturas, P = self.lector.leer_con_probabilidades(imagenes, VARIANTES_TEXTO,
                                                                  VARIANTES_VERIFICACION if verificar else ())
                if self.lector2 and nombre in ZONAS_SEGUNDO_LECTOR:
                    lecturas += self.lector2.leer_con_probabilidades(imagenes, VARIANTES_VERIFICACION)[0]
                leidas[nombre] = (lecturas, [Matriz(P[v]) for v in VARIANTES_VERIFICACION] if verificar else [])
            lecturas, mats = leidas[nombre]
            if nombre in profundo:   # la lectura de GLM va primero: es la base para el beneficiario
                lecturas = [{"variante": "glm-ocr", "texto": profundo[nombre], "confianza": 0.99}] + lecturas
            crudo[nombre] = [l["texto"] for l in lecturas]
            return lecturas, mats

        # 1. Abrir y buscar los campos
        t = time.perf_counter()
        original = leer_gris(ruta)
        tiempos["abrir_imagen"] = round(time.perf_counter() - t, 3)
        t = time.perf_counter()
        img = self.localizador.preparar(original)
        zonas, _, info = self.localizador.localizar(img)
        self.ultima_imagen = img
        calidad_ok = original.shape[1] >= ANCHO_MINIMO_PX
        tiempos["buscar_campos"] = round(time.perf_counter() - t, 3)

        # Copia del cheque sin el texto impreso: los recortes manuscritos no arrastran etiquetas ni leyendas
        manuscrito = img.copy()
        fondo = int(np.percentile(img, 90))
        for x0, y0, x1, y1 in info.pop("impresos", []):
            manuscrito[max(0, y0):y1, max(0, x0):x1] = fondo
        IMPRESAS = {"micr", "cheque_impreso", "cuenta_impresa"}

        def zona(z):
            x0, y0, x1, y1 = zonas[z]
            return (img if z in IMPRESAS else manuscrito)[y0:y1, x0:x1]

        # Firmas: se borran de los recortes; si una "firma" cubre 2+ campos manuscritos, esa letra es ilegible
        ilegibles = set()
        if self.firmas:
            from PIL import Image
            t = time.perf_counter()
            firmas = self.firmas.detectar(Image.fromarray(img).convert("RGB"))
            crudo["firmas"] = [f.a_dict() for f in firmas]
            for f in firmas:
                cubiertas = []
                for z in ("beneficiario", "monto_letras", "monto_numeros", "ciudad_fecha"):
                    if z in zonas:
                        x0, y0, x1, y1 = zonas[z]
                        ix = max(0, min(x1, f.x2) - max(x0, f.x1))
                        iy = max(0, min(y1, f.y2) - max(y0, f.y1))
                        if ix * iy > 0.3 * (x1 - x0) * (y1 - y0):
                            cubiertas.append(z)
                if len(cubiertas) >= 2:
                    ilegibles.update(cubiertas)   # no es una firma: es letra que parece firma
                else:
                    manuscrito[max(0, f.y1):f.y2, max(0, f.x1):f.x2] = fondo   # firma real: fuera del recorte
            tiempos["firmas"] = round(time.perf_counter() - t, 3)

        def letras_unidas():
            letras = zona("monto_letras")
            if "monto_letras_2" in zonas and proporcion_tinta(zona("monto_letras_2")) > TINTA_MINIMA_RENGLON:
                letras = _unir_renglones(letras, zona("monto_letras_2"))
            return letras

        def lectura_profunda(nombres, resto):
            """GLM sobre las zonas `nombres`, en UNA pasada, si alcanza el tiempo (resto = lo que falta después)."""
            if len(ilegibles) >= 2:
                crudo["glm_ocr"] = "omitida: letra ilegible (el detector de firmas la confunde con firmas)"
                return
            recortes = [(z, letras_unidas() if z == "monto_letras" else zona(z)) for z in nombres if z in zonas]
            if not recortes:
                return
            costo = self.profundo.estimar_segundos(len(recortes))
            if time.perf_counter() - t_total + costo + resto > presupuesto:
                crudo["glm_ocr"] = f"omitida: ~{costo:.0f} s estimados no alcanzan en el límite de {presupuesto} s"
                return
            t = time.perf_counter()
            leido = self.profundo.leer(recortes)
            tiempos["lectura_profunda"] = round(time.perf_counter() - t, 3)
            crudo["glm_ocr_texto_completo"] = leido.pop("_texto_completo", "")
            crudo["glm_ocr_zonas"] = [z for z, _ in recortes]
            profundo.update(leido)
            crudo["glm_ocr"] = profundo

        # Lectura profunda: "siempre" = todas las zonas manuscritas antes de decidir (como al inicio);
        # "dudosos" (por omisión) = solo las zonas cuyos campos el camino rápido dejó en revisión (ver abajo)
        modo_profundo = self.config.get("lectura_profunda_modo", "dudosos")
        if self.profundo and modo_profundo == "siempre":
            resto = sum(COSTO_ESTIMADO_S[k] for k in CAMPOS_DEL_PASO if sel.get(k)) * 0.6
            lectura_profunda([z for paso_, z in ZONA_GLM_DEL_PASO.items() if sel.get(paso_)], resto)

        # 2. Datos impresos: MICR (si hay), n.º de cheque, cuenta y banco
        if sel.get("micr_cheque_cuenta_banco"):
            def _impresos():
                lect, mats = {}, {}
                for z in ("cheque_impreso", "cuenta_impresa"):
                    lect[z], mats[z] = leer(z, zona(z)) if z in zonas else ([], [])
                micr = None
                if "micr" in zonas:
                    lectura_micr = self.micr.leer(zona("micr"))
                    crudo["micr_plantillas"] = lectura_micr["texto"]
                    r = campos.datos_impresos(lect, mats, self.puntuador, lectura_micr)
                    if r is None:   # la MICR tiene caracteres dudosos: se recurre al OCR general
                        lect["micr"], mats["micr"] = leer("micr", zona("micr"))
                        r = campos.datos_impresos(lect, mats, self.puntuador)
                        for campo in r:   # si las plantillas dudaron, la imagen está mala: nada automático
                            campo["revisar"] = True
                            campo["nota"] += "; MICR con caracteres dudosos en el lector E-13B"
                    micr, res["numero_cheque"], res["cuenta"] = r
                    res["micr"] = micr
                else:
                    res["numero_cheque"], res["cuenta"] = campos.impresos_sin_micr(lect)
                res["banco"] = campos.banco_encontrado(info["banco_impreso"], micr)
            paso("micr_cheque_cuenta_banco", _impresos)

        # 3. Montos (cifras y letras se verifican entre sí sobre la imagen)
        if sel.get("montos"):
            def _montos():
                lect_let, mats_let = leer("monto_letras", letras_unidas())
                cifras = zona("monto_numeros")
                if info.get("recortar_prefijo_monto"):   # sin etiqueta US$: quitar lo impreso antes del monto
                    cifras, corte = quitar_impreso_a_la_izquierda(cifras)
                    crudo["monto_numeros_corte_px"] = int(corte)
                lect_num, mats_num = leer("monto_numeros", cifras)
                num, let, val = campos.montos(lect_num, lect_let, mats_num, mats_let, self.puntuador)
                res["monto_numeros"], res["monto_letras"] = num, let
                validaciones["montos"] = val
            paso("montos", _montos)

        if sel.get("ciudad_fecha"):
            def _cf():
                lect, mats = leer("ciudad_fecha", zona("ciudad_fecha"))
                res["ciudad"], res["fecha"] = campos.ciudad_fecha(lect, mats, self.puntuador)
            paso("ciudad_fecha", _cf)

        if sel.get("beneficiario"):
            def _benef():
                lect, mats = leer("beneficiario", zona("beneficiario"))
                res["beneficiario"] = campos.beneficiario(lect, mats, self.puntuador)
            paso("beneficiario", _benef)

        # Lectura profunda solo donde el camino rápido dudó; esos pasos se vuelven a decidir con el texto
        # de GLM sumado a las lecturas ya hechas (no se relee la imagen)
        if self.profundo and modo_profundo == "dudosos":
            dudosos = [p for p in ZONA_GLM_DEL_PASO if p in hechos
                       and any(res.get(c, {}).get("revisar") for c in CAMPOS_DEL_PASO[p])]
            if dudosos:
                lectura_profunda([ZONA_GLM_DEL_PASO[p] for p in dudosos], 0.5)
                t = time.perf_counter()
                for p in dudosos:
                    if ZONA_GLM_DEL_PASO[p] in profundo:
                        hechos[p]()
                tiempos["decidir_con_glm"] = round(time.perf_counter() - t, 3)
            elif any(p in hechos for p in ZONA_GLM_DEL_PASO):
                crudo["glm_ocr"] = "no hizo falta: el camino rápido resolvió los campos manuscritos"

        # Letra que parece firma: sus campos siempre a revisión
        CAMPOS_DE_ZONA = {"beneficiario": ["beneficiario"], "monto_letras": ["monto_letras", "monto_numeros"],
                          "monto_numeros": ["monto_numeros", "monto_letras"], "ciudad_fecha": ["ciudad", "fecha"]}
        for z in ilegibles:
            for c in CAMPOS_DE_ZONA[z]:
                if c in res:
                    res[c]["revisar"] = True
                    res[c]["nota"] += "; letra ilegible (el detector de firmas la confunde con una firma)"
        # 4. Campos que no se pudieron leer: siempre a revisión, con el motivo
        for nombre in omitidos:
            for c in CAMPOS_DEL_PASO[nombre]:
                res[c] = campos._campo(None, 0, "omitido: no alcanzó el tiempo por lado", revisar=True)
        for nombre, faltan in sin_zona:
            for c in CAMPOS_DEL_PASO[nombre]:
                res[c] = campos._campo(None, 0, f"no se encontró en el cheque ({', '.join(faltan)})", revisar=True)
        if not calidad_ok:
            for v in res.values():
                v["revisar"] = True
                v["nota"] += f"; resolución insuficiente ({original.shape[1]} px de ancho)"
        total = round(time.perf_counter() - t_total, 3)
        a_revisar = [k for k, v in res.items() if v["revisar"]]
        H, W = img.shape
        return {
            "archivo": "(subida)" if isinstance(ruta, (bytes, bytearray)) else str(ruta),
            "estado": "OK" if not a_revisar else "REVISAR",
            "campos": {k: v["valor"] for k, v in res.items()},
            "detalle": res,
            "campos_a_revisar": a_revisar,
            "validaciones": validaciones,
            "seleccion": sel,
            "tiempos_s": {**tiempos, "total": total},
            "dentro_de_presupuesto": total <= presupuesto,
            "pasos_omitidos_por_tiempo": omitidos,
            "localizacion": {**info, "zonas": {k: [round(x0 / W, 4), round(y0 / H, 4), round(x1 / W, 4), round(y1 / H, 4)]
                                               for k, (x0, y0, x1, y1) in zonas.items()}},
            "calidad_imagen": {"ancho_px": original.shape[1], "alto_px": original.shape[0], "suficiente": calidad_ok},
            "lecturas_crudas": crudo,
            "modelo_lectura": self.lector.modelo,
        }
