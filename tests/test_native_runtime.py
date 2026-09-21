"""Native integration contracts: validate and run without an external CLI."""
import base64
import hashlib
import json
import re
import signal
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from automation.easycon118 import build_run_command, prepare_compat_runner
from automation.native_runtime import probe_native_devices, validate_native_runtime
from automation.script_test import prepare_script_test_runtime, SCRIPT_TEST_BACKEND_NATIVE, SCRIPT_TEST_BACKEND_ORIGINAL
from easycon.native import EasyConScriptEngine
from easycon.native.parser import parse_text
from easycon.native.image_labels import ImageLabel, SearchMethod
from easycon.native.tesseract import TesseractRuntime, bundled_runtime_root, native_library_directory
from run_native_easycon import main, run_native


_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('script', sorted((_ROOT / 'assets').rglob('*.ecs')),
                         ids=lambda script: script.name)
def test_all_bundled_ecs_extensions_parse_natively(script):
    parse_text(script.read_text(encoding='utf-8-sig'), source=str(script))


def test_actual_common_region_arithmetic_harness_runs_natively():
    source = (_ROOT / 'assets/easycon118_extensions/seed_common_regions.ecs').read_text(encoding='utf-8-sig')
    harness = (_ROOT / 'tools/EasyCon164aCommonRegionCheck/Program.cs').read_text(encoding='utf-8-sig')
    cases = re.findall(r'source \+= """\n(.*?)\n""";', harness, re.S)
    assert len(cases) == 2
    program = EasyConScriptEngine().compile(source + '\n' + '\n'.join(cases))
    assert not program.has_gamepad_actions and not program.external_labels
    output = []
    cancelled = threading.Event()
    timeout = threading.Timer(120, cancelled.set)
    timeout.start()
    try:
        program.run(output=output.append, cancel_event=cancelled)
    finally:
        timeout.cancel()
    text = ''.join(output)
    assert 'ASSERT_FAIL' not in text
    assert 'NATIVE_COMMON_REGION_PASS' in text
    assert 'NATIVE_STARTER_COMMON_PASS' in text


def write_label(directory, *, method=5, alpha=False):
    image = np.random.default_rng(17).integers(1, 256, (3, 4, 4 if alpha else 3), dtype=np.uint8)
    if alpha:
        image[:, :, 3] = 255
    ok, png = cv2.imencode('.png', image)
    assert ok
    labels = directory / 'ImgLabel'
    labels.mkdir(exist_ok=True)
    path = labels / '目标.IL'
    path.write_text(json.dumps(dict(searchMethod=method, ImgBase64=base64.b64encode(png).decode(),
        RangeX=0, RangeY=0, RangeWidth=16, RangeHeight=12,
        TargetX=6, TargetY=5, TargetWidth=4, TargetHeight=3)), encoding='utf-8')
    return path, image


def test_native_command_ignores_old_executable_and_preserves_capture_options(tmp_path):
    command = build_run_command(tmp_path/'missing.exe', tmp_path/'main.ecs', port='COM3', video_device=2,
                                preview_port=43210, fingerprint_warning_only=True)
    assert str(tmp_path/'missing.exe') not in command
    assert Path(command[2]).name == 'run_native_easycon.py'
    assert command[command.index('--capture-api')+1] == '700'
    assert command[command.index('--preview-port')+1] == '43210'
    assert '--fingerprint-warnings' in command
    assert prepare_compat_runner(tmp_path/'missing.exe').name == 'run_native_easycon.py'


def test_standalone_bridge_compiles_without_lib_or_cli(tmp_path):
    script = tmp_path/'main.ecs'
    text = 'A 0\nPRINT TIDFLOW|BRIDGE|DONE=1\nRETURN 0\n'
    script.write_text(text, encoding='utf-8')
    with patch('subprocess.run', side_effect=AssertionError('must compile natively')):
        check = validate_native_runtime(script)
        prepared = prepare_script_test_runtime(tmp_path/'absent.exe', script, SCRIPT_TEST_BACKEND_NATIVE)
    assert check.ok, check.errors
    assert prepared.check.ok
    assert script.read_text(encoding='utf-8') == text
    assert not prepare_script_test_runtime(tmp_path/'absent.exe', script, SCRIPT_TEST_BACKEND_ORIGINAL).check.ok


