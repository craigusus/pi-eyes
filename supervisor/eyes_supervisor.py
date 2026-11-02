#!/usr/bin/env python3
"""Runs Adafruit's eyes.py from the folder of the selected style.

eyes.py loads graphics/... relative to its working directory, so each style is
a folder holding its own graphics/ and eyes.py needs no changes. A style change
restarts only eyes.py. A style that dies at startup falls back to the last good
one, so a bad style can't leave the eyes dead.

Standard library only: this runs under Adafruit's Python venv.
"""

import argparse
import logging
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger("eyes_supervisor")

DEFAULT_STYLE = "default"
REQUIRED_FILES = ("eye.svg", "iris.jpg", "sclera.png", "lid.png")
NAME_RE = re.compile(r"[a-z0-9-]{1,32}")
HEALTHY_AFTER = 20.0  # Must outlast Python + pi3d startup on a Pi 3
RESTART_DELAY = 1.0
MAX_BACKOFF = 60.0
STOP_TIMEOUT = 5.0


class Supervisor:
    def __init__(self, state_dir, eyes, radius, python=sys.executable,
                 healthy_after=HEALTHY_AFTER, clock=time.monotonic,
                 spawn=subprocess.Popen):
        self.state_dir = Path(state_dir)
        self.eyes = str(eyes)
        self.radius = radius
        self.python = python
        self.healthy_after = healthy_after
        self.clock = clock
        self.spawn = spawn
        self.child = None
        self.running = None  # Style of the current child
        self.started_at = 0.0
        self.healthy = False
        self.last_good = None
        self.queue = []  # Styles still to try, best first
        self.seen_request = object()  # Differs from any real request
        self.retry_at = None
        self.failures = 0

    def _read_request(self):
        """Returns (name, mtime). The mtime means re-selecting a style that
        failed earlier tries it again."""
        path = self.state_dir / "current-style"
        try:
            return path.read_text().strip(), path.stat().st_mtime_ns
        except FileNotFoundError:
            return DEFAULT_STYLE, None

    def _style_dir(self, name):
        """Returns the style's folder, or None if it isn't usable."""
        if not NAME_RE.fullmatch(name):
            return None
        folder = self.state_dir / "styles" / name
        if all((folder / "graphics" / f).is_file() for f in REQUIRED_FILES):
            return folder
        return None

    def _write_active(self, name):
        path = self.state_dir / "active-style"
        if name is None:
            path.unlink(missing_ok=True)
            return
        tmp = path.with_name(f".active-style.{os.getpid()}.tmp")
        tmp.write_text(name + "\n")
        os.chmod(tmp, 0o664)
        os.replace(tmp, path)

    def _candidates(self, *names):
        return list(dict.fromkeys(n for n in names if n))

    def _start_next(self):
        """Starts the first usable style in the queue."""
        self.retry_at = None
        while self.queue:
            name = self.queue.pop(0)
            folder = self._style_dir(name)
            if folder is None:
                log.warning("Style %r is missing or incomplete", name)
                continue
            command = [self.python, self.eyes, "--radius", str(self.radius)]
            try:
                self.child = self.spawn(command, cwd=folder)
            except OSError as err:
                log.error("Could not start eyes.py: %s", err)
                continue
            self.running = name
            self.started_at = self.clock()
            self.healthy = False
            self._write_active(name)
            log.info("Started style %r", name)
            return
        # Nothing could run, not even the default. Keep trying, more slowly.
        self.running = None
        self._write_active(None)
        delay = min(RESTART_DELAY * 2 ** self.failures, MAX_BACKOFF)
        self.failures += 1
        self.retry_at = self.clock() + delay
        self.queue = self._candidates(DEFAULT_STYLE, self.last_good)
        log.error("No style could start; retrying in %.0fs", delay)

    def _handle_exit(self, code):
        ran_for = self.clock() - self.started_at
        name = self.running
        self.child = None
        if self.healthy or ran_for >= self.healthy_after:
            log.warning("Style %r exited with %s; restarting", name, code)
            self.last_good = name
            self.failures = 0
            self.queue = self._candidates(name, DEFAULT_STYLE)
            self.retry_at = self.clock() + RESTART_DELAY
        else:
            log.error("Style %r failed at startup with %s", name, code)
            self._start_next()

    def stop_child(self):
        if self.child is None:
            return
        self.child.terminate()
        try:
            self.child.wait(timeout=STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.child.kill()
            self.child.wait()
        self.child = None

    def tick(self):
        request = self._read_request()
        if request != self.seen_request:
            self.seen_request = request
            name = request[0]
            if self.child is not None and name == self.running:
                return  # Already showing it
            self.stop_child()
            self.queue = self._candidates(name, self.last_good, DEFAULT_STYLE)
            self._start_next()
        elif self.child is not None:
            code = self.child.poll()
            if code is not None:
                self._handle_exit(code)
            elif (not self.healthy and
                  self.clock() - self.started_at >= self.healthy_after):
                self.healthy = True
                self.last_good = self.running
                self.failures = 0
        elif self.retry_at is not None and self.clock() >= self.retry_at:
            self._start_next()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default="/var/lib/pi-eyes")
    parser.add_argument("--eyes", default="/opt/Pi_Eyes/eyes.py")
    parser.add_argument("--radius", type=int, default=128)
    parser.add_argument("--poll", type=float, default=0.5)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(name)s: %(levelname)s: %(message)s")

    stopping = []
    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name),
                          lambda *_: stopping.append(True))

    supervisor = Supervisor(args.state_dir, args.eyes, args.radius)
    try:
        while not stopping:
            supervisor.tick()
            time.sleep(args.poll)
    finally:
        supervisor.stop_child()


if __name__ == "__main__":
    main()
