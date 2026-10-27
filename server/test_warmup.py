import asyncio
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from server import main, warmup


class WarmCallPathTest(unittest.TestCase):
    def test_failed_step_is_reported_and_later_steps_still_run(self):
        ran = []

        def boom():
            ran.append("boom")
            raise RuntimeError("model file missing")

        results = warmup.warm_call_path([("a", lambda: ran.append("a")), ("boom", boom), ("c", lambda: ran.append("c"))])

        self.assertEqual(ran, ["a", "boom", "c"])
        self.assertIsInstance(results["a"], float)
        self.assertIsInstance(results["c"], float)
        self.assertEqual(results["boom"], "error: RuntimeError: model file missing")

    def test_real_steps_without_network_load_models(self):
        # Vertex 인증 갱신만 네트워크를 쓰므로 뺀다. 나머지는 실제 모듈 이름·모델 생성이 맞는지 확인한다.
        steps = [s for s in warmup.CALL_WARMUP_STEPS if s[0] != "vertex_auth"]
        with mock.patch.dict("os.environ", {"LIVE_BREATHS": "on"}):
            results = warmup.warm_call_path(steps)

        self.assertEqual(list(results), ["imports", "webrtc", "live_service", "noise_filter", "smart_turn", "silero", "breaths"])
        failed = {k: v for k, v in results.items() if not isinstance(v, float)}
        self.assertEqual(failed, {})

    def test_steps_cover_the_first_call_loads(self):
        names = [name for name, _ in warmup.CALL_WARMUP_STEPS]
        for name in ("imports", "webrtc", "vertex_auth", "smart_turn", "silero", "breaths"):
            self.assertIn(name, names)


class WarmOnStartupTest(unittest.TestCase):
    def test_off_switch_skips_warmup(self):
        warm = mock.Mock()
        asyncio.run(warmup.warm_on_startup(env={"CALL_WARMUP": "off"}, warm=warm))
        warm.assert_not_called()

    def test_on_by_default(self):
        warm = mock.Mock()
        asyncio.run(warmup.warm_on_startup(env={}, warm=warm))
        warm.assert_called_once_with()

    def test_exception_does_not_stop_startup(self):
        warm = mock.Mock(side_effect=RuntimeError("onnxruntime broken"))
        with self.assertLogs("server.warmup", level="WARNING") as logs:
            asyncio.run(warmup.warm_on_startup(env={}, warm=warm))
        self.assertIn("onnxruntime broken", "\n".join(logs.output))

    def test_slow_warmup_gives_up_after_timeout(self):
        gate = threading.Event()
        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        self.addCleanup(gate.set)
        with self.assertLogs("server.warmup", level="WARNING") as logs:
            loop.run_until_complete(warmup.warm_on_startup(env={}, timeout=0.05, warm=lambda: gate.wait(5)))
        self.assertIn("did not finish", "\n".join(logs.output))


class LifespanWiringTest(unittest.TestCase):
    def test_server_start_runs_warmup_once_before_serving(self):
        with mock.patch.object(warmup, "warm_call_path") as warm, mock.patch.dict("os.environ", {"CALL_WARMUP": "on"}):
            with TestClient(main.app) as client:
                warm.assert_called_once_with()
                self.assertEqual(client.get("/api/status").status_code, 200)

    def test_server_still_starts_when_warmup_fails(self):
        with mock.patch.object(warmup, "warm_call_path", side_effect=RuntimeError("boom")), \
                mock.patch.dict("os.environ", {"CALL_WARMUP": "on"}):
            with TestClient(main.app) as client:
                self.assertEqual(client.get("/api/status").status_code, 200)


if __name__ == "__main__":
    unittest.main()
