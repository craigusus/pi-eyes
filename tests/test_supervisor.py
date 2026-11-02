import os
import sys
import time

import pytest

from conftest import make_style
from eyes_supervisor import HEALTHY_AFTER, Supervisor


class FakeChild:
    def __init__(self, style):
        self.style = style
        self.code = None
        self.terminated = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = -15

    def kill(self):
        self.code = -9

    def wait(self, timeout=None):
        return self.code


class Harness:
    """A supervisor with a fake clock and fake child processes."""

    def __init__(self, state_dir):
        self.state_dir = state_dir
        self.now = 100.0
        self.children = []
        self.commands = []
        self.writes = 0
        self.supervisor = Supervisor(state_dir, "/opt/Pi_Eyes/eyes.py", 240,
                                     python="python", clock=lambda: self.now,
                                     spawn=self._spawn)

    def _spawn(self, command, cwd):
        self.commands.append(command)
        child = FakeChild(cwd.name)
        self.children.append(child)
        return child

    def select(self, name):
        self.writes += 1
        path = self.state_dir / "current-style"
        path.write_text(name + "\n")
        # Distinct mtimes even when the filesystem clock is coarse
        os.utime(path, ns=(self.writes * 10**9, self.writes * 10**9))

    def tick(self, advance=0.0):
        self.now += advance
        self.supervisor.tick()

    @property
    def child(self):
        return self.children[-1]

    @property
    def active(self):
        path = self.state_dir / "active-style"
        return path.read_text().strip() if path.exists() else None

    def started(self):
        return [child.style for child in self.children]


@pytest.fixture
def harness(tmp_path):
    for name in ("default", "dragon", "blue"):
        make_style(tmp_path, name)
    return Harness(tmp_path)


def test_starts_default_with_no_selection(harness):
    harness.tick()
    assert harness.started() == ["default"]
    assert harness.active == "default"
    assert harness.commands[0] == ["python", "/opt/Pi_Eyes/eyes.py", "--radius", "240"]


def test_restores_selected_style_at_boot(harness):
    harness.select("dragon")
    harness.tick()
    assert harness.started() == ["dragon"]


def test_style_change_restarts_child_in_new_folder(harness):
    harness.tick()
    first = harness.child
    harness.select("dragon")
    harness.tick(1)
    assert first.terminated
    assert harness.started() == ["default", "dragon"]
    assert harness.active == "dragon"


def test_stable_state_does_not_restart(harness):
    harness.tick()
    for _ in range(5):
        harness.tick(1)
    assert harness.started() == ["default"]


def test_reselecting_running_style_does_not_restart(harness):
    harness.select("dragon")
    harness.tick()
    harness.select("dragon")
    harness.tick(1)
    assert harness.started() == ["dragon"]


def test_startup_crash_falls_back_to_last_good(harness):
    harness.select("dragon")
    harness.tick()
    harness.tick(HEALTHY_AFTER)  # dragon is now known good
    harness.select("blue")
    harness.tick(1)
    harness.child.code = 1
    harness.tick(1)
    assert harness.started() == ["dragon", "blue", "dragon"]
    assert harness.active == "dragon"


def test_failed_style_is_not_retried_until_selected_again(harness):
    harness.tick()
    harness.tick(HEALTHY_AFTER)
    harness.select("blue")
    harness.tick(1)
    harness.child.code = 1
    harness.tick(1)
    assert harness.started() == ["default", "blue", "default"]
    for _ in range(5):
        harness.tick(5)
    assert harness.started() == ["default", "blue", "default"]
    harness.select("blue")
    harness.tick(1)
    assert harness.started() == ["default", "blue", "default", "blue"]


def test_startup_crash_with_no_last_good_uses_default(harness):
    harness.select("blue")
    harness.tick()
    harness.child.code = 1
    harness.tick(1)
    assert harness.started() == ["blue", "default"]
    assert harness.active == "default"


def test_incomplete_style_falls_back_without_starting(harness):
    (harness.state_dir / "styles" / "blue" / "graphics" / "eye.svg").unlink()
    harness.select("blue")
    harness.tick()
    assert harness.started() == ["default"]
    assert harness.active == "default"


@pytest.mark.parametrize("name", ["../../evil", "nope", "UPPER"])
def test_invalid_selection_falls_back(harness, name):
    (harness.state_dir / "current-style").write_text(name)
    harness.tick()
    assert harness.started() == ["default"]


def test_healthy_crash_restarts_same_style_after_delay(harness):
    harness.select("dragon")
    harness.tick()
    harness.tick(HEALTHY_AFTER)
    harness.child.code = 1
    harness.tick(1)
    assert harness.started() == ["dragon"]  # Waiting out the delay
    harness.tick(1)
    assert harness.started() == ["dragon", "dragon"]
    assert harness.active == "dragon"


def test_crash_found_late_still_counts_as_healthy(harness):
    harness.select("dragon")
    harness.tick()
    harness.child.code = 1
    harness.tick(HEALTHY_AFTER + 1)  # No tick saw it running past the window
    harness.tick(2)
    assert harness.started() == ["dragon", "dragon"]


def test_all_styles_failing_backs_off_and_recovers(harness):
    harness.tick()
    harness.child.code = 1
    harness.tick(1)
    assert harness.active is None
    harness.tick(0.5)
    assert harness.started() == ["default"]  # Still waiting: 1s delay
    harness.tick(0.5)
    assert harness.started() == ["default", "default"]
    harness.child.code = 1
    harness.tick(1)
    harness.tick(1)
    assert harness.started() == ["default", "default"]  # Now a 2s delay
    harness.tick(1)
    assert harness.started() == ["default", "default", "default"]
    assert harness.active == "default"
    harness.tick(HEALTHY_AFTER)
    assert harness.supervisor.failures == 0


def test_spawn_error_tries_next_style(harness):
    real_spawn = harness._spawn

    def failing_spawn(command, cwd):
        if cwd.name == "blue":
            raise OSError("no such file")
        return real_spawn(command, cwd)

    harness.supervisor.spawn = failing_spawn
    harness.select("blue")
    harness.tick()
    assert harness.started() == ["default"]


def test_active_style_is_readable_by_the_control_service(harness):
    harness.tick()
    if os.name == "posix":
        assert (harness.state_dir / "active-style").stat().st_mode & 0o044 == 0o044
    assert not list(harness.state_dir.glob(".*tmp"))


def test_real_child_runs_in_style_folder_and_switches(tmp_path):
    """Real processes: the stub records its working directory and whether it
    can see the style's graphics, as eyes.py needs to."""
    for name in ("default", "dragon"):
        make_style(tmp_path, name)
    log = tmp_path / "started.log"
    stub = tmp_path / "stub_eyes.py"
    stub.write_text(
        "import os, sys, time\n"
        f"open({str(log)!r}, 'a').write("
        "os.path.basename(os.getcwd()) + ' ' + str(os.path.isfile('graphics/eye.svg'))"
        " + ' ' + sys.argv[2] + chr(10))\n"
        "time.sleep(60)\n")
    supervisor = Supervisor(tmp_path, stub, 240)

    def wait_for_lines(count):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if log.exists() and len(log.read_text().splitlines()) >= count:
                return log.read_text().splitlines()
            time.sleep(0.05)
        pytest.fail("stub did not start")

    try:
        supervisor.tick()
        assert wait_for_lines(1) == ["default True 240"]
        first = supervisor.child
        (tmp_path / "current-style").write_text("dragon\n")
        supervisor.tick()
        assert wait_for_lines(2)[1] == "dragon True 240"
        assert first.poll() is not None
    finally:
        supervisor.stop_child()
    assert supervisor.child is None
