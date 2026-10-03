"""Real published-assembly, mock HTTP, PRINT and GUI acceptance. No devices."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from automation.target_verification import TargetVerificationSpec, _event_line, parse_target_verification
from pyside_app.run_input_state import validate_input_response, RunInputStateModel


def verify_samples(path):
    samples = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    model = RunInputStateModel()
    model.begin("protocol-run", "protocol-session", "protocol-stage")
    for payload in samples:
        model.apply_payload(payload)
    assert any(item["snapshot"]["buttons"] == ["A", "ZL"] for item in samples)
    assert any(item["snapshot"]["left_stick"] == [0, 255] for item in samples)
    assert samples[-1]["snapshot"]["buttons"] == []
    return samples


def verify_runner(runner, output, samples):
    output.mkdir(parents=True, exist_ok=True)
    spec = TargetVerificationSpec("protocol-run", "protocol-attempt", "75D1", 1901, 7, "Static 1", "89ABCDEF")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for shiny in ("0", "1"):
        script = output / f"print-{shiny}.ecs"
        script.write_text('$循环计数 = 1\n' + _event_line(spec, "TARGET", shiny=shiny) + '\nWAIT 2000\n', encoding="utf-8")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        command = [str(runner), "run", str(script), "--port", "mock", "--preview-port", str(port),
                   "--run-id", "protocol-run", "--input-session-id", "protocol-session", "--input-stage-id", "protocol-stage"]
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    with opener.open(f"http://127.0.0.1:{port}/capabilities", timeout=.5) as reply:
                        assert json.load(reply)["input_state_protocol"] == 1
                    with opener.open(f"http://127.0.0.1:{port}/input-state?after_seq=0", timeout=.5) as reply:
                        payload = json.load(reply)
                    break
                except OSError:
                    if time.monotonic() >= deadline or proc.poll() is not None:
                        raise RuntimeError("mock HTTP service did not become ready")
                    time.sleep(.05)
            validate_input_response(payload, run_id="protocol-run", session_id="protocol-session", stage_id="protocol-stage", last_seq=-1)
            (output / f"http-{shiny}.json").write_text(json.dumps(payload), encoding="utf-8")
            raw = proc.communicate(timeout=20)[0].decode("utf-8", errors="replace")
            (output / f"print-{shiny}.log").write_text(raw, encoding="utf-8")
            assert proc.returncode == 0, raw
            proof = parse_target_verification(raw, run_id=spec.run_id, attempt_id=spec.attempt_id)
            assert proof and proof["shiny"] == (shiny == "1"), raw
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.communicate(timeout=5)
    from PySide6.QtWidgets import QApplication
    from pyside_app.migration import CompleteWindow
    from pyside_app.manual import ControllerWindow
    from pyside_app.services import AppPaths
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="frlg-protocol-gui-") as temp:
        w = CompleteWindow(paths=AppPaths(user=Path(temp), output=Path(temp) / "runtime"), auto_detect=False)
        controller = ControllerWindow(w)
        w.accessories.controller = controller
        w.running = True
        model = w.accessories.input_client.model
        model.begin("protocol-run", "protocol-session", "protocol-stage")
        for payload in samples:
            model.apply_payload(payload)
            view = model.view()
            w.accessories._input_state_changed(view)
            assert controller.observed_snapshot == view.snapshot
        model.end("运行已结束", phase="ended")
        w.accessories._input_state_changed(model.view())
        w.running = False
        controller.close()
        w.close()
        app.processEvents()
    (output / "verification.json").write_text(json.dumps({"samples":len(samples), "http":True, "print_roundtrip":True, "gui":True}), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", required=True, type=Path)
    parser.add_argument("--runner", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    samples = verify_samples(args.samples)
    if args.runner:
        verify_runner(args.runner.resolve(), args.output.resolve(), samples)
    print(f"Production input protocol samples accepted: {len(samples)}")
