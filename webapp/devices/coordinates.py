from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from webapp.core.errors import AppError, ErrorCode


BASE_WIDTH = 1280
BASE_HEIGHT = 720


@dataclass(frozen=True)
class ContentRect:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class ScreenTransform:
    raw_width: int
    raw_height: int
    rotation: int
    content: ContentRect
    base_width: int = BASE_WIDTH
    base_height: int = BASE_HEIGHT

    @classmethod
    def fit(
        cls,
        raw_width: int,
        raw_height: int,
        *,
        rotation: int | None = None,
        base_width: int = BASE_WIDTH,
        base_height: int = BASE_HEIGHT,
    ) -> "ScreenTransform":
        if raw_width <= 0 or raw_height <= 0:
            raise ValueError("Raw screen dimensions must be positive.")
        if base_width <= 0 or base_height <= 0:
            raise ValueError("Base screen dimensions must be positive.")
        resolved_rotation = (90 if raw_height > raw_width else 0) if rotation is None else rotation
        if resolved_rotation not in {0, 90, 180, 270}:
            raise ValueError("Rotation must be 0, 90, 180, or 270 degrees.")

        normalized_width, normalized_height = (
            (raw_height, raw_width)
            if resolved_rotation in {90, 270}
            else (raw_width, raw_height)
        )
        content = _fit_content_rect(
            normalized_width,
            normalized_height,
            base_width / base_height,
        )
        return cls(
            raw_width=raw_width,
            raw_height=raw_height,
            rotation=resolved_rotation,
            content=content,
            base_width=base_width,
            base_height=base_height,
        )

    def logical_to_raw(self, x: float, y: float) -> tuple[int, int]:
        logical_x = min(max(float(x), 0.0), float(self.base_width))
        logical_y = min(max(float(y), 0.0), float(self.base_height))
        normalized_x = self.content.x + logical_x * self.content.width / self.base_width
        normalized_y = self.content.y + logical_y * self.content.height / self.base_height
        raw_x, raw_y = self._normalized_to_raw(normalized_x, normalized_y)
        return (
            min(max(round(raw_x), 0), self.raw_width - 1),
            min(max(round(raw_y), 0), self.raw_height - 1),
        )

    def raw_to_logical(self, x: float, y: float) -> tuple[int, int]:
        normalized_x, normalized_y = self._raw_to_normalized(float(x), float(y))
        logical_x = (normalized_x - self.content.x) * self.base_width / self.content.width
        logical_y = (normalized_y - self.content.y) * self.base_height / self.content.height
        return (
            min(max(round(logical_x), 0), self.base_width),
            min(max(round(logical_y), 0), self.base_height),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def _normalized_to_raw(self, x: float, y: float) -> tuple[float, float]:
        if self.rotation == 0:
            return x, y
        if self.rotation == 90:
            return y, self.raw_height - 1 - x
        if self.rotation == 180:
            return self.raw_width - 1 - x, self.raw_height - 1 - y
        return self.raw_width - 1 - y, x

    def _raw_to_normalized(self, x: float, y: float) -> tuple[float, float]:
        if self.rotation == 0:
            return x, y
        if self.rotation == 90:
            return self.raw_height - 1 - y, x
        if self.rotation == 180:
            return self.raw_width - 1 - x, self.raw_height - 1 - y
        return y, self.raw_width - 1 - x


@dataclass(frozen=True)
class NormalizedFrame:
    png: bytes
    transform: ScreenTransform


class FrameNormalizer:
    def __init__(
        self,
        *,
        rotation: int | None = None,
        base_width: int = BASE_WIDTH,
        base_height: int = BASE_HEIGHT,
    ) -> None:
        self.rotation = rotation
        self.base_width = base_width
        self.base_height = base_height

    def normalize(self, image_bytes: bytes) -> NormalizedFrame:
        try:
            with Image.open(BytesIO(image_bytes)) as source:
                image = source.convert("RGB")
        except (OSError, UnidentifiedImageError) as exc:
            raise AppError(
                ErrorCode.SNAPSHOT_FAILED,
                "Screenshot is not a valid image.",
            ) from exc

        transform = ScreenTransform.fit(
            image.width,
            image.height,
            rotation=self.rotation,
            base_width=self.base_width,
            base_height=self.base_height,
        )
        normalized = _rotate_image(image, transform.rotation)
        content = transform.content
        cropped = normalized.crop(
            (content.x, content.y, content.x + content.width, content.y + content.height)
        )
        if cropped.size != (self.base_width, self.base_height):
            cropped = cropped.resize((self.base_width, self.base_height), Image.Resampling.LANCZOS)
        output = BytesIO()
        cropped.save(output, format="PNG", optimize=False)
        return NormalizedFrame(output.getvalue(), transform)


def _fit_content_rect(width: int, height: int, target_aspect: float) -> ContentRect:
    current_aspect = width / height
    if current_aspect > target_aspect:
        content_width = min(width, round(height * target_aspect))
        return ContentRect((width - content_width) // 2, 0, content_width, height)
    content_height = min(height, round(width / target_aspect))
    return ContentRect(0, (height - content_height) // 2, width, content_height)


def _rotate_image(image: Image.Image, rotation: int) -> Image.Image:
    if rotation == 90:
        return image.transpose(Image.Transpose.ROTATE_270)
    if rotation == 180:
        return image.transpose(Image.Transpose.ROTATE_180)
    if rotation == 270:
        return image.transpose(Image.Transpose.ROTATE_90)
    return image
