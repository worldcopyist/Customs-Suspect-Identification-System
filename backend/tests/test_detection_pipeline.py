from io import BytesIO

import pytest
from PIL import Image

from app.services.detection import InputImageError, normalize_image
from app.workers.inference import InferenceConfig, InferenceError, _parse_results


class _Tensor:
    def __init__(self, value):
        self.value = value

    def cpu(self):
        return self

    def tolist(self):
        return self.value


class _Boxes:
    xyxy = _Tensor([[1.0, 2.0, 18.0, 9.0]])
    conf = _Tensor([0.8])
    cls = _Tensor([0.0])


class _Result:
    names = {0: "sus"}
    orig_shape = (10, 20)
    boxes = _Boxes()


def test_normalize_image_flattens_alpha_and_removes_input_format() -> None:
    original = Image.new("RGBA", (20, 10), (255, 0, 0, 128))
    buffer = BytesIO()
    original.save(buffer, format="PNG")
    normalized, width, height = normalize_image(buffer.getvalue())
    assert (width, height) == (20, 10)
    assert normalized.startswith(b"\xff\xd8")  # normalized JPEG, not user-provided PNG bytes


def test_normalize_image_rejects_non_image_input() -> None:
    with pytest.raises(InputImageError, match="INVALID_IMAGE"):
        normalize_image(b"not an image")


def test_yolo_result_parser_returns_only_contractual_sus_boxes() -> None:
    boxes, warnings = _parse_results([_Result()], InferenceConfig(0.25, 0.45, 320, 100, "cpu"), 20, 10)
    assert warnings == []
    assert boxes[0].class_name == "sus"
    assert boxes[0].bbox == [1.0, 2.0, 18.0, 9.0]


def test_yolo_result_parser_rejects_changed_class_contract() -> None:
    _Result.names = {0: "person"}
    try:
        with pytest.raises(InferenceError) as raised:
            _parse_results([_Result()], InferenceConfig(0.25, 0.45, 320, 100, "cpu"), 20, 10)
        assert raised.value.code == "MODEL_CONTRACT_CHANGED"
    finally:
        _Result.names = {0: "sus"}
