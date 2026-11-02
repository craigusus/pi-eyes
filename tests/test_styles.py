import io

import pytest
from PIL import Image

from conftest import image_bytes
from make_starter_styles import build
from pi_eyes_control.styles import (InvalidStyle, StyleConflict, StyleNotFound,
                                    valid_name)


@pytest.mark.parametrize("name", [
    "../default", "..", "a/b", "a\\b", "UPPER", "", "with space", "dragon\n",
    "x" * 33, None, 7,
])
def test_bad_names_are_rejected(store, name):
    assert not valid_name(name)
    with pytest.raises(StyleNotFound):
        store.select(name)


def test_select_writes_requested_style(store):
    store.select("dragon")
    assert store.requested() == "dragon"
    assert (store.state_dir / "current-style").read_text() == "dragon\n"


def test_requested_defaults_when_never_set_or_corrupt(store):
    assert store.requested() == "default"
    (store.state_dir / "current-style").write_text("../../etc")
    assert store.requested() == "default"


def test_incomplete_style_is_not_listed(store):
    (store.styles_dir / "dragon" / "graphics" / "lid.png").unlink()
    assert store.names() == ["default"]


def test_add_reencodes_to_texture_sizes(store):
    store.add("mine", image_bytes(), image_bytes(mode="RGBA"), shape="dragon")
    graphics = store.styles_dir / "mine" / "graphics"
    with Image.open(graphics / "iris.jpg") as iris:
        assert (iris.format, iris.size) == ("JPEG", (512, 512))
    with Image.open(graphics / "sclera.png") as sclera:
        assert (sclera.format, sclera.mode, sclera.size) == ("PNG", "RGBA", (1024, 1024))
    assert store.names() == ["default", "dragon", "mine"]
    assert store.is_uploaded("mine")


def test_add_without_sclera_uses_the_shape_style(store):
    (store.styles_dir / "dragon" / "graphics" / "sclera.png").write_bytes(b"dragon")
    store.add("mine", image_bytes(), shape="dragon")
    assert (store.styles_dir / "mine" / "graphics" / "sclera.png").read_bytes() == b"dragon"


@pytest.mark.parametrize("data,message", [
    (b"not an image", "not a readable"),
    (image_bytes(size=(64, 32)), "square"),
    (image_bytes(image_format="GIF", mode="P"), "JPEG or PNG"),
    (image_bytes(size=(5000, 5000)), "at most"),
])
def test_add_rejects_bad_images_and_leaves_nothing_behind(store, data, message):
    with pytest.raises(InvalidStyle, match=message):
        store.add("mine", data)
    assert sorted(p.name for p in store.styles_dir.iterdir()) == ["default", "dragon"]


def test_truncated_image_is_rejected(store):
    with pytest.raises(InvalidStyle, match="not a readable"):
        store.add("mine", image_bytes(image_format="JPEG")[:200])


def test_add_rejects_existing_name(store):
    with pytest.raises(StyleConflict):
        store.add("dragon", image_bytes())


def test_builtin_cannot_be_deleted(store):
    with pytest.raises(StyleConflict):
        store.delete("dragon")
    assert store.exists("dragon")


def test_style_in_use_cannot_be_deleted(store):
    store.add("mine", image_bytes())
    store.select("mine")
    with pytest.raises(StyleConflict):
        store.delete("mine")
    store.select("default")
    (store.state_dir / "active-style").write_text("mine\n")
    with pytest.raises(StyleConflict):
        store.delete("mine")
    (store.state_dir / "active-style").write_text("default\n")
    store.delete("mine")
    assert not store.exists("mine")


def test_preview_is_a_jpeg_disc(store):
    with Image.open(io.BytesIO(store.preview("default"))) as preview:
        assert (preview.format, preview.size) == ("JPEG", (160, 160))
        assert all(c > 240 for c in preview.getpixel((0, 0)))  # Outside the disc
        assert all(c < 30 for c in preview.getpixel((80, 80)))  # Pupil


def test_starter_styles_build_and_keep_uploads(tmp_path):
    source = tmp_path / "graphics"
    source.mkdir()
    for file in ("eye.svg", "sclera.png", "lid.png", "dragon-eye.svg", "dragon-sclera.png"):
        (source / file).write_bytes(file.encode())
    Image.new("RGB", (16, 16), (150, 160, 60)).save(source / "iris.jpg")
    Image.new("RGB", (16, 16), (200, 40, 30)).save(source / "dragon-iris.jpg")
    dest = tmp_path / "styles"
    (dest / "mine").mkdir(parents=True)

    build(source, dest)
    build(source, dest)  # Re-running must work

    assert sorted(p.name for p in dest.iterdir()) == [
        "blue", "default", "dragon", "green", "mine", "red"]
    dragon = dest / "dragon" / "graphics"
    assert (dragon / "eye.svg").read_bytes() == b"dragon-eye.svg"
    assert (dragon / "sclera.png").read_bytes() == b"dragon-sclera.png"
    assert (dest / "default" / "graphics" / "iris.jpg").read_bytes() == (source / "iris.jpg").read_bytes()
    with Image.open(dest / "blue" / "graphics" / "iris.jpg") as blue:
        red, _, bluish = blue.convert("RGB").getpixel((8, 8))
    assert bluish > red