def test_preflight_rejects_syntax_and_missing_or_invalid_labels_even_in_advanced_mode(tmp_path):
    script = tmp_path/'main.ecs'
    script.write_text('IF true\nA 10', encoding='utf-8')
    assert not validate_native_runtime(script, fingerprint_warning_only=True).ok
    script.write_text('$score = @目标', encoding='utf-8')
    check = validate_native_runtime(script)
    assert not check.ok and '找不到搜图标签' in '\n'.join(check.errors)
    path, _ = write_label(tmp_path)
    assert validate_native_runtime(script).ok
    path.write_text('{}', encoding='utf-8')
    assert not validate_native_runtime(script, fingerprint_warning_only=True).ok


def test_ocr_models_come_from_script_and_hash_policy_does_not_allow_missing_model(tmp_path):
    script = tmp_path/'main.ecs'
    script.write_text('$text = OCR(0, 0, 10, 10, "FRLG_EN_ALL")', encoding='utf-8')
    tessdata = tmp_path/'Tessdata'
    tessdata.mkdir()
    model = tessdata/'FRLG_EN_ALL.traineddata'
    model.write_bytes(b'custom-model')
    with patch('easycon.native.tesseract.TesseractRuntime') as runtime, \
         patch('easycon.native.tesseract.resolve_tessdata_root', return_value=tmp_path):
        assert not validate_native_runtime(script).ok
        advanced = validate_native_runtime(script, fingerprint_warning_only=True)
        assert advanced.ok and advanced.warnings
        runtime.assert_called_with(tmp_path, language='FRLG_EN_ALL')
        runtime.return_value.validate_model.assert_called()
        model.unlink()
        check = validate_native_runtime(script, fingerprint_warning_only=True)
        assert not check.ok and 'Tessdata 缺少' in '\n'.join(check.errors)


@pytest.mark.parametrize('advanced', [False, True])
def test_corrupt_ocr_model_blocks_hardware_start_even_in_advanced_mode(tmp_path, advanced):
    script = tmp_path / 'main.ecs'
    script.write_text('A 1\n$text = OCR(0, 0, 10, 10, "chi_sim")', encoding='utf-8')
    models = tmp_path / 'Tessdata'
    models.mkdir()
    (models / 'chi_sim.traineddata').write_bytes(b'not-a-tesseract-model')
    with patch('run_native_easycon.CaptureBrokerProcess') as broker, \
         patch('run_native_easycon.NativeEasyConBackend') as backend:
        code = run_native(script, port='COM3', video=0, fingerprint_warnings=advanced)
    assert code == 2
    broker.return_value.start.assert_not_called()
    backend.return_value.connect.assert_not_called()
    assert 'Tesseract 初始化失败' in (tmp_path / 'native-easycon.log').read_text(encoding='utf-8')


def test_enumeration_returns_friendly_names_without_opening_capture():
    with patch('automation.native_runtime.list_ports', return_value=['COM3']), \
         patch('cv2_enumerate_cameras.enumerate_cameras', return_value=[SimpleNamespace(index=2, name='USB Capture')]) as enumerate_, \
         patch('cv2.VideoCapture', side_effect=AssertionError('enumeration must not open devices')):
        ports, videos, _ = probe_native_devices(include_video_names=True)
    assert ports == {'COM3'} and videos == {2: 'USB Capture'}
    enumerate_.assert_called_once_with(700)


