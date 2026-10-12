import numpy as np

_ACENTOS = {"a": "áÁ", "e": "éÉ", "i": "íÍ", "o": "óÓ", "u": "úÚüÜ", "n": "ñÑ"}
PARECIDOS_DIGITO = {"0": "oOcCDQ°", "1": "lI|i!", "2": "zZ", "4": "A", "5": "sS", "6": "bG", "7": "T",
                    "8": "B", "9": "gq"}
NEG = -1e9
import os
PENALIZACION = float(os.environ.get("PENALIZACION", 2.5))

class Matriz:

    def __init__(self, P):
        self.P = P
        self.mejor = np.log(P.max(1) + 1e-12)
        self.arg = P.argmax(1)
        self._cache = {}

    def columnas(self, cols):
        clave = tuple(cols)
        if clave not in self._cache:
            self._cache[clave] = np.log(self.P[:, cols].sum(1) + 1e-12) if cols else np.full(len(self.P), NEG)
        return self._cache[clave]

class Puntuador:
    def __init__(self, caracteres):
        self.indice = {c: i for i, c in enumerate(caracteres)}

    def _columnas(self, ch, digitos_manuscritos=False):
        variantes = {ch, ch.lower(), ch.upper(), *_ACENTOS.get(ch.lower(), "")}
        if digitos_manuscritos:
            variantes.update(PARECIDOS_DIGITO.get(ch, ""))
        return sorted(self.indice[v] for v in variantes if v in self.indice)

    def puntuar(self, M, texto, como_blanco=" ", digitos_manuscritos=False):
        etiquetas = [c for c in texto if c != " "]
        if not etiquetas:
            return NEG
        idx_blanco = [0] + sorted(self.indice[c] for c in set(como_blanco) if c in self.indice)
        clave_libre = ("libre", tuple(idx_blanco))
        if clave_libre not in M._cache:
            M._cache[clave_libre] = M.mejor - np.where(np.isin(M.arg, idx_blanco), 0.0, PENALIZACION)
        libre = M._cache[clave_libre]
        blanco = M.columnas(idx_blanco)

        S = 2 * len(etiquetas) + 1
        T = len(M.P)
        E = np.empty((T, S))
        E[:, 0::2] = blanco[:, None]
        for k, c in enumerate(etiquetas):
            E[:, 2 * k + 1] = M.columnas(self._columnas(c, digitos_manuscritos))
        salto = np.zeros(S, bool)
        for k in range(1, len(etiquetas)):
            salto[2 * k + 1] = etiquetas[k] != etiquetas[k - 1]
        salto = salto[2:]

        prefijo = libre[0]
        a = np.full(S, NEG)
        a[0], a[1] = E[0, 0], E[0, 1]
        sufijo = NEG
        for t in range(1, T):
            fin = a[-1] if a[-1] > a[-2] else a[-2]
            nuevo = a.copy()
            np.maximum(nuevo[1:], a[:-1], out=nuevo[1:])
            nuevo[2:] = np.where(salto, np.maximum(nuevo[2:], a[:-2]), nuevo[2:])
            if prefijo > nuevo[0]:
                nuevo[0] = prefijo
            if prefijo > nuevo[1]:
                nuevo[1] = prefijo
            a = nuevo + E[t]
            sufijo = (sufijo if sufijo > fin else fin) + libre[t]
            prefijo += libre[t]
        total = max(sufijo, a[-1], a[-2])
        return float(total - M.mejor.sum())
