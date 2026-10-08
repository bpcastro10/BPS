"""Analiza un archivo de cheque desde consola y muestra los campos extraídos.

Uso:  python tools/probar_cheque.py ruta/al/cheque.jpg
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.logging_config import configure_logging  # noqa: E402
from app.config.settings import get_settings  # noqa: E402
from app.service.analysis.check_analyzer import CheckAnalyzer  # noqa: E402
from app.service.analysis.handwriting_recognizer import HandwritingRecognizer  # noqa: E402
from app.service.analysis.ocr_engine import OcrEngine  # noqa: E402
from app.service.analysis.vlm_refiner import VlmRefiner  # noqa: E402
from app.service.processing_service import file_sha256  # noqa: E402

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    configure_logging()
    settings = get_settings()
    analyzer = CheckAnalyzer(settings, OcrEngine(),
                             HandwritingRecognizer(settings.handwriting_model, settings.handwriting_enabled),
                             VlmRefiner(settings.ollama_url, settings.ollama_model, settings.vlm_mode))
    for arg in sys.argv[1:]:
        path = Path(arg)
        for record in analyzer.analyze_file(path, file_sha256(path)):
            print(f"\n=== {record.file_name} | {record.status} | conf {record.overall_confidence:.0%} | {record.processing_ms} ms")
            for key, f in record.fields.items():
                print(f"  {key:<14} {str(f.value):<50} {f.confidence:.2f}  {f.source:<9} {f.writing or ''}")
            print("  observaciones:", record.observations)
            print("  --- texto OCR ---\n  " + record.raw_text.replace("\n", "\n  "))
