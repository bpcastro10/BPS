from dataclasses import dataclass

@dataclass
class ComponentesOcr:
    lector: object
    localizador: object
    lector_secundario: object = None
