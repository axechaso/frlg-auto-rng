"""Build isolated, finite SID training ECS projects; never modify mother assets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rng.ev_training import gen3_ev_yield
from rng.tenlines_utils import get_personal, NATURES
from tools.inspect_sid_training_packages import _name

STATS = ("HP", "ATK", "DEF", "SPA", "SPD", "SPE")
FOES = {10: "三代绿毛虫", 13: "三代独角虫", 16: "三代波波", 19: "三代小拉达",
        21: "三代烈雀", 23: "三代阿柏蛇", 29: "三代尼多兰", 32: "三代尼多朗",
        39: "三代胖丁", 43: "三代走路草", 50: "三代地鼠", 51: "三代三头地鼠",
        52: "三代喵喵", 57: "三代火爆猴", 58: "三代卡蒂狗", 63: "三代凯西", 92: "三代鬼斯"}
ARCHIVES = {
    "en": ("1.61客户端-（美版）努力值-捡道具-火红叶绿全能脚本V3.9.zip",
           "d6fa78e31139fad0bf53107ecf9161a2c61998709e89d87b27b571c90616950d"),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def archive_labels(path: Path, expected_hash: str) -> dict[str, tuple[bytes, str]]:
    if sha(path.read_bytes()) != expected_hash:
        raise ValueError(f"reference archive changed; inspect before use: {path}")
    result = {}
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > 10_000 or sum(i.file_size for i in infos) > 100 * 1024 * 1024:
            raise ValueError("reference archive exceeds limits")
        seen = set()
        for info in infos:
            name = _name(info)
            if name in seen:
                raise ValueError(f"duplicate member: {name}")
            seen.add(name)
            # Ignore the separate 'new icons' staging folder; use the actual
            # reference project's ImgLabel directory, never a filename-only merge.
            if not name.lower().endswith(".il") or PurePosixPath(name).parent.name != "ImgLabel":
                continue
            stem = PurePosixPath(name).stem
            if stem in result:
                raise ValueError(f"duplicate label: {stem}")
            result[stem] = (archive.read(info), name)
    return result


def picker(function: str, choices: list[tuple[str, int]], *, optional: bool = False,
           threshold: str = "$训练数字阈值") -> str:
    lines = [f"FUNC {function}(): INT", "    $best = -1", "    $second = -1", "    $value = -1"]
    groups: dict[int, list[str]] = {}
    for label, value in choices:
        groups.setdefault(value, []).append(label)
    for value, labels in groups.items():
        lines.append("    $score = -1")
        for label in labels:
            lines += [f"    $candidate = @{label}", "    IF $candidate > $score",
                      "        $score = $candidate", "    ENDIF"]
        lines += ["    IF $score > $best",
                  "        $second = $best", "        $best = $score", f"        $value = {value}",
                  "    ELIF $score > $second", "        $second = $score", "    ENDIF"]
    lines += [f"    IF $best < {threshold}"]
    lines += ["        RETURN 0" if optional else "        RETURN -2", "    ENDIF",
              "    IF $best - $second < $训练区分差值", "        RETURN -2", "    ENDIF",
              "    RETURN $value", "ENDFUNC"]
    return "\n".join(lines)


def data_and_functions() -> tuple[str, str]:
    arrays, funcs = [], []
    for index, stat in enumerate(STATS):
        arrays.append(f"$训练种族{stat} = [0," + ",".join(str(get_personal(i)["stats"][index]) for i in range(1, 387)) + "]")
        arrays.append(f"$训练产出{stat} = [0," + ",".join(str(gen3_ev_yield(i)[index]) for i in range(1, 387)) + "]")
    for function, prefix in (("训练取种族值", "训练种族"), ("训练取EV产出", "训练产出")):
        lines = [f"FUNC {function}($dex: INT, $stat: INT): INT"]
        if function == "训练取种族值":
            for game_index, game in enumerate(("fr_nx", "lg_nx")):
                lines.append(f"    IF $dex == 386 and $训练游戏 == {game_index}")
                for i, value in enumerate(get_personal(386, game)["stats"]):
                    lines += [f"        IF $stat == {i}", f"            RETURN {value}", "        ENDIF"]
                lines.append("    ENDIF")
        for i, stat in enumerate(STATS):
            lines += [f"    IF $stat == {i}", f"        RETURN ${prefix}{stat}[$dex]", "    ENDIF"]
        lines += ["    RETURN -1", "ENDFUNC"]
        funcs.append("\n".join(lines))
    return "\n".join(arrays), "\n\n".join(funcs)


def build_project(language: str, mode: int, source: dict[str, tuple[bytes, str]],
                  common: Path, directory: Path) -> dict:
    if language != "en" or mode not in (0, 1):
        raise ValueError("only English ROM self-battle/Exp. Share tests are supported")
    directory.mkdir(parents=True, exist_ok=False)
    labels_dir = directory / "ImgLabel"
    labels_dir.mkdir()
    manifest = {"schema": 1, "language": language, "recipient": "PARTICIPANT" if mode == 0 else "EXP_SHARE",
                "hardware_tested": False, "labels": {}, "notes": [
                    "Standalone test only; common mother labels and scripts are not modified.",
                    "Experience ownership relies on the documented one-/two-Pokemon party setup."]}

    def add(alias: str, original: str, *, old: bool = False) -> str:
        target = "TRAIN_" + alias
        if old:
            raw, origin = source[original]
        else:
            path = common / (original + ".IL")
            raw, origin = path.read_bytes(), "common/" + path.name
        payload = json.loads(raw.decode("utf-8-sig"))
        payload["name"] = target
        data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        (labels_dir / (target + ".IL")).write_bytes(data)
        manifest["labels"][target] = {"source": origin, "source_sha256": sha(raw), "sha256": sha(data),
                                      "search_method": payload.get("searchMethod", 5),
                                      "derived_range": False, "image_crop": None}
        return target

    controls = {"敌HP": "三代路闪HP检测", "主菜单": "三代通用菜单启动栏",
                "战斗菜单": "三代路闪闪光选项箭头", "我方血量": "三代血量足够",
                "空PP": "三代技能池", "经验": "获得经验",
                "学新技能1": "想学新技能", "学新技能2": "尝试学新技能",
                "进化": "宝可梦进化"}
    for alias, original in controls.items():
        add(alias, original, old=True)

    funcs = []
    nature_choices = []
    for i in range(25):
        original = "性格" + NATURES[i]
        nature_choices.append((add(f"性格{i}", original), i))
    funcs.append(picker("训练识别性格", nature_choices))
    funcs.append(picker("训练等级首位", [(add(f"等级首{i}", f"LV_十位_{i}"), i) for i in range(1, 10)]))
    funcs.append(picker("训练等级次位", [(add(f"等级次{i}", f"LV_个位_{i}"), i) for i in range(10)] +
                        [(add("等级次空", "LV_个位_空"), -1)]))
    funcs.append("""FUNC 训练识别等级(): INT
    $first = 训练等级首位()
    $second = 训练等级次位()
    IF $first < 0 or $second == -2
        RETURN -1
    ENDIF
    IF $second == -1
        RETURN $first
    ENDIF
    RETURN $first * 10 + $second
