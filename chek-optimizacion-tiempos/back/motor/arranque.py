import sys

from back.motor import hardware
from back.motor.paralelo import Motor, config_de_ejecucion

def _preguntar(texto, por_omision, validar):
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
        try:
            n = int(r)
        except ValueError:
            raise ValueError(f"escribe un número entero entre {minimo} y {maximo}")
        if not minimo <= n <= maximo:
            raise ValueError(f"debe estar entre {minimo} y {maximo}")
        return n
    return validar

def _dentro_de_rango(n, rec):
    n = int(n)
    if rec.minimo <= n <= rec.maximo:
        return n
    ajustado = min(max(n, rec.minimo), rec.maximo)
    print(f"  [AVISO] {n} está fuera del rango permitido ({rec.minimo}-{rec.maximo}); se usa {ajustado}")
    return ajustado

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
    print(f"\n  Paralelismo en {rec.dispositivo.upper()}: entre {rec.minimo} y {rec.maximo} procesos a la vez, "
          f"por defecto {rec.recomendado}")
    print("  Límite por " + ", ".join(f"{k}: {v}" for k, v in rec.limites.items()))
    for n in rec.notas:
        print(f"   - {n}")

def elegir_plan(config, args=None):
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

    pedido = args.get("dispositivo") or (None if interactivo else ej.get("dispositivo", "cpu"))
    if not equipo.hay_gpu:
        if pedido == "gpu":
            print("  [AVISO] se pidió GPU pero torch no puede usarla: se ejecuta en CPU")
        dispositivo = "cpu"
        if equipo.gpus_sin_cuda or equipo.motivo_gpu:
            print("\n  La GPU se detectó, pero torch no puede usarla. Se ejecuta en CPU.")
            if equipo.motivo_gpu:
                print("  " + equipo.motivo_gpu)
        else:
            print("\n  No hay GPU NVIDIA: se ejecuta en CPU.")
    elif pedido in ("cpu", "gpu"):
        dispositivo = pedido
    else:
        print("\n¿Dónde ejecutar los modelos?\n  1) CPU\n  2) GPU (recomendado: GLM-OCR es el 80 % del tiempo)")
        dispositivo = _preguntar("Opción", 2, _cpu_o_gpu)

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

    rec = hardware.recomendar(equipo, dispositivo, gpu, precision, con_glm)
    _mostrar_recomendacion(rec)
    pedido_n = args.get("paralelos")
    if pedido_n is None and not interactivo:
        pedido_n = ej.get("paralelos", rec.recomendado)
    if pedido_n is not None:
        paralelos = _dentro_de_rango(pedido_n, rec)
    elif rec.minimo == rec.maximo:
        paralelos = rec.minimo
        print(f"  En este equipo solo se permite {paralelos} proceso{'s' if paralelos != 1 else ''} a la vez.")
    else:
        print(f"  Escribe un número entre {rec.minimo} y {rec.maximo}. "
              f"Si no escribes nada, queda {rec.recomendado}.")
        paralelos = _preguntar(f"¿Cuántos procesos en paralelo? ({rec.minimo}-{rec.maximo})",
                               rec.recomendado, _entero_entre(rec.minimo, rec.maximo))

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
    descripcion = describir_plan(plan)
    print(f"\n=== Ejecución: {descripcion} ===", flush=True)
    dispositivo = f"cuda:{plan['gpu']}" if plan["dispositivo"] == "gpu" else "cpu"
    cfg = config_de_ejecucion(config, dispositivo, plan["hilos_torch"], plan["precision_gpu"], plan["onnx_gpu"])
    return Motor(cfg, raiz, plan["paralelos"], descripcion)
