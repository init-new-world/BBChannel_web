from io import BytesIO

from PIL import Image

from webapp.devices.coordinates import ContentRect, FrameNormalizer, ScreenTransform


def _png(width: int, height: int, color=(20, 40, 60)) -> bytes:
    image = Image.new("RGB", (width, height), color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_screen_transform_maps_standard_landscape_without_offset():
    transform = ScreenTransform.fit(1920, 1080)

    assert transform.rotation == 0
    assert transform.content == ContentRect(0, 0, 1920, 1080)
    assert transform.logical_to_raw(0, 0) == (0, 0)
    assert transform.logical_to_raw(640, 360) == (960, 540)
    assert transform.raw_to_logical(960, 540) == (640, 360)


def test_screen_transform_accounts_for_ultrawide_side_bars():
    transform = ScreenTransform.fit(2400, 1080)

    assert transform.content.x == 240
    assert transform.content.width == 1920
    assert transform.logical_to_raw(0, 360) == (240, 540)
    assert transform.logical_to_raw(1280, 360) == (2160, 540)


def test_screen_transform_accounts_for_tall_landscape_bars():
    transform = ScreenTransform.fit(1280, 800)

    assert transform.content.y == 40
    assert transform.content.height == 720
    assert transform.logical_to_raw(640, 0) == (640, 40)


def test_screen_transform_rotates_portrait_capture_back_to_raw_coordinates():
    transform = ScreenTransform.fit(720, 1280)

    assert transform.rotation == 90
    assert transform.logical_to_raw(0, 0) == (0, 1279)
    assert transform.logical_to_raw(1280, 720) == (719, 0)
    assert transform.raw_to_logical(360, 640) == (639, 360)


def test_frame_normalizer_outputs_base_resolution():
    normalized = FrameNormalizer().normalize(_png(2400, 1080))

    with Image.open(BytesIO(normalized.png)) as image:
        assert image.size == (1280, 720)
    assert normalized.transform.content.x == 240
