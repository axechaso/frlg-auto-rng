"""Generate and launch a configured 1.1.8 project on pinned EasyCon 1.6.4a."""

import json
import hashlib
import re
import shutil
import struct
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from assets.game_text import CATEGORY_EN_TO_ZH, location_to_zh

from .planner import RunPlan


EXPECTED_LABEL_COUNT = 871
EXPECTED_LABEL_METHODS = {1: 15, 5: 502, 14: 354}
EXPECTED_LABEL_SHA256 = "934060b2bf40ac30b461bcf59fddcb375eeaceae75a809ec294920cc7d6fe0b8"
EASYCON_BACKEND_NAME = "EasyCon 1.6.4a"
EXPECTED_EZCON_VERSION = "1.6.4-a+9c86137c7e63bff842175470895727a5fa9bab52"
EXPECTED_EZCON_SHA256 = "559b81c234d2548c439926a88f5355ccac0958b8a191c1ecca48b2c7c71c1260"
EXPECTED_COMPAT_SOURCE_COMMIT = "9c86137c7e63bff842175470895727a5fa9bab52"
EXPECTED_COMPAT_PATCH_ID = "cli-image-label-ceiling-v1"
EXPECTED_TESSDATA_SHA256 = {
    "frlg_battle.traineddata": "7abcaef4936727b33717656b38fd5b5027823e1cafec21abb06cc8ef1f7ff758",
    "FRLG_EN_ALL.traineddata": "3272f23a6f259518813025d89be77d706574ccdf163132ccf6f5be15ca19cfa0",
}
DEFAULT_EZCON_PATH = (
    Path.home()
    / "Downloads"
    / "伊机控-EasyCon-v1.6.4alpha测试版-260518"
    / "publish"
    / "ezcon.exe"
)
DEFAULT_COMPAT_RUNNER_PATH = (
    Path(__file__).resolve().parents[1]
    / "runtime_backend"
    / "easycon164a-cli-gui-rounding-selfcontained"
    / "EasyCon2.CLI.exe"
)
STANDARD_TEMPLATE_NAME = "NS火叶全自动一键乱数1.1.8.ecs"
EGG_TEMPLATE_NAME = "NS火叶全自动一键乱数1.1.8-TV时间轴测试.ecs"
EXPECTED_TEMPLATE_NAMES = (STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME)
EXPECTED_SCRIPT_FILE_COUNT = 33
EXPECTED_SCRIPT_SHA256 = "bc0845d23f47805b1c6f46cd861deb69c01c7605a72d92ad7e00f538cee6f52e"


@dataclass(frozen=True)
class EasyCon118Options:
    nx_model: int | None = None
    paralysis: bool = False
    false_swipe: bool = False
    continue_capture_after_shiny: bool = False


