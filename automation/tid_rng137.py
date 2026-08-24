"""Configure the pinned FRLG TID/SID 1.3.7 scripts for EasyCon 1.6.4-a."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .easycon118 import (
    EASYCON_BACKEND_NAME,
    EXPECTED_EZCON_SHA256,
    EXPECTED_EZCON_VERSION,
    EasyConRuntimeCheck,
    inspect_label_corpus,
)


ROOT = Path(__file__).resolve().parents[1]
TID_HOME_BUFFER_ADAPTIVE_PATH = (
    ROOT / "assets" / "tid_rng137_extensions" / "home_buffer_adaptive.ecs"
)
DOWNLOADED_TID_SOURCE = (
    Path.home() / "Downloads" / "自定义TID SID 御三家乱数多功能包1.3"
)
IMPORTED_TID_SOURCE = ROOT / "local_assets" / "tid_rng137"
DEFAULT_TID_SOURCE_PATH = (
    IMPORTED_TID_SOURCE if IMPORTED_TID_SOURCE.is_dir() else DOWNLOADED_TID_SOURCE
)

TID_SCRIPT_NAMES = {
    "英文": "【TID+SID乱数&穷举】英文版-火红叶绿1.3.7.txt",
    "日文": "【TID+SID乱数&穷举】日文版-火红叶绿1.3.7.txt",
}
EXPECTED_TID_SCRIPT_SHA256 = {
    "英文": "8438b473f2032efe4b013fd6ac5976c62c7013c4bb983be543181ab6457c55d9",
    "日文": "77072be5e6c4fdbb7723e0df7f36f10c2df5e62394c5e5f07b08b105e836cfe7",
}
EXPECTED_TID_LABEL_COUNT = 328
EXPECTED_TID_LABEL_METHODS = {1: 4, 3: 1, 5: 322, 11: 1}
EXPECTED_TID_LABEL_SHA256 = (
    "9b4ca9049371d0e4bd60ecfd039ba3e397c82e3da1db2c53f7cf7248568bbc93"
)

_USER_SECTION_END = "# ======================== 用户自定义区结束"
_TID_HOME_BUFFER_GLOBAL_ANCHOR = "$识图判断阈值 = 95\n"
_TID_HOME_BUFFER_ADAPTIVE_MARKER = (
    "# TID 1.3.7 HOME_BUFFER 稳定低分自适应：仅由工具显式开启。"
)
_TID_HOME_BUFFER_ORIGINAL = """FUNC HOME_BUFFER
    FOR
        A
        1500
        A
        WAIT $HOME_BUFFER延迟
        PRINT 尝试HOME_BUFFER延迟: & $HOME_BUFFER延迟 & " ms"
        HOME 100
        1500
        IF @HOME_BUFFER正确退出 >= 95 and @错误退出 < 95 and @错误退出_NS2 < 95 or @HOME_BUFFER正确退出_NS2 >= 95 and @错误退出 < 95 and @错误退出_NS2 < 95
            PRINT HOME_BUFFER正确
            PRINT 可用HOME_BUFFER延迟: & $HOME_BUFFER延迟 & " ms"
            RETURN
        ELIF @错误退出 >= 95 or @错误退出_NS2 >= 95
            PRINT 错误进入休眠菜单
            B
            1000
            CALL 关闭游戏
        ELIF @正确退出 >= 95 or @正确退出_NS2 >= 95
            PRINT HOME_BUFFER延迟过长，减100继续尝试中
            CALL 关闭游戏
            $HOME_BUFFER延迟 -= 100
        ELSE
            PRINT HOME_BUFFER延迟过短，加100继续尝试中
            $HOME_BUFFER延迟 += 100
        ENDIF
    NEXT
