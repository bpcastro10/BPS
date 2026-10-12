import ctypes
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field

RAM_MODELOS_CPU_GB = 5.0
RAM_MODELOS_GPU_GB = 3.0
VRAM_MODELOS_GB = {"float32": 4.2, "float16": 2.3, "bfloat16": 2.3}
VRAM_MODELOS_SIN_GLM_GB = 0.3
RAM_POR_ANALISIS_GB = 0.8
VRAM_POR_ANALISIS_GB = 0.6
RAM_RESERVA_GB = 2.0
VRAM_RESERVA_GB = 0.5
NUCLEOS_MINIMOS_POR_ANALISIS = 2
NUCLEOS_RECOMENDADOS_CPU = 4
ANALISIS_RECOMENDADOS_GPU = 3

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
    gpus: list = field(default_factory=list)
    gpus_sin_cuda: list = field(default_factory=list)
    torch_cuda: bool = False
    torch_version: str = ""
    onnx_cuda: bool = False
    motivo_gpu: str = ""
    cuda_driver: str = ""
    cuda_torch: str = ""

    @property
    def hay_gpu(self):
        return bool(self.gpus)

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
    except Exception:
        fisicos = None
    return min(fisicos or logicos, logicos), logicos

def _ram_gb():
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
                    datos[k] = int(v.split()[0]) / 2**20
            return datos["MemTotal"], datos.get("MemAvailable", datos.get("MemFree", 0))
    except Exception:
        pass
    return 0.0, 0.0

_entorno_cuda_listo = False

def _preparar_entorno_cuda():
    global _entorno_cuda_listo
    if _entorno_cuda_listo:
        return
    _entorno_cuda_listo = True
    if os.environ.get("CUDA_VISIBLE_DEVICES") is not None and not os.environ["CUDA_VISIBLE_DEVICES"].strip():
        os.environ.pop("CUDA_VISIBLE_DEVICES", None)
    rutas = []
    try:
        import importlib.util
        spec = importlib.util.find_spec("torch")
        if spec and spec.origin:
            rutas.append(os.path.join(os.path.dirname(spec.origin), "lib"))
    except Exception:
        pass
    cuda_path = os.environ.get("CUDA_PATH", "")
    if cuda_path:
        rutas.append(os.path.join(cuda_path, "bin"))
    for ruta in rutas:
        if not ruta or not os.path.isdir(ruta):
            continue
        os.environ["PATH"] = ruta + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(ruta)
            except OSError:
                pass

def _tupla_cuda(version):
    nums = []
    for parte in str(version or "").split("."):
        digitos = ""
        for c in parte:
            if c.isdigit():
                digitos += c
            else:
                break
        if not digitos:
            break
        nums.append(int(digitos))
        if len(nums) == 2:
            break
    return tuple(nums)

def _mib_a_gb(texto):
    t = (texto or "").strip()
    if not t or "N/A" in t.upper() or "NOT SUPPORTED" in t.upper():
        return 0.0
    try:
        return round(float(t.replace(",", "")) / 1024, 1)
    except ValueError:
        return 0.0

def _cuda_driver():
    if not shutil.which("nvidia-smi"):
        return ""
    try:
        salida = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=15,
                                encoding="utf-8", errors="replace").stdout
    except Exception:
        return ""
    hallado = re.search(r"CUDA Version:\s*([0-9]+(?:\.[0-9]+)?)", salida)
    return hallado.group(1) if hallado else ""

def _gpus_nvidia_smi():
    if not shutil.which("nvidia-smi"):
        return []
    try:
        salida = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.total,memory.free",
                                 "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15,
                                encoding="utf-8", errors="replace").stdout
    except Exception:
        return []
    gpus = []
    for linea in salida.strip().splitlines():
        partes = [p.strip() for p in linea.split(",")]
        if len(partes) < 4 or not partes[0].isdigit():
            continue
        nombre = ",".join(partes[1:-2]).strip() or "NVIDIA"
        total = _mib_a_gb(partes[-2])
        libre = _mib_a_gb(partes[-1]) or total
        gpus.append(GPU(int(partes[0]), nombre, total, libre))
    return gpus

