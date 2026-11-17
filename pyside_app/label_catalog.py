"""Script and label choices for the in-app label maker (no file pickers)."""
from dataclasses import dataclass
from pathlib import Path

from automation.script_test import inspect_script_label_references


@dataclass(frozen=True)
class ScriptLabels:
    title: str
    path: Path


@dataclass(frozen=True)
class LabelChoice:
    name: str
    path: Path
    overridden: bool = False


def script_choices(window) -> tuple[ScriptLabels, ...]:
    """Prefer the selected plan, then the configured packages and direct ECS."""
    from automation.easycon118 import STANDARD_TEMPLATE_NAME, EGG_TEMPLATE_NAME
    from automation.sid_reverse118 import SID_REVERSE_TEMPLATE_NAME
    from automation.tid_rng137 import TID_SCRIPT_NAMES, TID_REFERENCE_SCRIPT_NAMES, TID_LEGACY_SCRIPT_NAMES

    choices = []
    seen = set()

    def add(title, path):
        if not path:
            return
        path = Path(path).expanduser().resolve()
        if path.is_file() and path not in seen:
            seen.add(path)
            choices.append(ScriptLabels(title, path))

    for key in ("workflow", "prepared"):
        prepared = getattr(window, key, None)
        if prepared is not None:
            add("已准备方案 · " + Path(prepared.project).name if prepared.project else "", prepared.project)
            # TID/starter plans can contain multiple independent entry scripts.
            if prepared.project:
                root = Path(prepared.project).parent
                if root.name in {"01_id", "00_calibration"}:
                    root = root.parent
                    for entry in sorted(root.glob("*/main.ecs")):
                        add("已准备方案 · " + entry.parent.name, entry)

    page = getattr(window, "current_page", "")
    sources = [("source", "2.0"), ("sid_source", "SID"), ("tid_source", "TID")]
    if page in {"sid", "tid"}:
        sources.sort(key=lambda item: item[0] != page + "_source")
    if page == "script_test":
        add("脚本测试 · 当前 ECS", window.fields["script_path"].text().strip())
    for field, title in sources:
        raw = window.fields[field].text().strip()
        if not raw:
            continue
        root = Path(raw).expanduser()
        if not root.is_dir():
            continue
        preferred = STANDARD_TEMPLATE_NAME
        if "script_entry" in window.fields and window.fields["script_entry"].currentIndex() == 1:
            preferred = EGG_TEMPLATE_NAME
        if page == "sid" and field == "sid_source":
            preferred = SID_REVERSE_TEMPLATE_NAME
        elif page == "tid" and field == "tid_source":
            preferred = TID_SCRIPT_NAMES.get(window.fields["tid_language"].currentText(), "")
        text_scripts = {*TID_SCRIPT_NAMES.values(), *TID_REFERENCE_SCRIPT_NAMES.values(), *TID_LEGACY_SCRIPT_NAMES.values()}
        for entry in sorted(root.iterdir(), key=lambda path: (path.name != preferred, path.name)):
            if (entry.suffix.lower() == ".ecs" or entry.name in text_scripts) and entry.is_file():
                add(f"{title} · {entry.stem}", entry)
    add("脚本测试 · 当前 ECS", window.fields["script_path"].text().strip())
    return tuple(choices)


def label_choices(script: Path, override_directory: Path | None = None) -> tuple[LabelChoice, ...]:
    """Only list labels referenced by this script and its library corpus.

    Missing files remain visible so the user sees an incomplete package rather
    than a misleading empty list. Device overrides take precedence by name.
    """
    directory = script.parent / "ImgLabel"
    files = {p.stem.casefold(): p for p in directory.iterdir()
             if p.is_file() and p.suffix.lower() == ".il"} if directory.is_dir() else {}
    overrides = {p.stem.casefold(): p for p in override_directory.iterdir()
                 if p.is_file() and p.suffix.lower() == ".il"} if override_directory and override_directory.is_dir() else {}
    return tuple(LabelChoice(name + ".IL", overrides.get(name.casefold(), files.get(name.casefold(), directory / (name + ".IL"))),
                             name.casefold() in overrides)
                 for name in inspect_script_label_references(script))
