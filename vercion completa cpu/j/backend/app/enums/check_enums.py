from enum import Enum


class CheckStatus(str, Enum):
    COMPLETO = "COMPLETO"
    REVISAR = "REVISAR"
    ERROR = "ERROR"


class FieldSource(str, Enum):
    OCR = "ocr"
    MICR = "micr"
    MANUSCRITO_IA = "trocr"
    VLM = "vlm"
    IMAGEN = "imagen"
    CALCULADO = "calculado"
    MANUAL = "manual"


class WritingType(str, Enum):
    IMPRESO = "impreso"
    MANUSCRITO = "manuscrito"


class FieldKey(str, Enum):
    BANCO = "banco"
    NUMERO_CHEQUE = "numero_cheque"
    CIUDAD = "ciudad"
    FECHA = "fecha"
    BENEFICIARIO = "beneficiario"
    MONTO = "monto"
    MONTO_LETRAS = "monto_letras"
    MONEDA = "moneda"
    CUENTA = "cuenta"
    CODIGO_RUTA = "codigo_ruta"
    LINEA_MICR = "linea_micr"
    CONCEPTO = "concepto"
    FIRMA = "firma"

    @property
    def label(self) -> str:
        return FIELD_LABELS[self]


FIELD_LABELS = {
    FieldKey.BANCO: "Banco",
    FieldKey.NUMERO_CHEQUE: "N° Cheque",
    FieldKey.CIUDAD: "Ciudad",
    FieldKey.FECHA: "Fecha",
    FieldKey.BENEFICIARIO: "Beneficiario",
    FieldKey.MONTO: "Monto",
    FieldKey.MONTO_LETRAS: "Monto en letras",
    FieldKey.MONEDA: "Moneda",
    FieldKey.CUENTA: "Cuenta",
    FieldKey.CODIGO_RUTA: "Código de ruta",
    FieldKey.LINEA_MICR: "Línea MICR",
    FieldKey.CONCEPTO: "Concepto",
    FieldKey.FIRMA: "Firma",
}
