"""Detección del equipo (CPU, RAM, GPU) y recomendación de cuántos análisis hacer a la vez.

No carga ningún modelo: solo mira el equipo. Se puede ejecutar solo para ver el diagnóstico:

    .venv\\Scripts\\python -m poc.hardware
"""

import ctypes
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field

# Los modelos se cargan UNA vez y los comparten todos los análisis simultáneos.
# Memoria de los modelos (medido en la PoC: el proceso usa ~5 GB en CPU)
RAM_MODELOS_CPU_GB = 5.0
RAM_MODELOS_GPU_GB = 3.0       # en GPU los pesos de GLM pasan a la VRAM
# VRAM de los modelos: GLM-OCR 0,9 B (fp32 ~3,6 GB, fp16 ~1,8 GB) + YOLOS (~0,1 GB) + margen
VRAM_MODELOS_GB = {"float32": 4.2, "float16": 2.3, "bfloat16": 2.3}
VRAM_MODELOS_SIN_GLM_GB = 0.3
# Memoria de TRABAJO de cada análisis simultáneo extra (imágenes, activaciones, caché de GLM)
RAM_POR_ANALISIS_GB = 0.8
VRAM_POR_ANALISIS_GB = 0.6
RAM_RESERVA_GB = 2.0           # para el sistema operativo y el servidor web
VRAM_RESERVA_GB = 0.5
NUCLEOS_MINIMOS_POR_ANALISIS = 2   # con menos, cada cheque se vuelve demasiado lento
NUCLEOS_RECOMENDADOS_CPU = 4       # en CPU, cada análisis rinde bien desde ~4 núcleos
ANALISIS_RECOMENDADOS_GPU = 3      # mientras uno usa la GPU (GLM), los otros hacen la parte de CPU


@dataclass
class GPU:
    indice: int
    nombre: str
    vram_total_gb: float
    vram_libre_gb: float


@dataclass
class Equipo:
    nucleos_fisicos: int
    nucleos_logicos: int
    ram_total_gb: float
    ram_libre_gb: float
    gpus: list = field(default_factory=list)          # GPUs que torch puede usar
    gpus_sin_cuda: list = field(default_factory=list)  # GPUs NVIDIA vistas por nvidia-smi pero torch es solo CPU
    torch_cuda: bool = False
    torch_version: str = ""
    onnx_cuda: bool = False                             # PaddleOCR (ONNX) también puede ir a la GPU

    @property
    def hay_gpu(self):
        return bool(self.gpus)


# ---------------------------------------------------------------- CPU y RAM
def _nucleos():
    logicos = os.cpu_count() or 1
    try:
        import psutil
        return psutil.cpu_count(logical=False) or logicos, logicos
    except ImportError:
        pass
    fisicos = None
    sistema = platform.system()
    try:
        if sistema == "Windows":
            salida = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfCores -Sum).Sum"],
                capture_output=True, text=True, timeout=15).stdout.strip()
            fisicos = int(salida) if salida.isdigit() else None
        elif sistema == "Linux":
            pares = set()
            fisico = None
            with open("/proc/cpuinfo", encoding="utf-8") as f:
                for linea in f:
                    if linea.startswith("physical id"):
                        fisico = linea.split(":")[1].strip()
                    elif linea.startswith("core id"):
                        pares.add((fisico, linea.split(":")[1].strip()))
            fisicos = len(pares) or None
        elif sistema == "Darwin":
            fisicos = int(subprocess.run(["sysctl", "-n", "hw.physicalcpu"], capture_output=True,
                                         text=True, timeout=5).stdout.strip())
    except Exception:   # noqa: BLE001 - si no se puede saber, se usa el número lógico
        fisicos = None
    return min(fisicos or logicos, logicos), logicos


def _ram_gb():
    """(total, libre) en GB."""
    try:
        import psutil
        m = psutil.virtual_memory()
        return m.total / 2**30, m.available / 2**30
    except ImportError:
        pass
    try:
        if platform.system() == "Windows":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MEMORYSTATUSEX()
            m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 2**30, m.ullAvailPhys / 2**30
        if os.path.exists("/proc/meminfo"):
            datos = {}
            with open("/proc/meminfo", encoding="utf-8") as f:
                for linea in f:
                    k, v = linea.split(":", 1)
                    datos[k] = int(v.split()[0]) / 2**20   # kB -> GB
            return datos["MemTotal"], datos.get("MemAvailable", datos.get("MemFree", 0))
    except Exception:   # noqa: BLE001
        pass
    return 0.0, 0.0