ENDFUNC"""
_TID_HOME_BUFFER_ADAPTIVE_GLOBALS = """# TID HOME_BUFFER 自适应只作用于生成副本，默认由工具关闭。
$HOME_BUFFER自适应最低阈值 = 90
$HOME_BUFFER有效识图阈值 = 95
$HOME_BUFFER自适应稳定要求 = 3
$HOME_BUFFER自适应采样 = 0
$HOME_BUFFER选中正确 = 0
$HOME_BUFFER选中普通 = 0
$HOME_BUFFER选中错误 = 0
$HOME_BUFFER自适应候选状态 = 0
$HOME_BUFFER自适应候选分数 = 0
$HOME_BUFFER自适应首次状态 = 0
$HOME_BUFFER自适应首次分数 = 0
$HOME_BUFFER识别状态 = 0
"""
_JAPANESE_LOOP_164A_SOURCE = """    $NameIndex = 0

    FOR $InputLen
        $输入目标字符 = calcname($name, $NameIndex)
        CALL 输入单字符
        $NameIndex += 1
    NEXT"""
_JAPANESE_LOOP_164A_REPLACEMENT = """    $有效名称末索引 = $InputLen - 1

    FOR $NameIndex = 0 TO $有效名称末索引
        $输入目标字符 = calcname($name, $NameIndex)
        CALL 输入单字符
    NEXT"""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ecs_literal(value: Any) -> str:
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _supported_name_characters(template_text: str) -> set[str]:
    return set(re.findall(r'\$char\s*==\s*"((?:\\.|[^"\\])*)"', template_text))


@dataclass(frozen=True)
class TidRngRequest:
    language: str = "英文"
    mode: int = 1
    calibration_check: bool = False
    op_fixed_delay: int = 30550
    f1_fixed_delay: int = 22050
    f2_fixed_delay: int = 4250
    f3_fixed_delay: int = 14900
    close_game_delay: int = 1500
    home_buffer_delay: int = 1200
    op_correction: int = 0
    gender: int = 1
    nx_model: int = 1
    target_tid: int = 0
    target_sid: int = 38449
    sid_advance_correction: int = 0
    op_target_frame: int = 3693
    f1_target_frame: int = 2693
    f2_target_frame: int = 2105
    op_start: int = 3902
    f1_start: int = 2649
    f2_start: int = 2183
    player_name: str = "Alxe"
    select_correction: int = 0
    sound: int = 0
    button_mode: int = 0
    seed_button: int = 0
    name_entry_button: int = 0
    sid_random: bool = False
    f3_random_range: int = 0
    op_rng_range: int = 0
    f1_rng_range: int = 0
    f2_rng_range: int = 0
    op_max_range: int = 600
    f1_max_range: int = 30
    f2_max_range: int = 300
    f2_candidate_range: int = 2000
    f1_candidate_range: int = 100
    denoise_need_hit: int = 2
    denoise_try_window: int = 10
    same_id: bool = False
    sequential_id: bool = False
    include_65535: bool = True
    single_digit_id: bool = False
    image_threshold: int = 95
    home_buffer_adaptive_threshold: bool = False

    def validate(self, template_text: str | None = None) -> None:
        if self.language not in TID_SCRIPT_NAMES:
            raise ValueError("ROM 语言必须是英文或日文")
        if self.mode not in {0, 1}:
            raise ValueError("TID 运行模式必须是穷举模式或乱数模式")
        if self.gender not in {0, 1}:
            raise ValueError("主角性别必须是男性或女性")
        if self.nx_model not in {1, 2}:
            raise ValueError("NS 机型必须是 Switch 1 或 Switch 2")
        if not 0 <= self.target_tid <= 65535:
            raise ValueError("目标 TID 必须在 0-65535 之间")
        if not 0 <= self.target_sid <= 65535:
            raise ValueError("目标 SID 必须在 0-65535 之间")
        if self.sound not in {0, 1}:
            raise ValueError("Sound 只能是 MONO 或 STEREO")
        if self.button_mode not in {0, 1, 2}:
            raise ValueError("Button Mode 只能是 HELP、LR 或 L=A")
        if self.seed_button not in {0, 1, 2}:
            raise ValueError("Seed Button 只能是 A、START 或 L(L=A)")
        if self.name_entry_button not in {0, 1}:
            raise ValueError("取名进入键只能是 A 或 B")

        nonnegative = {
            "OP 固定延迟": self.op_fixed_delay,
            "F1 固定延迟": self.f1_fixed_delay,
            "F2 固定延迟": self.f2_fixed_delay,
            "F3 固定延迟": self.f3_fixed_delay,
            "关闭游戏延迟": self.close_game_delay,
            "HOME_BUFFER 延迟": self.home_buffer_delay,
            "OP 目标帧": self.op_target_frame,
            "F1 目标帧": self.f1_target_frame,
            "F2 目标帧": self.f2_target_frame,
            "OP 起点": self.op_start,
            "F1 起点": self.f1_start,
            "F2 起点": self.f2_start,
            "F3 随机范围": self.f3_random_range,
            "OP 乱数半径": self.op_rng_range,
            "F1 乱数半径": self.f1_rng_range,
            "F2 乱数半径": self.f2_rng_range,
            "OP 穷举范围": self.op_max_range,
            "F1 穷举范围": self.f1_max_range,
            "F2 穷举范围": self.f2_max_range,
            "F2 候选阈值": self.f2_candidate_range,
            "F1 候选阈值": self.f1_candidate_range,
        }
        for label, value in nonnegative.items():
            if value < 0:
                raise ValueError(f"{label}不能为负数")
        if self.f3_random_range != 0:
            raise ValueError(
                "F3随机模式已移除；请使用目标SID自动计算ADV，或使用固定F3延迟"
            )
        if not 1 <= self.denoise_need_hit <= 10:
            raise ValueError("去噪命中数必须在 1-10 之间")
        if not 1 <= self.denoise_try_window <= 10:
            raise ValueError("去噪窗口必须在 1-10 之间")
        if self.denoise_need_hit > self.denoise_try_window:
            raise ValueError("去噪命中数不能大于去噪窗口")
        if not 1 <= self.image_threshold <= 100:
            raise ValueError("识图阈值必须在 1-100 之间")
        if not isinstance(self.home_buffer_adaptive_threshold, bool):
            raise ValueError("HOME_BUFFER稳定低分自适应开关必须是布尔值")
        if not self.player_name:
            raise ValueError("主角名称不能为空")
        name_limit = 7 if self.language == "英文" else 10
        if len(self.player_name) > name_limit:
            raise ValueError(f"{self.language}版主角名称最多按键 {name_limit} 次")
        if template_text is not None:
            supported = _supported_name_characters(template_text)
            invalid = sorted(set(self.player_name) - supported)
            if invalid:
                values = "、".join(invalid)
                hint = "；日文浊音/半浊音需拆写，例如 ド 写成 ト゛" if self.language == "日文" else ""
                raise ValueError(f"主角名称包含脚本不支持的字符：{values}{hint}")

    def to_user_values(self) -> dict[str, Any]:
        return {
            "$ID_RNG": self.mode,
            "$脚本固定延迟检查开关": int(self.calibration_check),
            "$OP脚本固定延迟": self.op_fixed_delay,
            "$F1脚本固定延迟": self.f1_fixed_delay,
            "$F2脚本固定延迟": self.f2_fixed_delay,
            "$F3脚本固定延迟": self.f3_fixed_delay,
            "$关闭游戏延迟": self.close_game_delay,
            "$HOME_BUFFER延迟": self.home_buffer_delay,
            "$OP修正": self.op_correction,
            "$gender": self.gender,
            "$NS机型": self.nx_model,
            "_TARGET_TID": self.target_tid,
            "_TARGET_SID": self.target_sid,
            "$SID_ADV修正": self.sid_advance_correction,
            "$OP目标帧": self.op_target_frame,
            "$F1目标帧": self.f1_target_frame,
            "$F2目标帧": self.f2_target_frame,
            "$OP起点": self.op_start,
            "$F1起点": self.f1_start,
            "$F2起点": self.f2_start,
            "$name": self.player_name,
            "$select补偿": self.select_correction,
            "$Sound": self.sound,
            "$Button_Mode": self.button_mode,
            "$Seed_Button": self.seed_button,
            "$取名进入键": self.name_entry_button,
            "$SID_RAND": int(self.sid_random),
            "$F3_Max_Rand_Range": self.f3_random_range,
            "$OP_RNG_Max_Range": self.op_rng_range,
            "$F1_RNG_Max_Range": self.f1_rng_range,
            "$F2_RNG_Max_Range": self.f2_rng_range,
            "$OP_Max_Range": self.op_max_range,
            "$F1_Max_Range": self.f1_max_range,
            "$F2_Max_Range": self.f2_max_range,
            "$F2candidate_range": self.f2_candidate_range,
            "$F1candidate_range": self.f1_candidate_range,
            "$denoise_need_hit": self.denoise_need_hit,
            "$denoise_try_window": self.denoise_try_window,
            "$same_id_switch": int(self.same_id),
            "$continue_id_switch": int(self.sequential_id),
            "$65535开关": int(self.include_65535),
            "$个位检测开关": int(self.single_digit_id),
            "$识图判断阈值": self.image_threshold,
        }

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["mode_name"] = "乱数" if self.mode == 1 else "穷举"
        return result


def inspect_tid_package(source_dir: str | Path) -> dict[str, Any]:
    source_dir = Path(source_dir).resolve()
    scripts = {}
    for language, filename in TID_SCRIPT_NAMES.items():
        path = source_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"TID 1.3.7 包缺少 {filename}")
        scripts[language] = {
            "filename": filename,
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
    label_dir = source_dir / "ImgLabel"
    if not label_dir.is_dir():
        raise FileNotFoundError("TID 1.3.7 包缺少 ImgLabel 目录")
    return {"scripts": scripts, "labels": inspect_label_corpus(label_dir)}


def verify_tid_package(source_dir: str | Path) -> dict[str, Any]:
    source_dir = Path(source_dir).resolve()
    manifest = inspect_tid_package(source_dir)
    for language, expected_sha256 in EXPECTED_TID_SCRIPT_SHA256.items():
        actual = manifest["scripts"][language]["sha256"]
        if actual != expected_sha256:
            raise ValueError(f"{language}版 TID 1.3.7 脚本指纹不一致: {actual}")
    labels = manifest["labels"]
    if labels["count"] != EXPECTED_TID_LABEL_COUNT:
        raise ValueError(
            f"TID 标签数量应为 {EXPECTED_TID_LABEL_COUNT}，当前为 {labels['count']}"
        )
    if labels["methods"] != EXPECTED_TID_LABEL_METHODS:
        raise ValueError(f"TID 标签方法分布不一致: {labels['methods']}")
    if labels["sha256"] != EXPECTED_TID_LABEL_SHA256:
        raise ValueError(f"TID 标签指纹不一致: {labels['sha256']}")
    return manifest


def configure_tid_template_text(
    template_text: str,
    request: TidRngRequest,
    *,
    include_flow_marker: bool = False,
) -> str:
    request.validate(template_text)
    user_section, separator, remainder = template_text.partition(_USER_SECTION_END)
    if not separator:
        raise ValueError("TID 1.3.7 模板缺少用户自定义区结束标记")
    configured = user_section
    for name, value in request.to_user_values().items():
        pattern = re.compile(rf"(?m)^\s*{re.escape(name)}\s*=\s*[^\r\n]*$")
        configured, count = pattern.subn(f"{name} = {_ecs_literal(value)}", configured)
        if count != 1:
            raise ValueError(f"TID 1.3.7 字段 {name} 应出现 1 次，实际为 {count} 次")
    configured += separator + remainder
    if request.language == "日文":
        if configured.count(_JAPANESE_LOOP_164A_SOURCE) != 1:
            raise ValueError("日文版取名循环结构与已审计的 1.3.7 模板不一致")
        configured = configured.replace(
            _JAPANESE_LOOP_164A_SOURCE,
            _JAPANESE_LOOP_164A_REPLACEMENT,
            1,
        )
    if include_flow_marker:
        success_block = """                IF $denoise_hit_count >= $denoise_need_hit
                    BREAK 2"""
        success_count = configured.count(success_block)
        if success_count != 5:
            raise ValueError(
                "TID 1.3.7模板的五种成功退出结构与已审计版本不一致："
                f"{success_count}"
            )
        marker_block = """                IF $denoise_hit_count >= $denoise_need_hit
                    PRINT TIDFLOW|ID|MATCH=1
                    PRINT TIDFLOW|ID|TID= & $curr1 & $curr2 & $curr3 & $curr4 & $curr5
                    PRINT TIDFLOW|ID|SID_ADV= & $adv
                    BREAK 2"""
        configured = configured.replace(success_block, marker_block)
    if request.home_buffer_adaptive_threshold:
        configured = _apply_tid_home_buffer_adaptive(configured)
    return configured


def _apply_tid_home_buffer_adaptive(template_text: str) -> str:
    """Install the opt-in TID HOME_BUFFER classifier in a generated copy."""
    if _TID_HOME_BUFFER_ADAPTIVE_MARKER in template_text:
        return template_text
    if template_text.count(_TID_HOME_BUFFER_GLOBAL_ANCHOR) != 1:
        raise ValueError("TID 1.3.7模板缺少唯一的识图阈值锚点")
    if template_text.count(_TID_HOME_BUFFER_ORIGINAL) != 1:
        raise ValueError("TID 1.3.7模板的HOME_BUFFER函数与已审计版本不一致")
    extension = TID_HOME_BUFFER_ADAPTIVE_PATH.read_text(encoding="utf-8").rstrip()
    template_text = template_text.replace(
        _TID_HOME_BUFFER_GLOBAL_ANCHOR,
        _TID_HOME_BUFFER_GLOBAL_ANCHOR + _TID_HOME_BUFFER_ADAPTIVE_GLOBALS,
        1,
    )
    return template_text.replace(_TID_HOME_BUFFER_ORIGINAL, extension, 1)


def referenced_image_labels(template_text: str) -> tuple[str, ...]:
    return tuple(sorted(set(re.findall(r"@([\w\u4e00-\u9fff]+)", template_text))))


def write_configured_tid_project(
    source_dir: str | Path,
    output_dir: str | Path,
    request: TidRngRequest,
    *,
    include_flow_marker: bool = False,
) -> Path:
    source_dir = Path(source_dir).resolve()
    output_dir = Path(output_dir).resolve()
    manifest = verify_tid_package(source_dir)
    template_path = source_dir / TID_SCRIPT_NAMES[request.language]
    template_text = template_path.read_text(encoding="utf-8")
    configured = configure_tid_template_text(
        template_text,
        request,
        include_flow_marker=include_flow_marker,
    )

    label_dir = source_dir / "ImgLabel"
    missing = [
        name for name in referenced_image_labels(configured)
        if not (label_dir / f"{name}.IL").is_file()
    ]
    if missing:
        raise FileNotFoundError("TID 脚本缺少引用标签: " + ", ".join(missing))

    output_dir.mkdir(parents=True, exist_ok=True)
    main_path = output_dir / "main.ecs"
    main_path.write_text(configured, encoding="utf-8")
    output_labels = output_dir / "ImgLabel"
    if output_labels.exists():
        shutil.rmtree(output_labels)
    shutil.copytree(label_dir, output_labels)
    (output_dir / "plan.json").write_text(
        json.dumps(
            {
                "source": str(source_dir),
                "template": template_path.name,
                "tid_request": request.to_dict(),
                "source_manifest": manifest,
                "japanese_164a_compatibility": request.language == "日文",
                "tid_starter_flow_marker": include_flow_marker,
                "backend": {
                    "name": EASYCON_BACKEND_NAME,
                    "expected_cli_version": EXPECTED_EZCON_VERSION,
                    "expected_cli_sha256": EXPECTED_EZCON_SHA256,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return main_path


def validate_tid_runtime(
    ezcon_path: str | Path,
    project_main: str | Path,
) -> EasyConRuntimeCheck:
    ezcon_path = Path(ezcon_path).resolve()
    project_main = Path(project_main).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    if not ezcon_path.is_file():
        errors.append(f"找不到 ezcon.exe: {ezcon_path}")
    elif _sha256_file(ezcon_path) != EXPECTED_EZCON_SHA256:
        errors.append("EasyCon 1.6.4-a ezcon.exe 指纹不一致，拒绝运行")
    if not project_main.is_file():
        errors.append(f"找不到生成脚本: {project_main}")
    label_dir = project_main.parent / "ImgLabel"
    if not label_dir.is_dir():
        errors.append("TID 运行项目缺少 ImgLabel 目录")
    else:
        try:
            labels = inspect_label_corpus(label_dir)
        except Exception as exc:
            errors.append(f"TID 标签读取失败: {exc}")
        else:
            if labels["count"] != EXPECTED_TID_LABEL_COUNT:
                errors.append(
                    f"TID 标签数量应为 {EXPECTED_TID_LABEL_COUNT}，当前为 {labels['count']}"
                )
            if labels["methods"] != EXPECTED_TID_LABEL_METHODS:
                errors.append(f"TID 标签方法分布不一致: {labels['methods']}")
            if labels["sha256"] != EXPECTED_TID_LABEL_SHA256:
                errors.append("TID 标签包不是已审计的 1.3.7 版本")

    run_options = dict(
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if ezcon_path.is_file() and not errors:
        try:
            version = subprocess.run(
                [str(ezcon_path), "--version"], timeout=15, **run_options
            )
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"无法读取 EasyCon 版本: {exc}")
        else:
            output = (version.stdout + "\n" + version.stderr).strip()
            version_line = output.splitlines()[-1] if output else "(无版本输出)"
            if version.returncode != 0 or version_line != EXPECTED_EZCON_VERSION:
                errors.append(
                    f"TID 正式运行只支持 EasyCon {EXPECTED_EZCON_VERSION}；检测到 {version_line}"
                )
            else:
                warnings.append("EasyCon 版本: " + version_line)
        if not errors:
            try:
                formatted = subprocess.run(
                    [str(ezcon_path), "format", str(project_main)],
                    cwd=str(project_main.parent),
                    timeout=90,
                    **run_options,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append(f"TID ECS 语法预检无法执行: {exc}")
            else:
                if formatted.returncode != 0:
                    details = (formatted.stderr or formatted.stdout).strip()
                    errors.append(
                        f"EasyCon 1.6.4-a TID ECS 语法预检失败: {details[-1000:]}"
                    )
    warnings.append(
        "TID/SID 1.3.7 参数生成已接通；名称、性别或操作流程变化后必须重新校准固定延迟。"
    )
    return EasyConRuntimeCheck(not errors, tuple(errors), tuple(warnings))
