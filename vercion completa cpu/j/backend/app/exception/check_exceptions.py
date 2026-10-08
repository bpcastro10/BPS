class CheckAppException(RuntimeError):
    """Base de todas las excepciones de negocio de la aplicación."""

    status_code = 500

    def __str__(self) -> str:
        return self.message

    @property
    def message(self) -> str:
        return "Error interno"


class CheckNotFoundException(CheckAppException):
    status_code = 404

    def __init__(self, check_id: int):
        super().__init__()
        self.check_id = check_id

    @property
    def message(self) -> str:
        return f"No se encontró ningún cheque con el id: {self.check_id}"


class ImageReadException(CheckAppException):
    status_code = 422

    def __init__(self, file_name: str, reason: str = ""):
        super().__init__()
        self.file_name = file_name
        self.reason = reason

    @property
    def message(self) -> str:
        detail = f" ({self.reason})" if self.reason else ""
        return f"No se pudo leer la imagen del archivo: {self.file_name}{detail}"


class UnsupportedFileException(CheckAppException):
    status_code = 415

    def __init__(self, file_name: str):
        super().__init__()
        self.file_name = file_name

    @property
    def message(self) -> str:
        return f"Formato de archivo no soportado: {self.file_name}"


class InvalidFieldException(CheckAppException):
    status_code = 400

    def __init__(self, field: str, value: str):
        super().__init__()
        self.field = field
        self.value = value

    @property
    def message(self) -> str:
        return f"Valor inválido para el campo {self.field}: {self.value}"


class ExportException(CheckAppException):
    status_code = 500

    def __init__(self, reason: str):
        super().__init__()
        self.reason = reason

    @property
    def message(self) -> str:
        return f"No se pudo generar el archivo de exportación: {self.reason}"