# ---------------------------------------------------------------- GPU
def _gpus_torch():
    try:
        import torch
        version = torch.__version__
        if not torch.cuda.is_available():
            return [], False, version
    except Exception:   # noqa: BLE001 - torch ausente o mal instalado: se sigue como "sin GPU"
        return [], False, ""
    gpus = []
    for i in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(i)
        total = props.total_memory / 2**30
        try:
            libre = torch.cuda.mem_get_info(i)[0] / 2**30
        except Exception:   # noqa: BLE001
            libre = total
        gpus.append(GPU(i, props.name, round(total, 1), round(libre, 1)))
    return gpus, True, version


def _gpus_nvidia_smi():
    """GPUs NVIDIA del equipo aunque torch no tenga CUDA (para avisar que se puede instalar)."""
    if not shutil.which("nvidia-smi"):
        return []
    try:
        salida = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.total,memory.free",
                                 "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout
    except Exception:   # noqa: BLE001
        return []
    gpus = []
    for linea in salida.strip().splitlines():
        partes = [p.strip() for p in linea.split(",")]
        if len(partes) == 4 and partes[0].isdigit():
            try:
                gpus.append(GPU(int(partes[0]), partes[1], round(float(partes[2]) / 1024, 1),
                                round(float(partes[3]) / 1024, 1)))
            except ValueError:
                continue
    return gpus


def _onnx_cuda():
    try:
        import onnxruntime
        return "CUDAExecutionProvider" in onnxruntime.get_available_providers()
    except Exception:   # noqa: BLE001
        return False


def detectar():
    fisicos, logicos = _nucleos()
    total, libre = _ram_gb()
    gpus, torch_cuda, version = _gpus_torch()
    sin_cuda = [] if gpus else _gpus_nvidia_smi()
    return Equipo(fisicos, logicos, round(total, 1), round(libre, 1), gpus, sin_cuda, torch_cuda, version,
                  _onnx_cuda() if gpus else False)


# ---------------------------------------------------------------- recomendación
@dataclass
class Recomendacion:
    dispositivo: str            # "cpu" o "gpu"
    maximo: int                 # análisis simultáneos que el equipo aguanta
    recomendado: int            # los que conviene usar
    limites: dict               # motivo -> máximo por ese motivo
    notas: list