def _olvidar_cache_cuda(torch):
    for nombre in ("_cached_device_count",):
        if hasattr(torch.cuda, nombre):
            try:
                setattr(torch.cuda, nombre, None)
            except Exception:
                pass

def _cuda_arranca(torch):
    try:
        if torch.cuda.is_available() and torch.cuda.device_count() > 0:
            return True, ""
    except Exception as e:
        ultimo = str(e)
    else:
        ultimo = ""
    _olvidar_cache_cuda(torch)
    try:
        torch.cuda.init()
        if torch.cuda.device_count() > 0:
            return True, ""
    except Exception as e:
        ultimo = str(e)
    try:
        muestra = torch.zeros(1, device="cuda:0")
        del muestra
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass
        return True, ""
    except Exception as e:
        return False, ultimo or str(e)

def _motivo_cuda(torch, error, cuda_driver):
    compilado = getattr(torch.version, "cuda", None) or ""
    if not compilado:
        return ("Hay una GPU NVIDIA, pero torch instalado no trae CUDA (rueda de CPU). "
                "Borra .venv\\.instalado y vuelve a ejecutar instalar_y_levantar.bat "
                "(la rueda cu126 también corre en CPU).")
    if cuda_driver and _tupla_cuda(cuda_driver) < _tupla_cuda(compilado):
        return (f"El driver admite CUDA {cuda_driver} y torch está compilado con CUDA {compilado}: "
                f"por eso la GPU se ve y no se usa. Hace falta la rueda cu126 "
                f"(drivers CUDA 12.6 o superiores, también los 13) o un driver más nuevo.")
    detalle = (error or "").strip().splitlines()
    extra = f" Detalle: {detalle[0]}" if detalle else ""
    return (f"Hay GPU NVIDIA (driver CUDA {cuda_driver or '?'}, torch CUDA {compilado}), "
            f"pero CUDA no arrancó.{extra}")

def _gpus_de_torch(torch):
    gpus = []
    for i in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(i)
        total = props.total_memory / 2**30
        try:
            libre = torch.cuda.mem_get_info(i)[0] / 2**30
        except Exception:
            libre = total
        nombre = getattr(props, "name", f"GPU {i}")
        gpus.append(GPU(i, str(nombre), round(total, 1), round(libre, 1)))
    return gpus

def _gpus_torch(cuda_driver, hay_nvidia):
    _preparar_entorno_cuda()
    try:
        import torch
    except Exception as e:
        motivo = f"No se pudo importar torch ({e})." if hay_nvidia else ""
        return [], False, "", motivo, ""
    version = torch.__version__
    compilado = getattr(torch.version, "cuda", None) or ""
    ok, error = _cuda_arranca(torch)
    if not ok:
        motivo = _motivo_cuda(torch, error, cuda_driver) if hay_nvidia else ""
        return [], False, version, motivo, compilado
    gpus = _gpus_de_torch(torch)
    if gpus:
        return gpus, True, version, "", compilado
    motivo = _motivo_cuda(torch, error, cuda_driver) if hay_nvidia else ""
    return [], False, version, motivo, compilado

def preparar_runtime_gpu():
    _preparar_entorno_cuda()
    try:
        import torch
    except Exception:
        pass
    try:
        import onnxruntime
        if hasattr(onnxruntime, "preload_dlls"):
            onnxruntime.preload_dlls()
    except Exception:
        pass

def _onnx_cuda():
    preparar_runtime_gpu()
    try:
        import onnxruntime
        return "CUDAExecutionProvider" in onnxruntime.get_available_providers()
    except Exception:
        return False

