from io import BytesIO

import pytest
from PIL import Image

from webapp.services.recognition import RecognitionService
from webapp.services.resources import ResourceService

pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


def _png(image):
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _fixture(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    pixels = np.random.default_rng(314).integers(10, 240, (16, 20, 4), dtype=np.uint8)
    pixels[:, :, 3] = 255
    pixels[:, 8:, 3] = 0
    Image.fromarray(pixels).save(assets / "target.png")
    altered = pixels[:, :, :3].copy()
    altered[:, 8:] = 0
    return pixels, _png(Image.fromarray(altered)), RecognitionService(ResourceService(assets, tmp_path / "data"))


def _matches(recognition, api, screen, **options):
    if api == "single":
        return [recognition.match_template(screen, "target.png", threshold=0.99, **options)]
    if api == "batch":
        return recognition.match_templates(screen, [{"template_path": "target.png", "threshold": 0.99, **options}])
    return recognition.match_template_all(screen, "target.png", threshold=0.99, **options)


@pytest.mark.parametrize("api", ["single", "batch", "all"])
@pytest.mark.parametrize("grayscale", [False, True])
@pytest.mark.parametrize("crop", [None, (2, 2, 18, 14)])
def test_alpha_mask_can_be_disabled_without_changing_the_default(tmp_path, api, grayscale, crop):
    pixels, altered, recognition = _fixture(tmp_path)
    options = {"grayscale": grayscale, "template_crop": crop}
    assert any(match.matched for match in _matches(recognition, api, altered, **options))
    assert not any(match.matched for match in _matches(recognition, api, altered, use_alpha_mask=False, **options))
    exact = _png(Image.fromarray(pixels[:, :, :3]))
    results = _matches(recognition, api, exact, use_alpha_mask=False, **options)
    assert any(match.matched for match in results)
    assert next(match for match in results if match.matched).top_left == ([2, 2] if crop else [0, 0])


@pytest.mark.parametrize("api", ["single", "batch", "all"])
def test_disabling_implicit_alpha_keeps_an_explicit_mask(tmp_path, api):
    pixels, _altered, recognition = _fixture(tmp_path)
    mask = np.zeros((16, 20), dtype=np.uint8)
    mask[:, 8:] = 255
    Image.fromarray(mask).save(recognition._resources.assets_dir / "mask.png")
    screen = pixels[:, :, :3].copy()
    screen[:, :8] = 0
    results = _matches(
        recognition, api, _png(Image.fromarray(screen)),
        mask_path="mask.png", use_alpha_mask=False, grayscale=True,
    )
    assert any(match.matched for match in results)
    assert next(match for match in results if match.matched).top_left == [0, 0]


def test_batch_alpha_modes_do_not_modify_the_cached_mask(tmp_path, monkeypatch):
    _pixels, altered, recognition = _fixture(tmp_path)
    load = recognition._load_template
    loads = []

    def count_load(*args):
        loads.append(1)
        return load(*args)

    monkeypatch.setattr(recognition, "_load_template", count_load)
    results = recognition.match_templates(altered, [
        {"template_path": "target.png", "threshold": 0.99},
        {"template_path": "target.png", "threshold": 0.99, "use_alpha_mask": False},
        {"template_path": "target.png", "threshold": 0.99},
    ])
    assert [result.matched for result in results] == [True, False, True]
    assert loads == [1]