def recomendar(equipo, dispositivo, gpu_elegida=None, precision_gpu="float32", con_glm=True):
    """Cuántos análisis simultáneos se pueden hacer con UN juego de modelos cargado en `dispositivo`.

    La memoria de los modelos se cuenta una sola vez; cada análisis extra solo suma su memoria de trabajo.
    El límite real es el menor entre: RAM libre, núcleos (mínimo por análisis) y, en GPU, VRAM libre.
    """
    notas, limites = [], {}
    gpu = dispositivo == "gpu"
    ram_modelos = RAM_MODELOS_GPU_GB if gpu else RAM_MODELOS_CPU_GB
    if equipo.ram_libre_gb > 0:
        limites["RAM"] = max(1, int((equipo.ram_libre_gb - RAM_RESERVA_GB - ram_modelos) // RAM_POR_ANALISIS_GB))
    limites["núcleos"] = max(1, equipo.nucleos_fisicos // NUCLEOS_MINIMOS_POR_ANALISIS)
    notas.append(f"Los modelos se cargan UNA vez (~{ram_modelos:.0f} GB de RAM) y los comparten todos los análisis; "
                 f"cada análisis simultáneo suma ~{RAM_POR_ANALISIS_GB:.1f} GB de trabajo.")

    if gpu:
        g = next((x for x in equipo.gpus if x.indice == gpu_elegida), equipo.gpus[0])
        vram_modelos = VRAM_MODELOS_GB.get(precision_gpu, VRAM_MODELOS_GB["float32"]) if con_glm else VRAM_MODELOS_SIN_GLM_GB
        limites["VRAM"] = max(1, int((g.vram_libre_gb - VRAM_RESERVA_GB - vram_modelos) // VRAM_POR_ANALISIS_GB))
        maximo = min(limites.values())
        recomendado = min(maximo, max(ANALISIS_RECOMENDADOS_GPU, 1))
        notas.append(f"En la GPU [{g.indice}] los modelos ocupan ~{vram_modelos:.1f} GB ({precision_gpu}) una sola vez; "
                     f"cada análisis extra ~{VRAM_POR_ANALISIS_GB:.1f} GB.")
        notas.append("GLM-OCR (el 80 % del tiempo) va a la GPU: cada cheque baja mucho de tiempo aun con 1.")
        notas.append("Con varios a la vez, mientras un cheque usa la GPU los otros avanzan con la parte de CPU.")
        if not equipo.onnx_cuda:
            notas.append("PaddleOCR (ONNX) seguirá en CPU: falta onnxruntime-gpu.")
    else:
        maximo = min(limites.values())
        recomendado = max(1, min(maximo, equipo.nucleos_fisicos // NUCLEOS_RECOMENDADOS_CPU))
        notas.append("En CPU, varios a la vez NO aceleran un cheque: reparten los núcleos. Sirven para LOTES "
                     "(más cheques por minuto); cada cheque individual tarda algo más.")
        if equipo.nucleos_fisicos < 2 * NUCLEOS_RECOMENDADOS_CPU:
            notas.append(f"Con {equipo.nucleos_fisicos} núcleos físicos conviene 1 (el modo actual).")
    notas.append("Cada cheque sigue con su límite de tiempo: si por la carga un paso no alcanza, ese campo "
                 "queda en \"revisar\" (nunca se pasa del límite).")
    if maximo <= 1:
        notas.append("Este equipo no da para más de 1: se usa el modo actual.")
    return Recomendacion(dispositivo, maximo, recomendado, limites, notas)


def hilos_torch(equipo, paralelos):
    """Núcleos para torch en cada análisis cuando hay varios a la vez (None = valor por omisión)."""
    if paralelos <= 1:
        return None
    return max(1, equipo.nucleos_fisicos // paralelos)


def describir(equipo):
    lineas = [f"CPU: {equipo.nucleos_fisicos} núcleos físicos / {equipo.nucleos_logicos} lógicos "
              f"({platform.processor() or platform.machine()})",
              f"RAM: {equipo.ram_libre_gb:.1f} GB libres de {equipo.ram_total_gb:.1f} GB"]
    if equipo.gpus:
        for g in equipo.gpus:
            lineas.append(f"GPU [{g.indice}]: {g.nombre} - {g.vram_libre_gb:.1f} GB libres de {g.vram_total_gb:.1f} GB")
        lineas.append(f"torch {equipo.torch_version} con CUDA: sí · PaddleOCR (ONNX) en GPU: "
                      f"{'sí' if equipo.onnx_cuda else 'no (falta onnxruntime-gpu; sigue en CPU)'}")
    elif equipo.gpus_sin_cuda:
        for g in equipo.gpus_sin_cuda:
            lineas.append(f"GPU [{g.indice}]: {g.nombre} ({g.vram_total_gb:.1f} GB) - NO utilizable: "
                          f"torch {equipo.torch_version or '(no instalado)'} es solo CPU")
        lineas.append("  Para usarla instala torch con CUDA en .venv (ver https://pytorch.org/get-started/locally/)")
    else:
        lineas.append("GPU: no se detectó ninguna GPU utilizable (NVIDIA + CUDA)")
    return lineas


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    eq = detectar()
    print("\n".join(describir(eq)))
    for d in (["cpu", "gpu"] if eq.hay_gpu else ["cpu"]):
        r = recomendar(eq, d)
        print(f"\n[{d.upper()}] máximo {r.maximo} análisis simultáneos, recomendado {r.recomendado} "
              f"(límites: {', '.join(f'{k} {v}' for k, v in r.limites.items())})")
        for n in r.notas:
            print("  -", n)
