"""Lectura profunda con GLM-OCR (modelo de visión-lenguaje local, 0,9 B parámetros, licencia MIT).

Lee la letra manuscrita bastante mejor que PP-OCR, pero es lento en CPU (~12 s para 3 renglones con
3 núcleos). Para pagar ese costo una sola vez, todas las zonas manuscritas se apilan en UNA imagen
(un renglón por zona) y se transcriben en una pasada. Su texto entra como una lectura más: las reglas
de siempre (cruce de montos, diccionario, fechas) deciden; GLM nunca se acepta "porque sí".
"""

import re
import time

import cv2
import numpy as np

ALTO_RENGLON = 48
ANCHO_MAXIMO = 760
TOKENS_POR_RENGLON = 28
# Tiras de la lectura en una pasada. Alto 40 o 32 ahorra parches pero empeora la lectura manuscrita
# (probado 2026-10-08: "cuatrociento" -> "Cuadernillo", y a 32 alucina renglones)
ALTO_TIRA = 56
ANCHO_MAXIMO_TIRA = 900


class LectorProfundo:
    def __init__(self, carpeta_modelo, dispositivo="cpu", precision="float32"):
        """dispositivo: "cpu" (original) o "cuda:N". precision solo aplica en GPU (en CPU siempre float32)."""
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor
        from transformers.utils import logging as hf_logging
        hf_logging.set_verbosity_error()
        hf_logging.disable_progress_bar()
        self.torch = torch
        self.proc = AutoProcessor.from_pretrained(carpeta_modelo)
        self.dispositivo = dispositivo
        self.gpu = dispositivo.startswith("cuda")
        self.dtype = getattr(torch, precision) if self.gpu else torch.float32
        self.modelo = AutoModelForImageTextToText.from_pretrained(carpeta_modelo, dtype=self.dtype).eval()
        if self.gpu:
            self.modelo = self.modelo.to(dispositivo)
        # se ajusta con cada uso (para el control de tiempo); en GPU arranca mucho más bajo
        self.segundos_por_token = 0.05 if self.gpu else 0.35

    def _a_dispositivo(self, entrada):
        """En GPU, las entradas van a la misma GPU y las imágenes en la precisión del modelo."""
        if not self.gpu:
            return entrada
        entrada = entrada.to(self.dispositivo)
        for k, v in entrada.items():
            if hasattr(v, "is_floating_point") and v.is_floating_point() and v.dtype != self.dtype:
                entrada[k] = v.to(self.dtype)
        return entrada

    def estimar_segundos(self, n_renglones):
        # una sola pasada: ~2 s fijos (imagen) + ~12 tokens de salida por renglón en promedio
        return 2.0 + self.segundos_por_token * 12 * n_renglones

    def leer(self, recortes):
        """recortes: lista de (nombre, imagen gris). Todas las zonas apiladas en UNA imagen (GLM lee mejor
        con contexto que renglón por renglón). Devuelve {nombre: texto}; renglones alucinados se descartan."""
        from PIL import Image
        # Ancho fijo con relleno blanco: rellenar solo hasta la tira más ancha ahorra ~3 s pero GLM lee peor
        # (probado 2026-10-08: "Ambato" -> "Jumbalo", "cuatrociento" -> "cuadrienteo")
        tiras = [cv2.resize(c, (max(1, int(c.shape[1] * ALTO_TIRA / c.shape[0])), ALTO_TIRA),
                            interpolation=cv2.INTER_CUBIC)[:, :ANCHO_MAXIMO_TIRA] for _, c in recortes]
        tiras = [cv2.copyMakeBorder(t, 6, 6, 8, ANCHO_MAXIMO_TIRA + 8 - t.shape[1], cv2.BORDER_CONSTANT, value=255)
                 for t in tiras]
        pila = Image.fromarray(np.vstack(tiras)).convert("RGB")
        msgs = [{"role": "user", "content": [{"type": "image", "image": pila}, {"type": "text", "text": "Text Recognition:"}]}]
        entrada = self.proc.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True,
                                                return_dict=True, return_tensors="pt")
        entrada = self._a_dispositivo(entrada)
        t = time.perf_counter()
        with self.torch.inference_mode():
            salida = self.modelo.generate(**entrada, max_new_tokens=TOKENS_POR_RENGLON * len(recortes) + 8,
                                          do_sample=False, repetition_penalty=1.1)
        nuevos = salida[0][entrada["input_ids"].shape[1]:]
        self.segundos_por_token = 0.7 * self.segundos_por_token + 0.3 * (time.perf_counter() - t) / max(1, len(nuevos))
        texto = self.proc.decode(nuevos, skip_special_tokens=True)
        res = {k: v for k, v in self._repartir([n for n, _ in recortes], texto).items() if self._validar(v)}
        res["_texto_completo"] = texto
        return res

    def _leer_una(self, recorte):
        from PIL import Image
        r = cv2.resize(recorte, (max(1, int(recorte.shape[1] * ALTO_RENGLON / recorte.shape[0])), ALTO_RENGLON),
                       interpolation=cv2.INTER_AREA)[:, :ANCHO_MAXIMO]
        r = cv2.copyMakeBorder(r, 6, 6, 8, 8, cv2.BORDER_CONSTANT, value=255)
        msgs = [{"role": "user", "content": [{"type": "image", "image": Image.fromarray(r).convert("RGB")},
                                             {"type": "text", "text": "Text Recognition:"}]}]
        entrada = self.proc.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True,
                                                return_dict=True, return_tensors="pt")
        entrada = self._a_dispositivo(entrada)
        t = time.perf_counter()
        with self.torch.inference_mode():
            salida = self.modelo.generate(**entrada, max_new_tokens=TOKENS_POR_RENGLON, do_sample=False,
                                          repetition_penalty=1.15)
        nuevos = salida[0][entrada["input_ids"].shape[1]:]
        self.segundos_por_token = 0.7 * self.segundos_por_token + 0.3 * (time.perf_counter() - t) / max(1, len(nuevos))
        return " ".join(self.proc.decode(nuevos, skip_special_tokens=True).split())

    @staticmethod
    def _validar(texto):
        """Descarta alucinaciones: otro alfabeto o la misma palabra repetida en bucle."""
        if not texto or any(ord(ch) > 0x24F for ch in texto if ch.isalpha()):
            return ""
        palabras = texto.split()
        if len(palabras) >= 4 and len(set(palabras)) <= len(palabras) / 2:
            return ""
        return texto

    @staticmethod
    def _repartir(nombres, texto):
        """Asigna cada renglón transcrito a su zona (en orden; si sobran o faltan, por contenido)."""
        lineas = [l.strip() for l in texto.splitlines() if l.strip()]
        # Etiquetas impresas que GLM a veces transcribe como renglón propio
        lineas = [l for l in lineas if not re.fullmatch(r"(?i)\W*(la\s*)?suma\s*de\W*|\W*uma de\W*|.*fecha de emisi.*|\W*d[oó]lares\W*", l)]
        from poc.clasificador import buscar_fecha, puntaje_letras
        if len(lineas) == len(nombres):
            res = dict(zip(nombres, lineas))
            # La línea con fecha siempre es ciudad/fecha (GLM a veces cambia el orden de los renglones)
            if "ciudad_fecha" in res and not buscar_fecha(res["ciudad_fecha"]):
                otra = next((n for n in nombres if n != "ciudad_fecha" and buscar_fecha(res[n])), None)
                if otra:
                    res["ciudad_fecha"], res[otra] = res[otra], res["ciudad_fecha"]
            return res
        res, libres = {}, list(lineas)
        for n in nombres:   # primero por contenido: fecha y letras se reconocen solos
            if n == "ciudad_fecha":
                l = next((x for x in libres if buscar_fecha(x)), None)
            elif n.startswith("monto_letras"):
                l = max(libres, key=puntaje_letras, default=None) if libres and max(map(puntaje_letras, libres)) else None
            else:
                continue
            if l:
                res[n] = l
                libres.remove(l)
        for n in nombres:   # el resto, en orden
            if n not in res and libres:
                res[n] = libres.pop(0)
        return res