def test_masked_template_match_is_finite_on_black_background(tmp_path):
    path, template = write_label(tmp_path, method=14, alpha=True)
    frame = np.zeros((12,16,3), dtype=np.uint8)
    frame[5:8, 6:10] = template[:, :, :3]
    result = ImageLabel.load(path).search(frame)
    assert result.script_value == 100 and result.match_rect == (6,5,4,3)
    assert np.isfinite(ImageLabel.load(path).search(np.zeros_like(frame)).score)


def test_while_condition_labels_are_bound():
    program = EasyConScriptEngine().compile('WHILE @目标 > 90\nBREAK\nEND')
    assert program.external_labels == frozenset({'目标'})


def test_bundled_ocr_dll_and_model_load_from_assets():
    root = bundled_runtime_root('chi_sim')
    assert root.name == 'easycon_native' and root.parent.name == 'assets'
    assert native_library_directory(root).name == 'x64'
    runtime = TesseractRuntime(root, language='chi_sim')
    text, confidence = runtime.read(np.full((32,120,3), 255, dtype=np.uint8))
    assert text == '' and 0 <= confidence <= 1


@pytest.fixture
def native_worker(tmp_path):
    script = tmp_path/'main.ecs'
    script.write_text('A 0\nPRINT TIDFLOW|BRIDGE|DONE=1\nRETURN 0', encoding='utf-8')
    with patch('run_native_easycon.CaptureBrokerProcess') as broker, patch('run_native_easycon.write_console'):
        broker.return_value.start.return_value = True
        yield script, broker.return_value


def test_worker_logs_exact_machine_records_and_cleans_up(native_worker):
    script, broker = native_worker
    assert run_native(script, port='mock', video=0) == 0
    log = (script.parent/'native-easycon.log').read_text(encoding='utf-8')
    assert '\nTIDFLOW|BRIDGE|DONE=1\n' in log
    broker.stop.assert_called_once()


def test_worker_parser_accepts_native_gui_arguments(native_worker):
    script, broker = native_worker
    assert main(['--project', str(script), '--port', 'mock', '--video', '0',
                 '--fingerprint-warnings', '--expected-marker', 'TIDFLOW|BRIDGE|DONE=1']) == 0


def test_worker_rejects_missing_completion_marker(native_worker):
    script, broker = native_worker
    assert run_native(script, port='mock', video=0, expected_marker=['孵蛋流程完成']) == 2
    broker.stop.assert_called_once()


def test_worker_stop_before_start_does_not_open_devices(native_worker):
    script, broker = native_worker
    stop = script.parent/'stop'
    stop.touch()
    assert run_native(script, port='mock', video=0, stop_file=stop) == 130
    broker.start.assert_not_called()


def test_worker_cancel_during_capture_start_cleans_up(native_worker):
    script, broker = native_worker
    def start(*, cancel_event):
        cancel_event.set()
        return False
    broker.start.side_effect = start
    assert run_native(script, port='mock', video=0) == 130
    broker.stop.assert_called_once()


def test_worker_connection_failure_stops_preview_and_broker(native_worker):
    script, broker = native_worker
    with patch('run_native_easycon.NativeEasyConBackend') as backend, \
         patch('run_native_easycon.NativePreviewServer') as preview:
        backend.return_value.connect.side_effect = RuntimeError('serial refused')
        assert run_native(script, port='mock', video=0, preview_port=43211) == 1
        backend.return_value.disconnect.assert_called_once()
        preview.return_value.close.assert_called_once()
    broker.stop.assert_called_once()


def test_worker_stop_file_interrupts_long_wait_and_releases_controller(native_worker):
    script, broker = native_worker
    script.write_text('A DOWN\nWAIT 60000', encoding='utf-8')
    stop = script.parent/'stop'
    from easycon.native_backend import NativeEasyConBackend
    backend = NativeEasyConBackend()
    timer = threading.Timer(.2, lambda: stop.touch())
    try:
        with patch('run_native_easycon.NativeEasyConBackend', return_value=backend):
            timer.start()
            assert run_native(script, port='mock', video=0, stop_file=stop) == 130
        assert backend.connected_port is None
        assert backend.get_report().button == 0
    finally:
        timer.cancel()
        timer.join()
    broker.stop.assert_called_once()


