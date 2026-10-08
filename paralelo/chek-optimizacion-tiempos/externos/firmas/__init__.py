"""Núcleo de detección de firmas en cheques (sin dependencias web)."""
from .detector import CONF_TINTA, MODELO_DEFAULT, DetectorFirmas, Firma, ModeloNoEncontrado

__all__ = ["CONF_TINTA", "MODELO_DEFAULT", "DetectorFirmas", "Firma", "ModeloNoEncontrado"]
