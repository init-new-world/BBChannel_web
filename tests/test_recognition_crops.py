from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from webapp.core.errors import AppError, ErrorCode
from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService

cv = pytest.importorskip("cv2")


def _png(image):
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _fixture(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    template = Image.new("RGB", (40, 32), (20, 80, 130))
    draw = ImageDraw.Draw(template)
    draw.rectangle((11, 9, 25, 20), fill="white")
    draw.line((10, 22, 28, 8), fill="black", width=2)
    draw.rectangle((2, 1, 7, 6), fill="yellow")
    template.save(assets / "target.png")
    return template, RecognitionService(ResourceService(assets, tmp_path / "data"))


@pytest.mark.parametrize("grayscale", [False, True])
def test_single_match_crops_template_before_search_and_keeps_global_coordinates(tmp_path, grayscale):
    template, recognition = _fixture(tmp_path)
    screen = Image.new("RGB", (100, 80), "black")
    screen.paste(template.crop((10, 8, 30, 24)), (63, 41))
    result = recognition.match_template(
        _png(screen), "target.png", threshold=0.99, roi=(50, 30, 40, 40),
        template_crop=(10, 8, 30, 24), grayscale=grayscale,
    )
    assert result.matched
    assert result.top_left == [63, 41]
    assert result.size == [20, 16]
    assert result.roi == [50, 30, 40, 40]


def test_batch_crop_and_gray_do_not_mutate_cached_color_template(tmp_path, monkeypatch):
    template, recognition = _fixture(tmp_path)
    screen = Image.new("RGB", (160, 80), "black")
    screen.paste(template.crop((10, 8, 30, 24)), (10, 12))
    screen.paste(template, (85, 25))
    decodes = []
    loads = []
    decode, load = recognition._decode_screenshot, recognition._load_template

    def count_decode(*args):
        decodes.append(1)
        return decode(*args)

    def count_load(*args):
        loads.append(1)
        return load(*args)

    monkeypatch.setattr(recognition, "_decode_screenshot", count_decode)
    monkeypatch.setattr(recognition, "_load_template", count_load)
    results = recognition.match_templates(_png(screen), [
        {"template_path": "target.png", "roi": (0, 0, 50, 50), "template_crop": (10, 8, 30, 24), "grayscale": True},
        {"template_path": "target.png", "roi": (70, 0, 80, 80)},
    ])
    assert len(decodes) == len(loads) == 1
    assert all(result.matched for result in results)
    assert [result.size for result in results] == [[20, 16], [40, 32]]
    assert [result.top_left for result in results] == [[10, 12], [85, 25]]


@pytest.mark.parametrize("api", ["single", "batch", "all"])
def test_grayscale_matching_can_recognize_luminance_when_color_differs(tmp_path, api):
    numpy = pytest.importorskip("numpy")
    assets = tmp_path / "assets"
    assets.mkdir()
    # Keep luminance contrast while removing the original red/green channel contrast.
    values = numpy.random.default_rng(17).integers(0, 2, (20, 20), dtype=numpy.uint8)
    original = numpy.where(values[:, :, None] == 0, [255, 0, 0], [0, 60, 0]).astype(numpy.uint8)
    gray = cv.cvtColor(original, cv.COLOR_RGB2GRAY)
    Image.fromarray(original).save(assets / "target.png")
    screen = Image.new("RGB", (60, 60), "black")
    screen.paste(Image.fromarray(gray).convert("RGB"), (23, 19))
    recognition = RecognitionService(ResourceService(assets, tmp_path / "data"))
    if api == "single":
        result = recognition.match_template(_png(screen), "target.png", threshold=0.99, grayscale=True)
    elif api == "batch":
        result = recognition.match_templates(_png(screen), [{"template_path": "target.png", "threshold": 0.99, "grayscale": True}])[0]
    else:
        result = recognition.match_template_all(_png(screen), "target.png", threshold=0.99, grayscale=True)[0]
    assert result.matched
    assert result.top_left == [23, 19]
    assert not recognition.match_template(_png(screen), "target.png", threshold=0.99).matched


@pytest.mark.parametrize("crop", [(-1, 0, 20, 16), (0, 0, 41, 32), (10, 10, 10, 20), (0, 0, 20)])
@pytest.mark.parametrize("api", ["single", "batch", "all"])
def test_invalid_template_crops_fail_consistently(tmp_path, crop, api):
    _template, recognition = _fixture(tmp_path)
    screen = _png(Image.new("RGB", (80, 80), "black"))
    with pytest.raises(AppError) as raised:
        if api == "single":
            recognition.match_template(screen, "target.png", template_crop=crop, grayscale=True)
        elif api == "batch":
            recognition.match_templates(screen, [{"template_path": "target.png", "template_crop": crop, "grayscale": True}])
        else:
            recognition.match_template_all(screen, "target.png", template_crop=crop, grayscale=True)
    assert raised.value.code == ErrorCode.MATCH_FAILED


def test_gray_template_crop_keeps_alpha_mask_aligned_when_scaled(tmp_path):
    template, recognition = _fixture(tmp_path)
    rgba = template.convert("RGBA")
    draw = ImageDraw.Draw(rgba)
    draw.rectangle((10, 8, 14, 23), fill=(255, 0, 0, 0))
    rgba.save(recognition._resources.assets_dir / "alpha.png")
    screen = Image.new("RGB", (80, 80), (50, 120, 170))
    resized = rgba.crop((10, 8, 30, 24)).resize((40, 32))
    screen.paste(resized, (25, 29), resized)
    result = recognition.match_template(
        _png(screen), "alpha.png", threshold=0.9, template_crop=(10, 8, 30, 24), grayscale=True, scales=(2,),
    )
    assert result.matched
    assert result.top_left == [25, 29]
    assert result.size == [40, 32]


@pytest.mark.parametrize("api", ["single", "batch", "all"])
@pytest.mark.parametrize("kind", ["crop", "grayscale", "scaled", "masked"])
def test_uninformative_transformed_templates_never_manufacture_a_match(tmp_path, api, kind):
    numpy = pytest.importorskip("numpy")
    template, recognition = _fixture(tmp_path)
    options = {}
    if kind == "crop":
        options["template_crop"] = (30, 25, 35, 30)
    elif kind == "grayscale":
        cells = numpy.indices((12, 12)).sum(axis=0) % 2
        pixels = numpy.where(cells[:, :, None] == 0, [255, 0, 0], [0, 130, 0]).astype(numpy.uint8)
        Image.fromarray(pixels).save(recognition._resources.assets_dir / "target.png")
        options["grayscale"] = True
    elif kind == "scaled":
        options.update(template_crop=(10, 8, 30, 24), grayscale=True, scales=(0.05,))
    else:
        mask = Image.new("L", template.size)
        ImageDraw.Draw(mask).rectangle((30, 25, 34, 29), fill=255)
        mask.save(recognition._resources.assets_dir / "mask.png")
        options.update(grayscale=True, mask_path="mask.png")
    screen = _png(Image.new("RGB", (80, 80), "black"))
    if api == "single":
        results = [recognition.match_template(screen, "target.png", threshold=0.99, **options)]
    elif api == "batch":
        results = recognition.match_templates(screen, [{"template_path": "target.png", "threshold": 0.99, **options}])
    else:
        results = recognition.match_template_all(screen, "target.png", threshold=0.99, **options)
    assert not any(result.matched for result in results)
    assert all(result.confidence == -1 for result in results)


@pytest.mark.parametrize("crop", [(0, 0, float("inf"), 12), (-0.9, 0, 12, 12), (0, 0, 11.9, 12), (False, 0, 12, 12)])
def test_crop_coordinates_must_be_actual_integers(tmp_path, crop):
    _template, recognition = _fixture(tmp_path)
    with pytest.raises(AppError) as raised:
        recognition.match_template(_png(Image.new("RGB", (80, 80))), "target.png", template_crop=crop)
    assert raised.value.code == ErrorCode.MATCH_FAILED