@dataclass(frozen=True)
class EggRunRequest:
    """User-provided Ten Lines Egg result for the experimental same-seed flow."""

    game: str
    seed_mode: int
    target_seed: str
    held_advances: int
    pickup_advances: int
    species_id: int
    compatibility: int
    parent_a_gender: str
    parent_a_ivs: tuple[int, int, int, int, int, int]
    parent_b_gender: str
    parent_b_ivs: tuple[int, int, int, int, int, int]

    @property
    def nx_model(self) -> int:
        return 2 if self.game.endswith("nx2") else 1

    @property
    def normalized_seed(self) -> str:
        value = self.target_seed.strip().upper()
        if value.startswith("0X"):
            value = value[2:]
        return value.zfill(4)

    def validate(self) -> None:
        if self.game not in {"fr_nx", "fr_nx2", "lg_nx", "lg_nx2"}:
            raise ValueError(f"孵蛋测试只支持火红/叶绿 Switch 1/2，当前为 {self.game!r}")
        if not 0 <= self.seed_mode <= 9:
            raise ValueError("孵蛋 Seed 模式必须在 0-9 之间")
        if self.game.startswith("fr") and self.seed_mode == 3:
            raise ValueError("火红 NX Seed 表不包含模式 3 (stereo_r_a)")
        raw_seed = self.target_seed.strip().upper()
        if raw_seed.startswith("0X"):
            raw_seed = raw_seed[2:]
        seed = self.normalized_seed
        if not raw_seed or len(raw_seed) > 4 or not re.fullmatch(r"[0-9A-F]{4}", seed):
            raise ValueError("孵蛋目标 Seed 必须是 0000-FFFF 的十六进制数")
        if self.held_advances <= 0:
            raise ValueError("Held/生成目标帧必须大于 0")
        if self.pickup_advances - self.held_advances < 1800:
            raise ValueError("Pickup/领取目标帧必须至少比 Held/生成目标帧晚 1800 帧")
        if not 1 <= self.species_id <= 386:
            raise ValueError("孵蛋蛋种全国图鉴编号必须在 1-386 之间")
        if self.compatibility not in {20, 50, 70}:
            raise ValueError("孵蛋双亲相性只能填写 20、50 或 70")
        if self.parent_a_gender not in {"雌", "无性别"}:
            raise ValueError("孵蛋亲本 A 必须是雌或无性别")
        if self.parent_b_gender not in {"雄", "无性别"}:
            raise ValueError("孵蛋亲本 B 必须是雄或无性别")
        if self.parent_a_gender == self.parent_b_gender == "无性别":
            raise ValueError("两只亲本不能同时填写无性别")
        for label, ivs in (("A", self.parent_a_ivs), ("B", self.parent_b_ivs)):
            if len(ivs) != 6 or any(not 0 <= iv <= 31 for iv in ivs):
                raise ValueError(f"亲本 {label} 的六项 IV 必须均在 0-31 之间")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        result = asdict(self)
        result["target_seed"] = self.normalized_seed
        result["nx_model"] = self.nx_model
        result["mode"] = "egg_same_seed_experimental"
        return result


