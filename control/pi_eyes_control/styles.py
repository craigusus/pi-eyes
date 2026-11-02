"""The style folders and the state files shared with eyes_supervisor.py.

current-style holds the style that was asked for. active-style is written by
the supervisor and holds the one actually running, which differs after a
fallback.
"""

import io
import math
import os
import re
import shutil
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

from PIL import Image

DEFAULT_STYLE = "default"
REQUIRED_FILES = ("eye.svg", "iris.jpg", "sclera.png", "lid.png")
NAME_RE = re.compile(r"[a-z0-9-]{1,32}")
UPLOADED_MARKER = "uploaded"
IRIS_SIZE = 512  # Same sizes as Adafruit's textures
SCLERA_SIZE = 1024
MAX_UPLOAD_PIXELS = 4096
PREVIEW_SIZE = 160
PREVIEW_PUPIL = 0.3


class StyleError(Exception):
    """A request that can't be met, with a message safe to show the user."""


class InvalidStyle(StyleError):
    pass


class StyleNotFound(StyleError):
    pass


class StyleConflict(StyleError):
    pass


def valid_name(name):
    return isinstance(name, str) and NAME_RE.fullmatch(name) is not None


def _read_name(path):
    try:
        name = path.read_text().strip()
    except FileNotFoundError:
        return None
    return name if valid_name(name) else None


def _load_square(data, label, size, mode):
    """Decodes an upload and returns it at Adafruit's texture size."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ("JPEG", "PNG"):
                raise InvalidStyle(f"{label} must be a JPEG or PNG image")
            if image.width != image.height:
                raise InvalidStyle(f"{label} must be square")
            if image.width > MAX_UPLOAD_PIXELS:
                raise InvalidStyle(
                    f"{label} must be at most {MAX_UPLOAD_PIXELS}px wide")
            return image.convert(mode).resize((size, size),
                                              Image.Resampling.LANCZOS)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise InvalidStyle(f"{label} is not a readable image") from None


@lru_cache(maxsize=64)
def _render_preview(iris_path, _mtime):
    """Wraps the polar iris texture into a disc, as the eye mesh does: the top
    of the texture meets the pupil and the bottom is the outer edge."""
    with Image.open(iris_path) as image:
        texture = image.convert("RGB").resize((256, 256))
    source = texture.load()
    preview = Image.new("RGB", (PREVIEW_SIZE, PREVIEW_SIZE), (255, 255, 255))
    pixels = preview.load()
    centre = (PREVIEW_SIZE - 1) / 2
    for y in range(PREVIEW_SIZE):
        for x in range(PREVIEW_SIZE):
            dx, dy = x - centre, y - centre
            radius = math.hypot(dx, dy) / centre
            if radius > 1:
                continue
            if radius < PREVIEW_PUPIL:
                pixels[x, y] = (0, 0, 0)
                continue
            u = (math.atan2(dy, dx) / (2 * math.pi)) % 1
            v = (radius - PREVIEW_PUPIL) / (1 - PREVIEW_PUPIL)
            pixels[x, y] = source[min(int(u * 256), 255), min(int(v * 256), 255)]
    output = io.BytesIO()
    preview.save(output, "JPEG", quality=85)
    return output.getvalue()


class StyleStore:
    def __init__(self, state_dir):
        self.state_dir = Path(state_dir)
        self.styles_dir = self.state_dir / "styles"
        self.lock = threading.Lock()

    def exists(self, name):
        if not valid_name(name):
            return False
        graphics = self.styles_dir / name / "graphics"
        return all((graphics / f).is_file() for f in REQUIRED_FILES)

    def is_uploaded(self, name):
        return (self.styles_dir / name / UPLOADED_MARKER).exists()

    def names(self):
        if not self.styles_dir.is_dir():
            return []
        return sorted(p.name for p in self.styles_dir.iterdir()
                      if self.exists(p.name))

    def requested(self):
        return _read_name(self.state_dir / "current-style") or DEFAULT_STYLE

    def active(self):
        return _read_name(self.state_dir / "active-style")

    def select(self, name):
        if not self.exists(name):
            raise StyleNotFound(f"No style called {name!r}")
        # Replaced whole, so the supervisor can't read a partial name. The new
        # mtime also makes it retry a style that failed earlier.
        path = self.state_dir / "current-style"
        tmp = path.with_name(f".current-style.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(name + "\n")
        os.chmod(tmp, 0o664)
        os.replace(tmp, path)

    def add(self, name, iris, sclera=None, shape=DEFAULT_STYLE):
        """Creates a style from uploaded images. They are re-encoded, so only
        pixels from the upload ever reach eyes.py, which runs with more rights
        than this service."""
        if not valid_name(name):
            raise InvalidStyle(
                "Names can only use lowercase letters, digits and hyphens "
                "(32 characters at most)")
        if not self.exists(shape):
            raise StyleNotFound(f"No style called {shape!r}")
        iris_image = _load_square(iris, "Iris", IRIS_SIZE, "RGB")
        sclera_image = (None if sclera is None else
                        _load_square(sclera, "Sclera", SCLERA_SIZE, "RGBA"))
        source = self.styles_dir / shape / "graphics"
        with self.lock:
            target = self.styles_dir / name
            if target.exists():
                raise StyleConflict(f"A style called {name!r} already exists")
            # Built aside and renamed, so a half-made style is never listed.
            building = Path(tempfile.mkdtemp(prefix=".new-", dir=self.styles_dir))
            try:
                graphics = building / "graphics"
                graphics.mkdir()
                shutil.copyfile(source / "eye.svg", graphics / "eye.svg")
                shutil.copyfile(source / "lid.png", graphics / "lid.png")
                iris_image.save(graphics / "iris.jpg", "JPEG", quality=92)
                if sclera_image is None:
                    shutil.copyfile(source / "sclera.png", graphics / "sclera.png")
                else:
                    sclera_image.save(graphics / "sclera.png", "PNG")
                (building / UPLOADED_MARKER).touch()
                os.chmod(building, 0o775)
                os.replace(building, target)
            except BaseException:
                shutil.rmtree(building, ignore_errors=True)
                raise

    def delete(self, name):
        if not self.exists(name):
            raise StyleNotFound(f"No style called {name!r}")
        if not self.is_uploaded(name):
            raise StyleConflict("Built-in styles can't be deleted")
        with self.lock:
            if name in (self.requested(), self.active()):
                raise StyleConflict("This style is in use; select another first")
            shutil.rmtree(self.styles_dir / name)

    def preview(self, name):
        if not self.exists(name):
            raise StyleNotFound(f"No style called {name!r}")
        iris = self.styles_dir / name / "graphics" / "iris.jpg"
        return _render_preview(str(iris), iris.stat().st_mtime_ns)
