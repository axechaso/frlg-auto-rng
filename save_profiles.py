"""PokeFinder-style save profiles for the FRLG automation GUI."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path


PROFILE_FILE_VERSION = 1
SUPPORTED_GAMES = ("火红", "叶绿")
SUPPORTED_NX_MODELS = (1, 2)


def _parse_trainer_id(value, label: str) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是 0-65535 的整数") from exc
    if not 0 <= parsed <= 65535:
        raise ValueError(f"{label} 必须在 0-65535 之间")
    return parsed


@dataclass(frozen=True)
class SaveProfile:
    """One FireRed/LeafGreen save identity."""

    profile_id: str
    name: str
    game: str
    tid: int
    sid: int
    nx_model: int

    @classmethod
    def create(
        cls,
        name: str,
        game: str,
        tid,
        sid,
        nx_model,
        *,
        profile_id: str | None = None,
    ) -> "SaveProfile":
        normalized_name = str(name).strip()
        if not normalized_name:
            raise ValueError("存档名称不能为空")
        normalized_game = str(game).strip()
        if normalized_game not in SUPPORTED_GAMES:
            raise ValueError("游戏版本只能是火红或叶绿")
        try:
            normalized_nx = int(nx_model)
        except (TypeError, ValueError) as exc:
            raise ValueError("主机只能是 Switch 1 或 Switch 2") from exc
        if normalized_nx not in SUPPORTED_NX_MODELS:
            raise ValueError("主机只能是 Switch 1 或 Switch 2")
        normalized_id = str(profile_id or uuid.uuid4()).strip()
        if not normalized_id:
            raise ValueError("存档 ID 不能为空")
        return cls(
            profile_id=normalized_id,
            name=normalized_name,
            game=normalized_game,
            tid=_parse_trainer_id(tid, "TID"),
            sid=_parse_trainer_id(sid, "SID"),
            nx_model=normalized_nx,
        )

    @classmethod
    def from_dict(cls, payload) -> "SaveProfile":
        if not isinstance(payload, dict):
            raise ValueError("存档条目必须是对象")
        profile_id = payload.get("id")
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise ValueError("存档条目缺少有效 ID")
        return cls.create(
            payload.get("name", ""),
            payload.get("game", ""),
            payload.get("tid", ""),
            payload.get("sid", ""),
            payload.get("nx_model", ""),
            profile_id=profile_id,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.profile_id,
            "name": self.name,
            "game": self.game,
            "tid": self.tid,
            "sid": self.sid,
            "nx_model": self.nx_model,
        }

    @property
    def switch_name(self) -> str:
        return f"Switch {self.nx_model}"


class SaveProfileStore:
    """JSON-backed ordered profile collection with an active selection."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.profiles: list[SaveProfile] = []
        self.selected_profile_id: str | None = None

    def load(self) -> None:
        if not self.path.is_file():
            self.profiles = []
            self.selected_profile_id = None
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"无法读取存档信息文件：{exc}") from exc
        if not isinstance(payload, dict) or payload.get("version") != PROFILE_FILE_VERSION:
            raise ValueError("存档信息文件版本不受支持")
        raw_profiles = payload.get("profiles")
        if not isinstance(raw_profiles, list):
            raise ValueError("存档信息文件缺少 profiles 列表")
        profiles = [SaveProfile.from_dict(item) for item in raw_profiles]
        self._validate_collection(profiles)
        selected = payload.get("selected_profile_id")
        if selected is not None and not isinstance(selected, str):
            raise ValueError("selected_profile_id 必须是字符串或 null")
        if selected and not any(item.profile_id == selected for item in profiles):
            selected = None
        self.profiles = profiles
        self.selected_profile_id = selected or None

    @staticmethod
    def _validate_collection(profiles: list[SaveProfile]) -> None:
        ids: set[str] = set()
        names: set[str] = set()
        for profile in profiles:
            name_key = profile.name.casefold()
            if profile.profile_id in ids:
                raise ValueError(f"存档 ID 重复：{profile.profile_id}")
            if name_key in names:
                raise ValueError(f"存档名称重复：{profile.name}")
            ids.add(profile.profile_id)
            names.add(name_key)

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": PROFILE_FILE_VERSION,
            "selected_profile_id": self.selected_profile_id,
            "profiles": [profile.to_dict() for profile in self.profiles],
        }
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _commit(
        self,
        profiles: list[SaveProfile],
        selected_profile_id: str | None,
    ) -> None:
        self._validate_collection(profiles)
        if selected_profile_id is not None and not any(
            profile.profile_id == selected_profile_id for profile in profiles
        ):
            raise ValueError("当前存档不存在")
        previous_profiles = self.profiles
        previous_selected = self.selected_profile_id
        self.profiles = profiles
        self.selected_profile_id = selected_profile_id
        try:
            self._write()
        except OSError:
            self.profiles = previous_profiles
            self.selected_profile_id = previous_selected
            raise

    def get(self, profile_id: str | None) -> SaveProfile | None:
        if not profile_id:
            return None
        return next(
            (profile for profile in self.profiles if profile.profile_id == profile_id),
            None,
        )

    def _ensure_unique_name(self, name: str, *, excluding_id: str | None = None) -> None:
        key = name.casefold()
        if any(
            profile.name.casefold() == key and profile.profile_id != excluding_id
            for profile in self.profiles
        ):
            raise ValueError(f"已经存在名为“{name}”的存档")

    def add(self, name: str, game: str, tid, sid, nx_model) -> SaveProfile:
        profile = SaveProfile.create(name, game, tid, sid, nx_model)
        self._ensure_unique_name(profile.name)
        self._commit([*self.profiles, profile], profile.profile_id)
        return profile

    def update(self, profile_id: str, name: str, game: str, tid, sid, nx_model) -> SaveProfile:
        current = self.get(profile_id)
        if current is None:
            raise ValueError("要编辑的存档不存在")
        updated = SaveProfile.create(
            name, game, tid, sid, nx_model, profile_id=current.profile_id
        )
        self._ensure_unique_name(updated.name, excluding_id=current.profile_id)
        index = self.profiles.index(current)
        profiles = list(self.profiles)
        profiles[index] = updated
        self._commit(profiles, self.selected_profile_id)
        return updated

    def duplicate(self, profile_id: str) -> SaveProfile:
        current = self.get(profile_id)
        if current is None:
            raise ValueError("要复制的存档不存在")
        base = f"{current.name} 副本"
        name = base
        suffix = 2
        existing = {profile.name.casefold() for profile in self.profiles}
        while name.casefold() in existing:
            name = f"{base} {suffix}"
            suffix += 1
        return self.add(name, current.game, current.tid, current.sid, current.nx_model)

    def delete(self, profile_id: str) -> None:
        current = self.get(profile_id)
        if current is None:
            raise ValueError("要删除的存档不存在")
        profiles = [profile for profile in self.profiles if profile != current]
        selected = None if self.selected_profile_id == profile_id else self.selected_profile_id
        self._commit(profiles, selected)

    def select(self, profile_id: str | None) -> SaveProfile | None:
        if profile_id is not None and self.get(profile_id) is None:
            raise ValueError("要选择的存档不存在")
        self._commit(list(self.profiles), profile_id)
        return self.get(profile_id)
