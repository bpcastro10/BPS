from app.controller.dto.check_dto import CheckDetailDTO, CheckDTO
from app.model import CheckRecord


class CheckMapper:
    """Mapeo automático modelo -> DTO (los atributos tienen el mismo nombre)."""

    @staticmethod
    def to_dto(model: CheckRecord) -> CheckDTO:
        dto = CheckDTO.model_validate(model)
        dto.image_url = f"/v1/checks/{model.id}/image"
        return dto

    @staticmethod
    def to_detail_dto(model: CheckRecord) -> CheckDetailDTO:
        dto = CheckDetailDTO.model_validate(model)
        dto.image_url = f"/v1/checks/{model.id}/image"
        return dto
