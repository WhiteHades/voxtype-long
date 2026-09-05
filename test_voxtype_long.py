import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


SCRIPT = Path(__file__).with_name("voxtype-long")


FAKE_NATIVE = r'''#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(os.environ["XDG_RUNTIME_DIR"])
state = root / "voxtype" / "state"
log = root / "calls.log"
state.parent.mkdir(parents=True, exist_ok=True)
args = sys.argv[1:]
if args and args[0] == "_delayed":
    time.sleep(float(args[1]))
    if not (root / "canceled").exists():
        state.write_text("recording")
    raise SystemExit(0)
if args[:2] == ["config", "set"]:
    log.open("a").write("config " + " ".join(args[2:]) + "\n")
    raise SystemExit(0)
action = args[1] if len(args) > 1 and args[0] == "record" else "bad"
current = state.read_text().strip() if state.exists() else "idle"
if action == "start":
    log.open("a").write("start:" + current + "\n")
    async_delay = os.environ.get("FAKE_ASYNC_DELAY")
    if async_delay:
        subprocess.Popen(
            [sys.executable, __file__, "_delayed", async_delay],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    else:
        delay = float(os.environ.get("FAKE_START_DELAY", "0"))
        if delay:
            time.sleep(delay)
        if current != "transcribing":
            state.write_text("recording")
elif action == "stop":
    log.open("a").write("stop:" + current + "\n")
    if current in ("recording", "streaming"):
        state.write_text("transcribing")
elif action == "cancel":
    log.open("a").write("cancel:" + current + "\n")
    (root / "canceled").write_text("")
    state.write_text("idle")
else:
    log.open("a").write("bad\n")
    raise SystemExit(2)
'''


class VoxtypeLongTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "voxtype").mkdir()
        (self.root / "voxtype" / "state").write_text("idle")
        (self.root / "voxtype" / "voxtype.lock").write_text(str(os.getpid()))
        self.fake = self.root / "fake-voxtype"
        self.fake.write_text(FAKE_NATIVE)
        self.fake.chmod(0o755)
        self.env = os.environ.copy()
        self.env.update(
            XDG_RUNTIME_DIR=str(self.root),
            VOXTYPE_LONG_NATIVE=str(self.fake),
            VOXTYPE_LONG_NOTIFY="0",
            PYTHONUNBUFFERED="1",
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_helper(self, action, **env):
        current = self.env.copy()
        current.update(env)
        return subprocess.run(
            [sys.executable, str(SCRIPT), action],
            env=current,
            capture_output=True,
            text=True,
            check=False,
        )

    def start_helper(self, action, **env):
        current = self.env.copy()
        current.update(env)
        return subprocess.Popen(
            [sys.executable, str(SCRIPT), action],
            env=current,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def wait_for(self, predicate, timeout=3):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return
            time.sleep(0.02)
        self.fail("condition did not become true")

    def calls(self):
        path = self.root / "calls.log"
        return path.read_text().splitlines() if path.exists() else []

    def request(self):
        path = self.root / "voxtype-long" / "request.json"
        return json.loads(path.read_text()) if path.exists() else None

    def finish(self, process):
        stdout, stderr = process.communicate(timeout=3)
        self.assertEqual(process.returncode, 0, stderr)
        return stdout, stderr

    def test_busy_start_is_retried_after_transcription(self):
        (self.root / "voxtype" / "state").write_text("transcribing")
        start = self.start_helper("start")
        self.wait_for(lambda: self.request() is not None)
        time.sleep(0.15)
        self.assertFalse(any(call.startswith("start:") for call in self.calls()))

        (self.root / "voxtype" / "state").write_text("idle")
        self.wait_for(lambda: (self.root / "voxtype" / "state").read_text() == "recording")
        self.finish(start)
        self.assertEqual(sum(call.startswith("start:") for call in self.calls()), 1)

    def test_release_cancels_queued_start(self):
        (self.root / "voxtype" / "state").write_text("transcribing")
        start = self.start_helper("start")
        self.wait_for(lambda: self.request() is not None)
        self.finish(self.start_helper("stop"))
        self.finish(start)
        (self.root / "voxtype" / "state").write_text("idle")
        self.assertFalse(any(call.startswith("start:") for call in self.calls()))
        document = self.request()
        self.assertTrue(document is None or document["request"] is None)

    def test_second_toggle_cancels_one_pending_start(self):
        (self.root / "voxtype" / "state").write_text("transcribing")
        first = self.start_helper("toggle")
        self.wait_for(lambda: self.request() is not None)
        self.finish(self.start_helper("toggle"))
        self.finish(first)
        (self.root / "voxtype" / "state").write_text("idle")
        self.assertFalse(any(call.startswith("start:") for call in self.calls()))

    def test_toggle_active_recording_stops(self):
        (self.root / "voxtype" / "state").write_text("recording")
        result = self.run_helper("toggle")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stop:recording", self.calls())

    def test_cancel_discards_active_recording(self):
        (self.root / "voxtype" / "state").write_text("recording")
        result = self.run_helper("cancel")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cancel:recording", self.calls())
        self.assertEqual((self.root / "voxtype" / "state").read_text(), "idle")

    def test_release_cancels_async_start_after_ack_timeout(self):
        start = self.start_helper(
            "start", FAKE_ASYNC_DELAY="0.6", VOXTYPE_LONG_ACK_TIMEOUT="0.1"
        )
        stdout, stderr = start.communicate(timeout=2)
        self.assertNotEqual(start.returncode, 0, stdout + stderr)
        self.assertEqual(self.request()["request"]["phase"], "starting")

        stop = self.run_helper("stop")
        self.assertEqual(stop.returncode, 0, stop.stderr)
        time.sleep(0.8)
        self.assertEqual((self.root / "voxtype" / "state").read_text(), "idle")
        self.assertIn("start:idle", self.calls())
        self.assertIn("cancel:idle", self.calls())
        self.assertFalse(any(call.startswith("stop:") for call in self.calls()))
        self.assertIsNone(self.request()["request"])

    def test_release_cleans_async_start_if_daemon_exits(self):
        start = self.start_helper(
            "start", FAKE_ASYNC_DELAY="0.6", VOXTYPE_LONG_ACK_TIMEOUT="0.1"
        )
        stdout, stderr = start.communicate(timeout=2)
        self.assertNotEqual(start.returncode, 0, stdout + stderr)
        self.assertEqual(self.request()["request"]["phase"], "starting")

        (self.root / "voxtype" / "voxtype.lock").write_text("999999999")
        stop = self.run_helper("stop")
        self.assertNotEqual(stop.returncode, 0)
        self.assertIsNone(self.request()["request"])
        time.sleep(0.8)

    def test_stop_during_start_ack_is_not_lost(self):
        start = self.start_helper("start", FAKE_START_DELAY="0.25")
        self.wait_for(lambda: self.request() is not None)
        stop = self.start_helper("stop")
        self.finish(start)
        self.finish(stop)
        self.assertIn("stop:recording", self.calls())
        self.assertEqual((self.root / "voxtype" / "state").read_text(), "transcribing")
        self.assertIsNone(self.request()["request"])

    def test_toggle_during_start_ack_stops(self):
        start = self.start_helper("start", FAKE_START_DELAY="0.25")
        self.wait_for(lambda: self.request() is not None)
        toggle = self.start_helper("toggle")
        self.finish(start)
        self.finish(toggle)
        self.assertIn("stop:recording", self.calls())
        self.assertEqual((self.root / "voxtype" / "state").read_text(), "transcribing")

    def test_duplicate_start_has_one_native_start(self):
        (self.root / "voxtype" / "state").write_text("transcribing")
        first = self.start_helper("start")
        self.wait_for(lambda: self.request() is not None)
        self.finish(self.start_helper("start"))
        (self.root / "voxtype" / "state").write_text("idle")
        self.wait_for(lambda: (self.root / "voxtype" / "state").read_text() == "recording")
        self.finish(first)
        self.assertEqual(sum(call.startswith("start:") for call in self.calls()), 1)

    def test_queue_timeout_clears_request(self):
        (self.root / "voxtype" / "state").write_text("transcribing")
        start = self.start_helper("start", VOXTYPE_LONG_QUEUE_TIMEOUT="0.2")
        stdout, stderr = start.communicate(timeout=2)
        self.assertNotEqual(start.returncode, 0, stdout + stderr)
        self.assertIsNone(self.request()["request"])
        self.assertFalse(any(call.startswith("start:") for call in self.calls()))

    def test_stale_daemon_is_rejected(self):
        (self.root / "voxtype" / "voxtype.lock").write_text("999999999")
        result = self.run_helper("start")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("daemon is not running", result.stderr)
        self.assertFalse((self.root / "calls.log").exists())
        document = self.request()
        self.assertTrue(document is None or document["request"] is None)

    def test_configure_uses_official_key_without_model_change(self):
        result = self.run_helper("configure")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("audio.max_duration_secs 3600", self.calls()[0])
        self.assertIn("restart voxtype", result.stdout)


if __name__ == "__main__":
    unittest.main()