ENDFUNC""")
    reader = ["FUNC 训练识别能力($stat: INT, $minimum: INT, $maximum: INT): INT",
              "    $hundred = 0", "    $ten = 0", "    $one = -1"]
    for index, stat in enumerate(STATS):
        for place, cn in (("百", "hundred"), ("十", "ten"), ("个", "one")):
            files = sorted(common.glob(f"{stat}_{place}位_*.IL"))
            if not files:
                raise ValueError(f"missing numeric templates for {stat}/{place}")
            choices = []
            for path in files:
                number = int(path.stem.rsplit("_", 1)[1])
                choices.append((add(f"{stat}{place}{number}", path.stem), number))
            funcs.append(picker(f"训练{stat}{place}位", choices, optional=place != "个"))
        reader += [f"    IF $stat == {index}", f"        $one = 训练{stat}个位()",
                   "        IF $maximum >= 10", f"            $ten = 训练{stat}十位()", "        ENDIF",
                   "        IF $maximum >= 100", f"            $hundred = 训练{stat}百位()", "        ENDIF", "    ENDIF"]
    reader += ["    IF $one < 0 or $ten < 0 or $hundred < 0", "        RETURN -1", "    ENDIF",
               "    $value = $hundred * 100 + $ten * 10 + $one",
               "    IF $value < $minimum or $value > $maximum",
               "        PRINT 数字不在合法能力范围: & $value & \"，范围=\" & $minimum & \"-\" & $maximum",
               "        RETURN -1", "    ENDIF", "    RETURN $value", "ENDFUNC"]
    funcs.append("\n".join(reader))
    foe_choices, shiny_checks = [], []
    for dex, original in FOES.items():
        foe_choices.append((add(f"敌{dex}", original, old=True), dex))
        files = list(common.glob(f"{dex:03d}_*_闪.IL"))
        if len(files) != 1:
            raise ValueError(f"expected one shiny protection template: {dex}")
        label = add(f"敌闪{dex}", files[0].stem)
        shiny_checks += [f"    IF @{label} >= $训练状态阈值", "        PRINT 支持物种的闪光标签命中，不攻击。", "        RETURN -1", "    ENDIF"]
    foe_reader = picker("训练识别敌方", foe_choices, threshold="$训练状态阈值")
    foe_reader = foe_reader.replace("    $best = -1", "\n".join(shiny_checks) + "\n    $best = -1", 1)
    funcs.append(foe_reader)
    arrays, data_funcs = data_and_functions()
    template = (ROOT / "assets/sid_training_test/main.ecs.in").read_text(encoding="utf-8")
    for key, value in {"SESSION": f"test_{language}_{mode}_20261007", "LANG": "0",
                       "MODE": str(mode), "SLOT": str(1 + mode), "RECIPIENT": manifest["recipient"],
                       "DATA": arrays, "FUNCTIONS": data_funcs + "\n\n" + "\n\n".join(funcs)}.items():
        template = template.replace(f"@@{key}@@", value)
    refs = set(re.findall(r"@([\w\u4e00-\u9fff]+)", template))
    if refs != set(manifest["labels"]) or "@@" in template:
        raise ValueError(f"incomplete references/placeholders: missing={sorted(refs - set(manifest['labels']))}, "
                         f"unused={sorted(set(manifest['labels']) - refs)}")
    (directory / "main.ecs").write_text(template, encoding="utf-8", newline="\n")
    manifest["script_sha256"] = sha(template.encode("utf-8"))
    manifest["label_count"] = len(refs)
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def build_bundle(output: Path, archives: Path, common: Path) -> Path:
    if output.exists():
        raise FileExistsError(f"do not overwrite an existing test bundle: {output}")
    output.mkdir(parents=True)
    for language, (filename, expected) in ARCHIVES.items():
        source = archive_labels(archives / filename, expected)
        for mode in (0, 1):
            name = "美版" + ("-自己战斗" if mode == 0 else "-学习装置")
            build_project(language, mode, source, common, output / name)
    readme = (ROOT / "assets/sid_training_test/使用说明.md").read_bytes()
    (output / "先读使用说明.md").write_bytes(readme)
    destination = output.with_suffix(".zip")
    if destination.exists():
        raise FileExistsError(destination)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                archive.write(path, str(PurePosixPath(output.name, *path.relative_to(output).parts)))
    return destination


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archives", type=Path, default=Path("D:/Download"))
    parser.add_argument("--common", type=Path, default=ROOT / "local_assets/easycon118/ImgLabel")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(build_bundle(args.output.resolve(), args.archives, args.common))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
