"""Al levantar el servidor: detecta el equipo, pregunta CPU o GPU y cuántos procesos, y crea el motor.

Las respuestas por omisión (Enter) son las recomendadas. Sin consola (o con --sin-preguntar) se usan
los argumentos de línea de comandos o la sección "ejecucion" de config.json.
"""

import sys

from poc import hardware
from poc.paralelo import MotorLocal, PoolProcesos, config_del_proceso


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


def _lista_gpus(disponibles):
    def validar(r):
        if r.lower() in ("todas", "all", "*"):
            return list(disponibles)
        ids = sorted({int(x) for x in r.replace(" ", "").split(",") if x})
        if not ids or any(i not in disponibles for i in ids):
            raise ValueError(f"usa índices de {disponibles} separados por coma, o 'todas'")
        return ids
    return validar


def _mostrar_recomendacion(rec):
    print(f"\n  Paralelismo en {rec.dispositivo.upper()}: máximo {rec.maximo} proceso(s), "
          f"recomendado {rec.recomendado}")
    print("  Límite por " + ", ".join(f"{k}: {v}" for k, v in rec.limites.items()))
    for n in rec.notas:
        print(f"   - {n}")


def elegir_plan(config, args=None):
    """Devuelve (equipo, plan). plan = {dispositivo, procesos, gpus, hilos, precision_gpu, onnx_gpu}."""
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

    # 2. Qué GPUs (solo si hay más de una)
    gpus = []
    if dispositivo == "gpu":
        disponibles = [g.indice for g in equipo.gpus]
        pedido_gpus = args.get("gpus") or ej.get("gpus")
        if pedido_gpus and pedido_gpus != "todas":
            try:
                gpus = _lista_gpus(disponibles)(str(pedido_gpus))
            except ValueError as e:
                print(f"  [AVISO] gpus '{pedido_gpus}' no válidas ({e}): se usan todas")
                gpus = disponibles
        elif len(disponibles) > 1 and interactivo and not args.get("gpus"):
            gpus = _preguntar(f"¿Qué GPUs usar? (índices separados por coma: {disponibles})", "todas",
                              _lista_gpus(disponibles))
        else:
            gpus = disponibles

    # 3. Cuántos procesos
    rec = hardware.recomendar(equipo, dispositivo, gpus or None, precision, con_glm)
    _mostrar_recomendacion(rec)
    pedido_n = args.get("procesos") or (None if interactivo else ej.get("procesos", 1))
    if pedido_n:
        procesos = max(1, int(pedido_n))
        if procesos > rec.maximo:
            print(f"  [AVISO] se pidieron {procesos} procesos y el máximo estimado es {rec.maximo}: "
                  "puede quedarse sin memoria")
    elif rec.maximo <= 1:
        procesos = 1
    else:
        procesos = _preguntar(f"¿Cuántos procesos en paralelo? (1-{rec.maximo}; 1 = modo actual)",
                              rec.recomendado, _entero_entre(1, rec.maximo))

    plan = {"dispositivo": dispositivo, "procesos": procesos, "gpus": gpus,
            "hilos": hardware.hilos_por_proceso(equipo, procesos), "precision_gpu": precision,
            "onnx_gpu": dispositivo == "gpu" and equipo.onnx_cuda}
    return equipo, plan


def describir_plan(plan):
    if plan["dispositivo"] == "gpu":
        donde = "GPU " + ",".join(str(g) for g in plan["gpus"])
        if not plan["onnx_gpu"]:
            donde += " (PaddleOCR en CPU)"
    else:
        donde = "CPU"
    texto = f"{donde} · {plan['procesos']} proceso(s)"
    if plan["hilos"]:
        texto += f" de {plan['hilos']} hilos"
    return texto


def crear_motor(config, raiz, equipo, plan):
    """1 proceso -> MotorLocal (modo original); N procesos -> PoolProcesos."""
    descripcion = describir_plan(plan)
    print(f"\n=== Ejecución: {descripcion} ===", flush=True)
    if plan["dispositivo"] == "gpu":
        dispositivos = [f"cuda:{plan['gpus'][i % len(plan['gpus'])]}" for i in range(plan["procesos"])]
    else:
        dispositivos = ["cpu"] * plan["procesos"]
    if plan["procesos"] == 1:
        cfg = config_del_proceso(config, dispositivos[0], None, plan["precision_gpu"], plan["onnx_gpu"])
        return MotorLocal(cfg, raiz, descripcion)
    ram_carga = hardware.RAM_POR_PROCESO_CPU_GB   # al cargar, GLM pasa por la RAM aunque termine en la GPU
    simultaneos = max(1, int((equipo.ram_libre_gb - hardware.RAM_RESERVA_GB) // ram_carga)) if equipo.ram_libre_gb else 1
    return PoolProcesos(config, raiz, dispositivos, plan["hilos"], plan["precision_gpu"], plan["onnx_gpu"],
                        simultaneos=simultaneos, descripcion=descripcion)
