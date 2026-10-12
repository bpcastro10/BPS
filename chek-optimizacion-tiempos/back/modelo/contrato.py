"""Contrato del modelo que lee la letra manuscrita.

El analizador le pasa recortes en gris y usa el texto como UNA lectura más.
Las reglas deciden; el modelo no acepta un campo por su cuenta.

Para enchufar otro modelo:

1. Crea un módulo con
       crear(config, raiz, dispositivo, precision) -> lector
       descargar(config, raiz)                      (opcional, para descargar_modelos.py)
   El lector tiene:
       estimar_segundos(n_renglones) -> float
       leer(recortes) -> {nombre_de_zona: texto}
   `recortes` es una lista de (nombre, imagen gris).
   Si el texto trae un renglón por zona, puedes devolver también "_texto_completo"
   (el analizador lo saca del dict y lo guarda en el JSON, como hace GLM hoy).
2. Agrega UNA línea en MODELOS de back/modelo/fabrica.py.
3. En config.json pon "modelo_profundo" con esa clave.
   "lectura_profunda": false apaga el modelo sin desinstalarlo.
   "carpeta_modelo_profundo" es la carpeta de pesos, si tu modelo la usa.

El analizador publica ese texto con la variante "glm-ocr". Es el nombre estable
que ya entienden las reglas; un modelo nuevo no tiene que llamarse GLM.
"""