def test_generated_lab_route_compiles_with_native_engine():
    from automation.tid_starter_flow import render_lab_bridge_ecs
    for starter in ('Bulbasaur', 'Charmander', 'Squirtle'):
        program = EasyConScriptEngine().compile(render_lab_bridge_ecs(starter))
        assert program.has_gamepad_actions


def test_print_continuation_keeps_machine_record_on_one_line(native_worker):
    script, _ = native_worker
    script.write_text('PRINT TIDFLOW|ID|TID=\\\nPRINT 12345\nRETURN 0\nPRINT unreachable', encoding='utf-8')
    assert run_native(script, port='mock', video=0) == 0
    log = (script.parent/'native-easycon.log').read_text(encoding='utf-8')
    assert '\nTIDFLOW|ID|TID=12345\n' in log
    assert 'unreachable' not in log


def test_ctrl_c_cancels_and_restores_signal_handler(native_worker):
    script, broker = native_worker
    script.write_text('A DOWN\nWAIT 60000', encoding='utf-8')
    from easycon.native_backend import NativeEasyConBackend
    class InterruptWaiter:
        def wait(self, milliseconds, cancel_event):
            signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
    backend = NativeEasyConBackend(waiter=InterruptWaiter())
    previous = signal.getsignal(signal.SIGINT)
    with patch('run_native_easycon.NativeEasyConBackend', return_value=backend):
        assert run_native(script, port='mock', video=0) == 130
    assert signal.getsignal(signal.SIGINT) == previous
    assert backend.connected_port is None and backend.get_report().button == 0
    broker.stop.assert_called_once()


def test_shared_broker_feeds_native_labels_and_loopback_preview(tmp_path):
    from http.client import HTTPConnection
    from capture_broker import CaptureBroker, CaptureBrokerClient, FakeCapture
    from easycon.native_backend import NativeEasyConBackend
    from easycon.native.preview import NativePreviewServer
    path, template = write_label(tmp_path)
    frame = np.zeros((12,16,3), dtype=np.uint8)
    frame[5:8,6:10] = template
    capture = FakeCapture([frame], repeat=True, read_delay=.01)
    manifest = tmp_path/'broker.json'
    broker = CaptureBroker(0, manifest_path=manifest, capture_factory=lambda *_: capture, width=16, height=12)
    client = lambda: CaptureBrokerClient.connect(manifest, require_running=True)
    backend = NativeEasyConBackend(frame_client_factory=client)
    preview = None
    try:
        assert broker.start(wait=True)
        backend.connect('mock')
        result = backend.run_script_text('PRINT @目标', script_dir=tmp_path)
        assert result.exit_code == 0 and result.stdout == '100\n'
        preview = NativePreviewServer(0, client)
        preview.start()
        http = HTTPConnection('127.0.0.1', preview.server.server_port, timeout=2)
        try:
            http.request('GET', '/mjpeg')
            response = http.getresponse()
            assert response.status == 200
            assert response.read(7) == b'--frame'
        finally:
            http.close()
        assert capture.open_calls == 1
    finally:
        backend.close()
        if preview:
            preview.close()
        broker.stop()
    assert capture.released


def test_capture_normalizes_matching_aspect_ratio_and_rejects_distortion():
    from capture_broker import OpenCVCapture, CaptureOpenError
    from unittest.mock import Mock
    capture = OpenCVCapture()
    source = capture._capture = Mock()
    source.read.return_value = (True, np.zeros((720,1280,3), dtype=np.uint8))
    ok, frame = capture.read()
    assert ok and frame.shape == (1080,1920,3)
    source.read.return_value = (True, np.zeros((480,640,3), dtype=np.uint8))
    with pytest.raises(CaptureOpenError, match='比例不一致'):
        capture.read()
