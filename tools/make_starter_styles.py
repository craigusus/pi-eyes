#!/usr/bin/env python3
"""Builds the built-in style folders from Adafruit's graphics folder.

Safe to re-run: built-in styles are rebuilt and uploaded styles are left alone.
"""

import argparse
import shutil
from pathlib import Path

from PIL import Image

# Target hue in degrees and saturation gain, tuned on Adafruit's iris.jpg, which
# runs from yellow-brown at the pupil to teal at the edge.
RECOLOURS = {
    "blue": (212, 1.6),
    "green": (118, 1.6),
    "red": (2, 2.0),
}
SOURCE_HUE = 75  # Roughly the middle of iris.jpg's hues, in degrees
HUE_SPREAD = 0.2  # How much of the original hue variation survives


def recolour(source, target, degrees, saturation):
    """Pulls every hue close to the target. Keeping a little of the original
    variation stops the iris looking flat."""
    with Image.open(source) as image:
        hue, sat, value = image.convert("RGB").convert("HSV").split()
    centre = SOURCE_HUE / 360 * 256
    goal = degrees / 360 * 256

    def pull(h):
        offset = (h - centre + 128) % 256 - 128
        return round(goal + offset * HUE_SPREAD) % 256

    hue = hue.point(pull)
    sat = sat.point(lambda s: min(round(s * saturation), 255))
    Image.merge("HSV", (hue, sat, value)).convert("RGB").save(
        target, "JPEG", quality=92)


def build(source, dest):
    """Each style is (source file for eye.svg, iris.jpg, sclera.png)."""
    source, dest = Path(source), Path(dest)
    layouts = {
        "default": ("eye.svg", "iris.jpg", "sclera.png"),
        "dragon": ("dragon-eye.svg", "dragon-iris.jpg", "dragon-sclera.png"),
    }
    layouts.update({name: layouts["default"] for name in RECOLOURS})
    for name, (svg, iris, sclera) in layouts.items():
        graphics = dest / name / "graphics"
        graphics.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / svg, graphics / "eye.svg")
        shutil.copyfile(source / sclera, graphics / "sclera.png")
        shutil.copyfile(source / "lid.png", graphics / "lid.png")
        if name in RECOLOURS:
            recolour(source / iris, graphics / "iris.jpg", *RECOLOURS[name])
        else:
            shutil.copyfile(source / iris, graphics / "iris.jpg")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="/opt/Pi_Eyes/graphics")
    parser.add_argument("--dest", default="/var/lib/pi-eyes/styles")
    args = parser.parse_args()
    build(args.source, args.dest)


if __name__ == "__main__":
    main()