@dataclass(frozen=True)
class EasyConRuntimeCheck:
    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def probe_easycon_devices(ezcon_path: str | Path):
    """Return currently enumerated serial ports, video indexes and raw output."""
    ezcon_path = Path(ezcon_path).resolve()
    run_options = dict(
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    port = subprocess.run([str(ezcon_path), "port", "--list"], timeout=15, **run_options)
    video = subprocess.run([str(ezcon_path), "video", "--list"], timeout=20, **run_options)
    if port.returncode != 0 or video.returncode != 0:
        details = "\n".join(filter(None, (port.stderr, video.stderr)))
        raise RuntimeError(f"设备检测命令失败：{details or '未知错误'}")
    ports = {item.upper() for item in re.findall(r"\bCOM\d+\b", port.stdout, re.IGNORECASE)}
    videos = {
        int(item)
        for item in re.findall(r"(?m)^\s*\[(\d+)\]", video.stdout)
    }
    output = "端口：\n" + port.stdout + "\n采集设备：\n" + video.stdout
    if not ports:
        output += "\n未检测到 EasyCon 单片机串口。"
    if not videos:
        output += "\n未检测到采集设备。"
    return ports, videos, output


def inspect_label_corpus(label_dir: str | Path) -> dict[str, Any]:
    """Return a deterministic fingerprint of a 1.1.8 ``ImgLabel`` folder."""
    label_dir = Path(label_dir)
    files = sorted(
        (path for path in label_dir.iterdir() if path.is_file() and path.suffix == ".IL"),
        key=lambda path: path.name,
    )
    digest = hashlib.sha256()
    method_counts: dict[int, int] = {}
    total_bytes = 0
    for path in files:
        name = path.name.encode("utf-8")
        data = path.read_bytes()
        digest.update(struct.pack(">I", len(name)))
        digest.update(name)
        digest.update(struct.pack(">Q", len(data)))
        digest.update(data)
        total_bytes += len(data)
        payload = json.loads(data.decode("utf-8-sig"))
        method = int(payload.get("searchMethod", 5))
        method_counts[method] = method_counts.get(method, 0) + 1
    return {
        "count": len(files),
        "bytes": total_bytes,
        "methods": method_counts,
        "sha256": digest.hexdigest(),
    }


def inspect_script_corpus(source_dir: str | Path) -> dict[str, Any]:
    """Fingerprint both official 1.1.8 entry scripts and every file under ``lib``."""
    source_dir = Path(source_dir)
    templates = [source_dir / name for name in EXPECTED_TEMPLATE_NAMES]
    missing_templates = [path.name for path in templates if not path.is_file()]
    if missing_templates:
        raise FileNotFoundError(
            f"1.1.8 包缺少正式/孵蛋入口: {', '.join(missing_templates)}"
        )
    lib_dir = source_dir / "lib"
    if not lib_dir.is_dir():
        raise FileNotFoundError(f"1.1.8 包缺少 lib 目录: {lib_dir}")
    files = [(path.name, path) for path in templates]
    files.extend(
        (path.relative_to(source_dir).as_posix(), path)
        for path in sorted(item for item in lib_dir.rglob("*") if item.is_file())
    )
    digest = hashlib.sha256()
    total_bytes = 0
    for relative_name, path in files:
        name = relative_name.encode("utf-8")
        data = path.read_bytes()
        digest.update(struct.pack(">I", len(name)))
        digest.update(name)
        digest.update(struct.pack(">Q", len(data)))
        digest.update(data)
        total_bytes += len(data)
    return {
        "count": len(files),
        "bytes": total_bytes,
        "sha256": digest.hexdigest(),
        "template": STANDARD_TEMPLATE_NAME,
        "templates": [path.name for path in templates],
    }


def _is_wild(plan: RunPlan) -> bool:
    key = (plan.request.method or plan.target.method).lower()
    return "wild" in key


def _game_text(game: str) -> str:
    if game.startswith("fr"):
        return "火红"
    if game.startswith("lg"):
        return "叶绿"
    raise ValueError(f"1.1.8 只支持火红/叶绿，当前游戏为 {game!r}")


def plan_to_user_values(
    plan: RunPlan,
    options: EasyCon118Options | None = None,
) -> dict[str, Any]:
    """Map a generated plan to the editable variables at the top of 1.1.8."""
    options = options or EasyCon118Options()
    nx_model = options.nx_model
    if nx_model is None:
        nx_model = 2 if plan.request.game.endswith("nx2") else 1
    if nx_model not in (1, 2):
        raise ValueError("NX 机型必须是 1 (Switch1) 或 2 (Switch2)")
    expected_nx_model = 2 if plan.request.game.endswith("nx2") else 1
    if nx_model != expected_nx_model:
        raise ValueError(
            f"搜索游戏 {plan.request.game} 必须使用 NX 机型 {expected_nx_model}，"
            f"不能写入 {nx_model}"
        )

    is_wild = _is_wild(plan)
    category_zh = CATEGORY_EN_TO_ZH.get(plan.request.category, plan.request.category)
    location_zh = location_to_zh(plan.request.location)
    return {
        "游戏版本文本": _game_text(plan.request.game),
        "Seed模式": plan.seed_mode,
        "NX机型": nx_model,
        "目标Seed": plan.initial_seed.seed.upper(),
        "目标消耗帧": plan.initial_seed.advances,
        "目标全国图鉴编号": plan.species_id,
        "静态或野生": "野生" if is_wild else "静态",
        "宝可梦遭遇方法": category_zh if is_wild else "草丛",
        "宝可梦遭遇地点": location_zh if is_wild else "",
        "麻痹": int(options.paralysis),
        "点到为止": int(options.false_swipe),
        "出闪后继续抓捕": int(options.continue_capture_after_shiny),
    }


def egg_request_to_user_values(request: EggRunRequest) -> dict[str, Any]:
    """Map a Ten Lines Egg result to the experimental same-seed ECS fields."""
    request.validate()
    values: dict[str, Any] = {
        "游戏版本文本": _game_text(request.game),
        "Seed模式": request.seed_mode,
        "NX机型": request.nx_model,
        "目标Seed": request.normalized_seed,
        "目标消耗帧": request.held_advances,
        "目标宝可梦名称": "",
        "目标全国图鉴编号": request.species_id,
        "静态或野生": "孵蛋",
        "孵蛋同Seed模式": 1,
        "孵蛋领取目标帧": request.pickup_advances,
        "孵蛋双亲相性": request.compatibility,
        "孵蛋亲本A性别": request.parent_a_gender,
        "孵蛋亲本B性别": request.parent_b_gender,
    }
    for parent, ivs in (("A", request.parent_a_ivs), ("B", request.parent_b_ivs)):
        for stat, value in zip(("HP", "ATK", "DEF", "SPA", "SPD", "SPE"), ivs):
            values[f"孵蛋双亲{parent}_{stat}"] = value
    return values


def _ecs_literal(value: Any) -> str:
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def configure_template_text(
    template_text: str,
    plan: RunPlan,
    options: EasyCon118Options | None = None,
    *,
    allow_experimental: bool = False,
) -> str:
    """Replace only the declared 1.1.8 user-input assignments."""
    if not plan.route_support.can_start and not allow_experimental:
        raise ValueError(
            "该路线只允许搜索/生成计划，不能生成可启动的 1.1.8 正式脚本: "
            + plan.route_support.summary
        )

    return _configure_user_values(template_text, plan_to_user_values(plan, options))


def _configure_user_values(template_text: str, values: dict[str, Any]) -> str:
    marker = "# ============================进阶设置"
    user_section, separator, remainder = template_text.partition(marker)
    if not separator:
        raise ValueError("1.1.8 模板缺少进阶设置分界标记，拒绝在未知版本中替换参数")
    configured = user_section
    for name, value in values.items():
        pattern = re.compile(rf"(?m)^\s*\${re.escape(name)}\s*=\s*[^\r\n]*$")
        configured, count = pattern.subn(f"${name} = {_ecs_literal(value)}", configured)
        if count != 1:
            raise ValueError(f"1.1.8 模板字段 ${name} 应出现 1 次，实际为 {count} 次")
    return configured + (separator + remainder if separator else "")


def configure_egg_template_text(template_text: str, request: EggRunRequest) -> str:
    """Configure the 1.6.4a-only experimental same-seed egg entry."""
    return _configure_user_values(template_text, egg_request_to_user_values(request))


def write_configured_project(
    source_dir: str | Path,
    output_dir: str | Path,
    plan: RunPlan,
    options: EasyCon118Options | None = None,
    *,
    copy_assets: bool = True,
) -> Path:
    """Create an EasyCon CLI project with ``main.ecs``, ``lib`` and labels."""
    source_dir = Path(source_dir).resolve()
    output_dir = Path(output_dir).resolve()
    script_corpus = inspect_script_corpus(source_dir)
    if script_corpus["count"] != EXPECTED_SCRIPT_FILE_COUNT:
        raise ValueError(
            f"1.1.8 主脚本/lib 文件数应为 {EXPECTED_SCRIPT_FILE_COUNT}，"
            f"当前为 {script_corpus['count']}"
        )
    if script_corpus["sha256"] != EXPECTED_SCRIPT_SHA256:
        raise ValueError(
            "1.1.8 主脚本/lib 指纹不一致，拒绝混用未经审计的版本: "
            + script_corpus["sha256"]
        )
    template_path = source_dir / STANDARD_TEMPLATE_NAME

    output_dir.mkdir(parents=True, exist_ok=True)
    configured = configure_template_text(
        template_path.read_text(encoding="utf-8"),
        plan,
        options,
    )
    main_path = output_dir / "main.ecs"
    main_path.write_text(configured, encoding="utf-8")

    if copy_assets:
        for directory in ("lib", "ImgLabel"):
            source = source_dir / directory
            if not source.is_dir():
                raise FileNotFoundError(f"1.1.8 包缺少 {directory} 目录")
            target = output_dir / directory
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)

    manifest = {
        "source": str(source_dir.resolve()),
        "template": template_path.name,
        "plan": plan.to_dict(),
        "easycon118_options": asdict(options or EasyCon118Options()),
        "labels": {
            "expected_count": EXPECTED_LABEL_COUNT,
            "expected_methods": EXPECTED_LABEL_METHODS,
            "expected_sha256": EXPECTED_LABEL_SHA256,
        },
        "scripts": {
            "expected_count": EXPECTED_SCRIPT_FILE_COUNT,
            "expected_sha256": EXPECTED_SCRIPT_SHA256,
        },
        "backend": {
            "name": EASYCON_BACKEND_NAME,
            "expected_cli_version": EXPECTED_EZCON_VERSION,
            "expected_cli_sha256": EXPECTED_EZCON_SHA256,
        },
    }
    (output_dir / "plan.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return main_path


def write_configured_egg_project(
    source_dir: str | Path,
    output_dir: str | Path,
    request: EggRunRequest,
    *,
    copy_assets: bool = True,
) -> Path:
    """Create a runnable project for the experimental same-seed egg flow."""
    request.validate()
    source_dir = Path(source_dir).resolve()
    output_dir = Path(output_dir).resolve()
    script_corpus = inspect_script_corpus(source_dir)
    if script_corpus["count"] != EXPECTED_SCRIPT_FILE_COUNT:
        raise ValueError(
            f"1.1.8 正式/孵蛋主脚本及 lib 文件数应为 {EXPECTED_SCRIPT_FILE_COUNT}，"
            f"当前为 {script_corpus['count']}"
        )
    if script_corpus["sha256"] != EXPECTED_SCRIPT_SHA256:
        raise ValueError(
            "1.1.8 孵蛋脚本指纹不一致，拒绝混用未经审计的版本: "
            + script_corpus["sha256"]
        )
    template_path = source_dir / EGG_TEMPLATE_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    configured = configure_egg_template_text(
        template_path.read_text(encoding="utf-8"), request
    )
    main_path = output_dir / "main.ecs"
    main_path.write_text(configured, encoding="utf-8")

    if copy_assets:
        for directory in ("lib", "ImgLabel"):
            source = source_dir / directory
            if not source.is_dir():
                raise FileNotFoundError(f"1.1.8 包缺少 {directory} 目录")
            target = output_dir / directory
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)

    manifest = {
        "source": str(source_dir),
        "template": template_path.name,
        "egg_request": request.to_dict(),
        "experimental": True,
        "labels": {
            "expected_count": EXPECTED_LABEL_COUNT,
            "expected_methods": EXPECTED_LABEL_METHODS,
            "expected_sha256": EXPECTED_LABEL_SHA256,
        },
        "scripts": {
            "expected_count": EXPECTED_SCRIPT_FILE_COUNT,
            "expected_sha256": EXPECTED_SCRIPT_SHA256,
        },
        "backend": {
            "name": EASYCON_BACKEND_NAME,
            "expected_cli_version": EXPECTED_EZCON_VERSION,
            "expected_cli_sha256": EXPECTED_EZCON_SHA256,
        },
    }
    (output_dir / "plan.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return main_path


def validate_runtime(
    ezcon_path: str | Path,
    project_main: str | Path,
) -> EasyConRuntimeCheck:
    ezcon_path = Path(ezcon_path).resolve()
    project_main = Path(project_main).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    if not ezcon_path.is_file():
        errors.append(f"找不到 ezcon.exe: {ezcon_path}")
    else:
        try:
            ezcon_sha256 = hashlib.sha256(ezcon_path.read_bytes()).hexdigest()
        except OSError as exc:
            errors.append(f"无法读取 ezcon.exe: {exc}")
        else:
            if ezcon_sha256 != EXPECTED_EZCON_SHA256:
                errors.append(
                    "EasyCon 1.6.4a ezcon.exe 指纹不一致，拒绝运行: "
                    + ezcon_sha256
                )
    if not project_main.is_file():
        errors.append(f"找不到生成脚本: {project_main}")
    project_dir = project_main.parent
    if not (project_dir / "lib").is_dir():
        errors.append("生成项目缺少 lib 目录")
    label_dir = project_dir / "ImgLabel"
    if not label_dir.is_dir():
        errors.append("生成项目缺少 ImgLabel 目录")
    else:
        try:
            corpus = inspect_label_corpus(label_dir)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"1.1.8 标签清单读取失败: {exc}")
        else:
            if corpus["count"] != EXPECTED_LABEL_COUNT:
                errors.append(
                    f"1.1.8 标签数量应为 {EXPECTED_LABEL_COUNT}，当前为 {corpus['count']}"
                )
            if corpus["methods"] != EXPECTED_LABEL_METHODS:
                errors.append(
                    f"1.1.8 标签方法分布不一致: {corpus['methods']}"
                )
            if corpus["sha256"] != EXPECTED_LABEL_SHA256:
                errors.append(
                    "1.1.8 标签指纹不一致，可能不是已审计的完整标签包: "
                    + corpus["sha256"]
                )

    tessdata_dir = ezcon_path.parent / "Tessdata"
    for model, expected_sha256 in EXPECTED_TESSDATA_SHA256.items():
        model_path = tessdata_dir / model
        if not model_path.is_file():
            errors.append(f"EasyCon Tessdata 缺少 {model}")
            continue
        try:
            model_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
        except OSError as exc:
            errors.append(f"无法读取 EasyCon Tessdata/{model}: {exc}")
            continue
        if model_sha256 != expected_sha256:
            errors.append(f"EasyCon Tessdata/{model} 指纹不一致: {model_sha256}")

    if ezcon_path.is_file() and project_main.is_file() and not errors:
        run_options = dict(
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            version = subprocess.run(
                [str(ezcon_path), "--version"], timeout=15, **run_options
            )
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"无法读取 EasyCon 版本: {exc}")
        else:
            version_text = (version.stdout + "\n" + version.stderr).strip()
            version_line = version_text.splitlines()[-1] if version_text else "(无版本输出)"
            if version.returncode != 0:
                errors.append(f"EasyCon 版本检查失败，退出码 {version.returncode}")
            elif version_line != EXPECTED_EZCON_VERSION:
                errors.append(
                    f"当前适配器只审计过 EasyCon {EXPECTED_EZCON_VERSION}；检测结果为: "
                    + version_line
                )
            else:
                warnings.append("EasyCon 版本: " + version_line)

        if not errors:
            try:
                formatted = subprocess.run(
                    [str(ezcon_path), "format", str(project_main)],
                    cwd=str(project_main.parent),
                    timeout=60,
                    **run_options,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append(f"EasyCon 1.6.4a ECS 语法预检无法执行: {exc}")
            else:
                if formatted.returncode != 0:
                    details = (formatted.stderr or formatted.stdout).strip()
                    errors.append(
                        "EasyCon 1.6.4a ECS 语法预检失败，退出码 "
                        f"{formatted.returncode}: {details[-1000:]}"
                    )

    warnings.append(
        "已固定使用 EasyCon 1.6.4a；正式长跑前仍需完成停止、重连和识别稳定性验收。"
    )
    return EasyConRuntimeCheck(not errors, tuple(errors), tuple(warnings))


def build_run_command(
    ezcon_path: str | Path,
    project_main: str | Path,
    *,
    port: str,
    video_device: int,
    video_type: str = "DSHOW",
    verbose: bool = False,
) -> list[str]:
    if video_device < 0:
        raise ValueError("采集卡序号不能为负数")
    if not port or not port.strip():
        raise ValueError("串口不能为空")
    if video_type not in {"ANY", "DSHOW", "MSMF"}:
        raise ValueError(f"不支持的视频类型: {video_type}")
    ezcon_path = Path(ezcon_path).resolve()
    project_main = Path(project_main).resolve()
    command = [
        str(ezcon_path),
        "run",
        str(project_main),
        "--port",
        port,
        "--device",
        str(video_device),
        "--videotype",
        video_type,
    ]
    if verbose:
        command.append("--verbose")
    return command


def prepare_compat_runner(
    ezcon_path: str | Path,
    runner_path: str | Path = DEFAULT_COMPAT_RUNNER_PATH,
) -> Path:
    """Validate the pinned GUI-rounding CLI and sync the audited OCR models.

    EasyCon 1.6.4-a's GUI rounds image-label confidence upward with
    ``Math.Ceiling`` while its bundled ``ezcon.exe run`` truncates it.  The
    compatibility runner is built from the exact 1.6.4-a source commit and
    changes only that runtime behavior (plus .NET 9 build-only compatibility).
    """
    ezcon_path = Path(ezcon_path).resolve()
    runner_path = Path(runner_path).resolve()
    if not ezcon_path.is_file():
        raise FileNotFoundError(f"找不到原始 EasyCon 1.6.4-a ezcon.exe: {ezcon_path}")
    if hashlib.sha256(ezcon_path.read_bytes()).hexdigest() != EXPECTED_EZCON_SHA256:
        raise ValueError("原始 EasyCon 1.6.4-a ezcon.exe 指纹不一致，拒绝准备兼容运行器")
    if not runner_path.is_file():
        raise FileNotFoundError(
            "缺少 EasyCon 1.6.4-a GUI 识图取整兼容运行器；请先运行 "
            "tools\\build_easycon164a_compat_runner.ps1"
        )

    manifest_path = runner_path.with_name("build-manifest.json")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"兼容运行器缺少构建清单: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"兼容运行器构建清单无法读取: {exc}") from exc
    if manifest.get("source_commit") != EXPECTED_COMPAT_SOURCE_COMMIT:
        raise ValueError("兼容运行器不是从已锁定的 EasyCon 1.6.4-a commit 构建")
    if manifest.get("patch_id") != EXPECTED_COMPAT_PATCH_ID:
        raise ValueError("兼容运行器补丁标识不一致")
    runner_sha256 = hashlib.sha256(runner_path.read_bytes()).hexdigest()
    if manifest.get("sha256") != runner_sha256:
        raise ValueError(f"兼容运行器指纹不一致: {runner_sha256}")

    try:
        version = subprocess.run(
            [str(runner_path), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"兼容运行器版本检查失败: {exc}") from exc
    version_text = (version.stdout + "\n" + version.stderr).strip()
    version_line = version_text.splitlines()[-1] if version_text else ""
    if version.returncode != 0 or version_line != EXPECTED_EZCON_VERSION:
        raise ValueError(
            "兼容运行器版本不一致；期望 "
            f"{EXPECTED_EZCON_VERSION}，实际 {version_line or '(无输出)'}"
        )

    source_tessdata = ezcon_path.parent / "Tessdata"
    target_tessdata = runner_path.parent / "Tessdata"
    target_tessdata.mkdir(parents=True, exist_ok=True)
    for model, expected_sha256 in EXPECTED_TESSDATA_SHA256.items():
        source = source_tessdata / model
        if not source.is_file():
            raise FileNotFoundError(f"原始 EasyCon Tessdata 缺少 {model}")
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected_sha256:
            raise ValueError(f"原始 EasyCon Tessdata/{model} 指纹不一致")
        target = target_tessdata / model
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected_sha256:
            shutil.copy2(source, target)
    return runner_path


def launch_project(**kwargs) -> subprocess.Popen:
    """Launch only after the caller has shown and accepted preflight results."""
    command = build_run_command(**kwargs)
    return subprocess.Popen(command, cwd=str(Path(kwargs["project_main"]).parent))
