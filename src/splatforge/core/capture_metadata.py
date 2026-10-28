"""Descriptive capture evidence; never a calibration or physical-device identity."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CaptureMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    origin: Literal["exif", "container_tags"]
    make: str | None = Field(default=None, max_length=256)
    model: str | None = Field(default=None, max_length=256)
    lens_model: str | None = Field(default=None, max_length=256)
    captured_at: datetime | None = None
    focal_length_mm: float | None = Field(default=None, gt=0)
    focal_length_35mm: float | None = Field(default=None, gt=0)
    exposure_seconds: float | None = Field(default=None, gt=0)
    f_number: float | None = Field(default=None, gt=0)
    iso: int | None = Field(default=None, gt=0, strict=True)
    gps_present: bool | None = None

    @property
    def device_label(self) -> str:
        """Partial evidence stays inspectable, but is not a strong grouping key."""
        if not self.make or not self.model:
            return "Unknown device"
        if self.model.casefold().startswith(self.make.casefold() + " "):
            return self.model
        return f"{self.make} {self.model}"
