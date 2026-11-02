#!/usr/bin/env python3
"""Runs eyes.py so its textures load from the current style's folder.

Usage: run_eyes.py /path/to/eyes.py [arguments for eyes.py]

eyes.py finds its files in two ways. parse("graphics/eye.svg") uses the working
directory, but pi3d.Texture searches sys.path, whose first entry is normally the
script's own folder, so textures would always come from Adafruit's graphics
folder. Putting the working directory first makes both find the style's files.
eyes.py's folder stays on the path for its gfxutil and snake_eyes_bonnet imports.
"""

import os
import runpy
import sys

eyes = os.path.abspath(sys.argv[1])
sys.path[0:1] = [os.getcwd(), os.path.dirname(eyes)]
sys.argv = sys.argv[1:]
runpy.run_path(eyes, run_name="__main__")