def detectar():
    fisicos, logicos = _nucleos()
    total, libre = _ram_gb()
    vistas = _gpus_nvidia_smi()
    cuda_driver = _cuda_driver()
    gpus, torch_cuda, version, motivo, cuda_torch = _gpus_torch(cuda_driver, bool(vistas) or bool(cuda_driver))
    sin_cuda = [] if gpus else vistas
    return Equipo(fisicos, logicos, round(total, 1), round(libre, 1), gpus, sin_cuda, torch_cuda, version,
                  _onnx_cuda() if gpus else False, motivo, cuda_driver, cuda_torch)

@dataclass
class Recomendacion:
    dispositivo: str
    minimo: int
    maximo: int
    recomendado: int
    limites: dict
    notas: list

def recomendar(equipo, dispositivo, gpu_elegida=None, precision_gpu="float32", con_glm=True):
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
        notas.append(f"En la GPU [{g.indice}] los modelos ocupan ~{vram_modelos:.1f} GB ({precision_gpu}) una sola vez; "
                     f"cada análisis extra ~{VRAM_POR_ANALISIS_GB:.1f} GB.")
        notas.append("GLM-OCR (el 80 % del tiempo) va a la GPU: cada cheque baja mucho de tiempo aun con 1.")
        notas.append("Con varios a la vez, mientras un cheque usa la GPU los otros avanzan con la parte de CPU.")
        if not equipo.onnx_cuda:
            notas.append("PaddleOCR (ONNX) seguirá en CPU: CUDAExecutionProvider no está disponible.")
        sugerido = max(ANALISIS_RECOMENDADOS_GPU, 1)
    else:
        notas.append("En CPU, varios a la vez NO aceleran un cheque: reparten los núcleos. Sirven para LOTES "
                     "(más cheques por minuto); cada cheque individual tarda algo más.")
        if equipo.nucleos_fisicos < 2 * NUCLEOS_RECOMENDADOS_CPU:
            notas.append(f"Con {equipo.nucleos_fisicos} núcleos físicos conviene 1 (el modo actual).")
        sugerido = max(1, equipo.nucleos_fisicos // NUCLEOS_RECOMENDADOS_CPU)
    minimo = 1
    maximo = max(minimo, min(limites.values()))
    recomendado = min(maximo, max(minimo, sugerido))
    notas.append("Cada cheque sigue con su límite de tiempo: si por la carga un paso no alcanza, ese campo "
                 "queda en \"revisar\" (nunca se pasa del límite).")
    if maximo <= 1:
        notas.append("Este equipo no da para más de 1: se usa el modo actual.")
    return Recomendacion(dispositivo, minimo, maximo, recomendado, limites, notas)

def hilos_torch(equipo, paralelos):
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
        compilado = f" · torch CUDA {equipo.cuda_torch}" if equipo.cuda_torch else ""
        driver = f" · driver CUDA {equipo.cuda_driver}" if equipo.cuda_driver else ""
        lineas.append(f"torch {equipo.torch_version} con CUDA: sí{compilado}{driver} · PaddleOCR (ONNX) en GPU: "
                      f"{'sí' if equipo.onnx_cuda else 'no (sigue en CPU)'}")
    elif equipo.gpus_sin_cuda:
        for g in equipo.gpus_sin_cuda:
            lineas.append(f"GPU [{g.indice}]: {g.nombre} ({g.vram_total_gb:.1f} GB) detectada por nvidia-smi")
        if equipo.motivo_gpu:
            lineas.append("  " + equipo.motivo_gpu)
        else:
            lineas.append("  torch no pudo usar esa GPU; se ejecuta en CPU.")
    else:
        lineas.append("GPU: no hay una GPU NVIDIA; con la misma instalación los modelos corren en CPU")
    return lineas

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    eq = detectar()
    print("\n".join(describir(eq)))
    for d in (["cpu", "gpu"] if eq.hay_gpu else ["cpu"]):
        r = recomendar(eq, d)
        print(f"\n[{d.upper()}] entre {r.minimo} y {r.maximo} análisis simultáneos, por defecto {r.recomendado} "
              f"(límites: {', '.join(f'{k} {v}' for k, v in r.limites.items())})")
        for n in r.notas:
            print("  -", n)
