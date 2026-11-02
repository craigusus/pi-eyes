import io

import pytest
from PIL import Image

from pi_eyes_control.styles import REQUIRED_FILES, StyleStore


def make_style(state_dir, name):
    graphics = state_dir / "styles" / name / "graphics"
    graphics.mkdir(parents=True)
    for file in REQUIRED_FILES:
        (graphics / file).write_bytes(b"placeholder")
    image = Image.new("RGB", (32, 32), (120, 90, 40))
    image.save(graphics / "iris.jpg", "JPEG")


def image_bytes(size=(64, 64), image_format="PNG", mode="RGB"):
    output = io.BytesIO()
    Image.new(mode, size, (10, 200, 60)).save(output, image_format)
    return output.getvalue()


@pytest.fixture
def store(tmp_path):
    for name in ("default", "dragon"):
        make_style(tmp_path, name)
    return StyleStore(tmp_path)
