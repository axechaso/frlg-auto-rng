import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import automation.easycon118 as backend


class EasyCon164aBackendTests(unittest.TestCase):
    def test_ocr_unavailable_sentinel_skips_name_correction(self):
        original = """\
FUNC OCR识别抓捕对象名称(): STRING
    $name = OCR(310, 141, 360, 53, "frlg_battle")
    $fixedName = OCR名称V2后处理($name)
    RETURN $fixedName
ENDFUNC

FUNC OCR最小3($A: INT, $B: INT, $C: INT): INT
    RETURN $A
ENDFUNC
"""
        configured = backend._apply_ocr_runtime_fallback_text(original)
        configured_again = backend._apply_ocr_runtime_fallback_text(configured)

        self.assertEqual(configured_again, configured)
        self.assertIn(backend.OCR_RUNTIME_FALLBACK_MARKER, configured)
        self.assertIn('IF $name == "OCR NOT SUPPORT"', configured)
        self.assertIn('IF $name == "OCR ARGS ERR!"', configured)
        self.assertLess(
            configured.index('IF $name == "OCR NOT SUPPORT"'),
            configured.index("$fixedName = OCR名称V2后处理($name)"),
        )

    def test_compat_patch_uses_a_continuous_latest_frame_capture(self):
        root = Path(__file__).resolve().parents[1]
        patch_text = (
            root / "tools" / "patches" / "easycon164a-cli-gui-rounding.patch"
        ).read_text(encoding="utf-8")
        additions = "\n".join(
            line[1:]
            for line in patch_text.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )

        self.assertEqual(
            backend.EXPECTED_COMPAT_PATCH_ID,
            "cli-latest-frame-ceiling-ocr-onedir-v4",
        )
        self.assertIn("captureTask = Task.Run", additions)
        self.assertIn("latestFrame = frame.Clone()", additions)
        self.assertIn("using var snapshot = CloneLatestFrame()", additions)
        self.assertIn("return latestFrame.Clone()", additions)
        self.assertIn("il.Search(snapshot, out var md)", additions)
        self.assertIn("return (int)Math.Ceiling(md)", additions)
        self.assertIn(
            "OcrDelegateFactory.Create(CloneLatestFrame)", additions
        )
        self.assertIn(
            "runner.Run(outdap, pad, ocr, externalGetters, cancellationToken)",
            additions,
        )
        self.assertNotIn(
            "runner.Run(outdap, pad, null, externalGetters, cancellationToken)",
            additions,
        )
        self.assertIn("采集卡实际画面", additions)

        build_script = (
            root / "tools" / "build_easycon164a_compat_runner.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("-p:PublishSingleFile=false", build_script)
        self.assertNotIn("-p:PublishSingleFile=true", build_script)
        self.assertIn("self-contained onedir", build_script)

    def test_default_backend_is_the_pinned_164a_package(self):
        self.assertEqual(
            backend.EXPECTED_EZCON_VERSION,
            "1.6.4-a+9c86137c7e63bff842175470895727a5fa9bab52",
        )
        self.assertEqual(backend.DEFAULT_EZCON_PATH.name, "ezcon.exe")
        self.assertIn("v1.6.4alpha", str(backend.DEFAULT_EZCON_PATH))
        self.assertEqual(
            backend.DEFAULT_COMPAT_RUNNER_PATH.name,
            "EasyCon2.CLI-ocr-v4.exe",
        )

    def test_runtime_preflight_uses_format_instead_of_170_ir(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            publish = root / "publish"
            tessdata = publish / "Tessdata"
            project = root / "project"
            (project / "lib").mkdir(parents=True)
            (project / "ImgLabel").mkdir()
            tessdata.mkdir(parents=True)

            ezcon = publish / "ezcon.exe"
            ezcon.write_bytes(b"pinned-ezcon")
            main = project / "main.ecs"
            main.write_text("PRINT test\n", encoding="utf-8")
            models = {
                "frlg_battle.traineddata": b"battle-model",
                "FRLG_EN_ALL.traineddata": b"english-model",
            }
            for name, data in models.items():
                (tessdata / name).write_bytes(data)
            expected_models = {
                name: hashlib.sha256(data).hexdigest()
                for name, data in models.items()
            }
            label_manifest = {
                "count": backend.EXPECTED_LABEL_COUNT,
                "methods": backend.EXPECTED_LABEL_METHODS,
                "sha256": backend.EXPECTED_LABEL_SHA256,
            }
            version_result = subprocess.CompletedProcess(
                [], 0, stdout=backend.EXPECTED_EZCON_VERSION + "\n", stderr=""
            )
            format_result = subprocess.CompletedProcess(
                [], 0, stdout="PRINT test\n", stderr=""
            )

            with (
                mock.patch.object(
                    backend,
                    "EXPECTED_EZCON_SHA256",
                    hashlib.sha256(b"pinned-ezcon").hexdigest(),
                ),
                mock.patch.object(backend, "EXPECTED_TESSDATA_SHA256", expected_models),
                mock.patch.object(backend, "inspect_label_corpus", return_value=label_manifest),
                mock.patch.object(
                    backend.subprocess,
                    "run",
                    side_effect=(version_result, format_result),
                ) as run,
            ):
                check = backend.validate_runtime(ezcon, main)

            self.assertTrue(check.ok, check.errors)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[0], [str(ezcon.resolve()), "--version"])
            self.assertEqual(
                commands[1],
                [str(ezcon.resolve()), "format", str(main.resolve())],
            )
            self.assertFalse(any("ir" in command for command in commands))

    def test_run_command_keeps_the_configured_dshow_backend(self):
        command = backend.build_run_command(
            "ezcon.exe",
            "main.ecs",
            port="COM22",
            video_device=0,
        )

        self.assertEqual(command[command.index("--videotype") + 1], "DSHOW")

    def test_compat_runner_is_pinned_and_receives_audited_ocr_models(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            publish = root / "publish"
            tessdata = publish / "Tessdata"
            runner_dir = root / "runner"
            tessdata.mkdir(parents=True)
            runner_dir.mkdir()
            ezcon = publish / "ezcon.exe"
            runner = runner_dir / "EasyCon2.CLI.exe"
            ezcon.write_bytes(b"official-164a")
            runner.write_bytes(b"compat-runner")
            models = {
                "frlg_battle.traineddata": b"battle-model",
                "FRLG_EN_ALL.traineddata": b"english-model",
            }
            for name, data in models.items():
                (tessdata / name).write_bytes(data)
            native_files = {
                "x64/leptonica-1.82.0.dll": b"leptonica-native",
                "x64/tesseract50.dll": b"tesseract-native",
            }
            for relative_name, data in native_files.items():
                path = runner_dir / Path(relative_name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            manifest = {
                "source_commit": backend.EXPECTED_COMPAT_SOURCE_COMMIT,
                "patch_id": backend.EXPECTED_COMPAT_PATCH_ID,
                "sha256": hashlib.sha256(b"compat-runner").hexdigest(),
            }
            runner.with_name("build-manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            version_result = subprocess.CompletedProcess(
                [], 0, stdout=backend.EXPECTED_EZCON_VERSION + "\n", stderr=""
            )

            with (
                mock.patch.object(
                    backend,
                    "EXPECTED_EZCON_SHA256",
                    hashlib.sha256(b"official-164a").hexdigest(),
                ),
                mock.patch.object(
                    backend,
                    "EXPECTED_TESSDATA_SHA256",
                    {
                        name: hashlib.sha256(data).hexdigest()
                        for name, data in models.items()
                    },
                ),
                mock.patch.object(
                    backend,
                    "EXPECTED_COMPAT_OCR_NATIVE_SHA256",
                    {
                        name: hashlib.sha256(data).hexdigest()
                        for name, data in native_files.items()
                    },
                ),
                mock.patch.object(
                    backend.subprocess, "run", return_value=version_result
                ),
            ):
                result = backend.prepare_compat_runner(ezcon, runner)

            self.assertEqual(result, runner.resolve())
            for name, data in models.items():
                self.assertEqual((runner_dir / "Tessdata" / name).read_bytes(), data)
            for relative_name, data in native_files.items():
                self.assertEqual((runner_dir / Path(relative_name)).read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
