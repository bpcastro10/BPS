"""Genera el Excel de observaciones con el formato del informe de cheques."""

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from validacion import valores_fila

COLUMNAS = [
    "Nombre_archivo",
    "Cuenta_No",
    "Cheque_No",
    "A_la_orden_de",
    "Valor_numero",
    "Valor_texto",
    "Cliente",
    "Fecha",
    "Endoso",
    "Firma",
    "Beneficiario",
    "Coincide_valor",
    "Fecha_correcta",
    "Endoso",
]

_ANCHOS = (38, 18, 14, 28, 16, 42, 22, 28, 18, 12, 16, 16, 16, 12)
_COLUMNAS_SI_NO = {10, 11, 12, 13, 14}
_COLUMNAS_TEXTO = {1, 2, 3}

_RELLENO_TITULO = PatternFill("solid", fgColor="1F4E79")
_RELLENO_NO = PatternFill("solid", fgColor="F4CCCC")
_FUENTE_TITULO = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
_FUENTE = Font(name="Calibri", size=11, color="000000")
_FUENTE_NO = Font(name="Calibri", bold=True, size=11, color="C00000")
_BORDE = Border(
    left=Side(style="thin", color="BDD3E6"),
    right=Side(style="thin", color="BDD3E6"),
    top=Side(style="thin", color="BDD3E6"),
    bottom=Side(style="thin", color="BDD3E6"),
)
_CENTRO = Alignment(horizontal="center", vertical="center", wrap_text=True)
_IZQUIERDA = Alignment(horizontal="left", vertical="center", wrap_text=True)


def escribir_informe(filas: list[dict], carpeta: Path) -> Path:
    """Escribe solo las filas con observaciones y devuelve la ruta del archivo."""
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"informe_cheques_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Informe"

    for columna, titulo in enumerate(COLUMNAS, start=1):
        celda = hoja.cell(1, columna, titulo)
        celda.font = _FUENTE_TITULO
        celda.fill = _RELLENO_TITULO
        celda.alignment = _CENTRO
        celda.border = _BORDE

    for fila_idx, fila in enumerate(filas, start=2):
        for columna, valor in enumerate(valores_fila(fila), start=1):
            celda = hoja.cell(fila_idx, columna, valor if valor != "" else None)
            celda.border = _BORDE
            celda.alignment = _CENTRO if columna in _COLUMNAS_SI_NO else _IZQUIERDA
            if columna in _COLUMNAS_TEXTO and valor not in ("", None):
                celda.number_format = "@"
                celda.value = str(valor)
            elif columna == 5 and isinstance(valor, float):
                celda.number_format = "#,##0.00"
            if columna in _COLUMNAS_SI_NO and valor == "NO":
                celda.font = _FUENTE_NO
                celda.fill = _RELLENO_NO
            else:
                celda.font = _FUENTE

    for indice, ancho in enumerate(_ANCHOS, start=1):
        hoja.column_dimensions[get_column_letter(indice)].width = ancho

    hoja.auto_filter.ref = f"A1:N{max(1, len(filas) + 1)}"
    hoja.freeze_panes = "A2"
    hoja.row_dimensions[1].height = 22
    hoja.page_setup.orientation = "landscape"
    hoja.page_setup.fitToPage = True
    hoja.page_setup.fitToWidth = 1
    hoja.page_setup.fitToHeight = 0
    hoja.sheet_properties.pageSetUpPr.fitToPage = True
    hoja.oddHeader.left.text = "Informe de cheques con observaciones"
    hoja.oddFooter.right.text = "Pagina &P de &N"

    libro.save(destino)
    return destino
