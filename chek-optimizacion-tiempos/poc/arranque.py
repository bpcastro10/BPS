"""Al levantar el servidor: detecta el equipo, pregunta CPU o GPU y cuántos análisis a la vez, y crea el motor.

Los modelos se cargan UNA sola vez; los análisis simultáneos usan esos mismos modelos (poc/paralelo.py).

Las respuestas por omisión (Enter) son las recomendadas. Sin consola (o con --sin-preguntar) se usan
los argumentos de línea de comandos o la sección "ejecucion" de config.json.
"""

import sys

from poc import hardware
from poc.paralelo import Motor, config_de_ejecucion


def _preguntar(texto, por_omision, validar):
    """Pregunta hasta tener una respuesta válida. Enter o sin consola = por_omision."""
    while True:
        try:
            r = input(f"{texto} [Enter = {por_omision}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return validar(str(por_omision))
        if not r:
            r = str(por_omision)
        try:
            return validar(r)
        except ValueError as e:
            print(f"  Respuesta no válida: {e}")


def _entero_entre(minimo, maximo):
    def validar(r):
        n = int(r)
        if not minimo <= n <= maximo:
            raise ValueError(f"debe estar entre {minimo} y {maximo}")
        return n
    return validar


def _cpu_o_gpu(r):
    opciones = {"1": "cpu", "2": "gpu", "cpu": "cpu", "gpu": "gpu"}
    if r.lower() not in opciones:
        raise ValueError("escribe 1 (CPU) o 2 (GPU)")
    return opciones[r.lower()]


def _una_gpu(disponibles):
    def validar(r):
        if not r.strip().isdigit() or int(r) not in disponibles:
            raise ValueError(f"elige uno de {disponibles}")
        return int(r)
    return validar


def _mostrar_recomendacion(rec):
    print(f"\n  Paralelismo en {rec.dispositivo.upper()}: máximo {rec.maximo} análisis a la vez, "
          f"recomendado {rec.recomendado}")
    print("  Límite por " + ", ".join(f"{k}: {v}" for k, v in rec.limites.items()))
    for n in rec.notas:
        print(f"   - {n}")


def elegir_plan(config, args=None):
    """Devuelve (equipo, plan). plan = {dispositivo, paralelos, gpu, hilos_torch, precision_gpu, onnx_gpu}."""
    ej = config.get("ejecucion", {})
    args = args or {}
    interactivo = sys.stdin is not None and sys.stdin.isatty() and ej.get("preguntar_al_iniciar", True) \
        and not args.get("sin_preguntar")
    precision = ej.get("precision_gpu", "float32")
    con_glm = bool(config.get("lectura_profunda"))

    print("\n=== Equipo detectado ===", flush=True)
    equipo = hardware.detectar()
    for linea in hardware.describir(equipo):
        print("  " + linea)

    # 1. CPU o GPU
    pedido = args.get("dispositivo") or (None if interactivo else ej.get("dispositivo", "cpu"))
    if not equipo.hay_gpu:
        if pedido == "gpu":
            print("  [AVISO] se pidió GPU pero no hay ninguna utilizable: se ejecuta en CPU")
        dispositivo = "cpu"
        print("\n  Sin GPU utilizable: se ejecuta en CPU.")
    elif pedido in ("cpu", "gpu"):
        dispositivo = pedido
    else:
        print("\n¿Dónde ejecutar los modelos?\n  1) CPU\n  2) GPU (recomendado: GLM-OCR es el 80 % del tiempo)")
        dispositivo = _preguntar("Opción", 2, _cpu_o_gpu)

    # 2. Qué GPU (solo si hay más de una): los modelos se cargan una vez, en UNA GPU
    gpu = None
    if dispositivo == "gpu":
        disponibles = [g.indice for g in equipo.gpus]
        pedida = args.get("gpu") if args.get("gpu") is not None else ej.get("gpu")
        if pedida is not None and str(pedida).strip() != "":
            try:
                gpu = _una_gpu(disponibles)(str(pedida))
            except ValueError as e:
                print(f"  [AVISO] gpu '{pedida}' no válida ({e}): se usa la {disponibles[0]}")
                gpu = disponibles[0]
        elif len(disponibles) > 1 and interactivo:
            libre = max(equipo.gpus, key=lambda g: g.vram_libre_gb).indice
            print("  Los modelos se cargan una sola vez, en una GPU (los análisis simultáneos la comparten).")
            gpu = _preguntar(f"¿Qué GPU usar? {disponibles}", libre, _una_gpu(disponibles))
        else:
            gpu = max(equipo.gpus, key=lambda g: g.vram_libre_gb).indice

    # 3. Cuántos análisis a la vez (sobre los mismos modelos)
    rec = hardware.recomendar(equipo, dispositivo, gpu, precision, con_glm)
    _mostrar_recomendacion(rec)
    pedido_n = args.get("paralelos") or (None if interactivo else ej.get("paralelos", 1))
    if pedido_n:
        paralelos = max(1, int(pedido_n))
        if paralelos > rec.maximo:
            print(f"  [AVISO] se pidieron {paralelos} a la vez y el máximo estimado es {rec.maximo}: "
                  "puede quedarse sin memoria o pasarse de tiempo")
    elif rec.maximo <= 1:
        paralelos = 1
    else:
        paralelos = _preguntar(f"¿Cuántos cheques analizar a la vez? (1-{rec.maximo}; 1 = modo actual)",
                               rec.recomendado, _entero_entre(1, rec.maximo))

    plan = {"dispositivo": dispositivo, "paralelos": paralelos, "gpu": gpu,
            "hilos_torch": hardware.hilos_torch(equipo, paralelos), "precision_gpu": precision,
            "onnx_gpu": dispositivo == "gpu" and equipo.onnx_cuda}
    return equipo, plan


def describir_plan(plan):
    if plan["dispositivo"] == "gpu":
        donde = f"GPU {plan['gpu']}" + ("" if plan["onnx_gpu"] else " (PaddleOCR en CPU)")
    else:
        donde = "CPU"
    return f"{donde} · {plan['paralelos']} a la vez (modelos cargados 1 vez)"


def crear_motor(config, raiz, equipo, plan):
    """Carga los modelos UNA vez; `paralelos` cheques pueden usarlos a la vez (1 = modo original)."""
    descripcion = describir_plan(plan)
    print(f"\n=== Ejecución: {descripcion} ===", flush=True)
    dispositivo = f"cuda:{plan['gpu']}" if plan["dispositivo"] == "gpu" else "cpu"
    cfg = config_de_ejecucion(config, dispositivo, plan["hilos_torch"], plan["precision_gpu"], plan["onnx_gpu"])
    return Motor(cfg, raiz, plan["paralelos"], descripcion)
