"""Portable egg configuration adapters matching the formal Tk file contract."""
from automation import EggRunRequest
from automation.easycon118 import EGG_PARENT_GENDERS, is_valid_egg_parent_pair
EGG_CONFIG_VERSION = 1
EGG_PARENT_CONFIG_KIND = "egg_parent"
EGG_FULL_CONFIG_KIND = "egg_full"
IV_STAT_LABELS = ("HP", "攻击", "防御", "特攻", "特防", "速度")

def parse_exact_ivs(values, label: str) -> tuple[int, int, int, int, int, int]:
    if len(values) != 6:
        raise ValueError(f"{label}必须包含六项 IV")
    result = []
    for stat, text in zip(IV_STAT_LABELS, values):
        try:
            value = int(str(text).strip())
        except ValueError as exc:
            raise ValueError(f"{label}{stat}必须是 0–31 的整数") from exc
        if not 0 <= value <= 31:
            raise ValueError(f"{label}{stat}必须在 0–31 之间")
        result.append(value)
    return tuple(result)


def build_egg_config_payload(
    game: str,
    nx_model,
    species_id,
    compatibility,
    parent_a_ivs,
    parent_b_ivs,
    start_from_prepared_254=False,
) -> dict:
    """Validate the egg-page settings and return a portable JSON payload."""
    game = str(game).strip()
    if game not in {"火红", "叶绿"}:
        raise ValueError("游戏版本只能是火红或叶绿")
    try:
        nx_model = int(nx_model)
    except (TypeError, ValueError) as exc:
        raise ValueError("机型必须是 Switch 1 或 Switch 2") from exc
    if nx_model not in {1, 2}:
        raise ValueError("机型必须是 Switch 1 或 Switch 2")
    try:
        species_id = int(species_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("蛋种全国图鉴编号必须是整数") from exc
    if not 1 <= species_id <= 386:
        raise ValueError("蛋种全国图鉴编号必须在 1-386 之间")
    try:
        compatibility = int(compatibility)
    except (TypeError, ValueError) as exc:
        raise ValueError("双亲相性只能填写 20、50 或 70") from exc
    if compatibility not in {20, 50, 70}:
        raise ValueError("双亲相性只能填写 20、50 或 70")
    for values, label in ((parent_a_ivs, "亲本A"), (parent_b_ivs, "亲本B")):
        if isinstance(values, (str, bytes)):
            raise ValueError(f"{label}必须包含六项 IV")
        try:
            len(values)
        except TypeError as exc:
            raise ValueError(f"{label}必须包含六项 IV") from exc
    parent_a_ivs = parse_exact_ivs(parent_a_ivs, "亲本A")
    parent_b_ivs = parse_exact_ivs(parent_b_ivs, "亲本B")
    if not isinstance(start_from_prepared_254, bool):
        raise ValueError("254 步启动模式必须是布尔值")
    return {
        "version": EGG_CONFIG_VERSION,
        "game": game,
        "nx_model": nx_model,
        "egg_species_id": species_id,
        "compatibility": compatibility,
        "parent_a_ivs": list(parent_a_ivs),
        "parent_b_ivs": list(parent_b_ivs),
        "start_from_prepared_254": start_from_prepared_254,
    }


def parse_egg_config_payload(payload) -> dict:
    """Validate a saved egg JSON object and return its canonical values."""
    if not isinstance(payload, dict):
        raise ValueError("配置文件顶层必须是 JSON 对象")
    try:
        version = int(payload.get("version", EGG_CONFIG_VERSION))
    except (TypeError, ValueError) as exc:
        raise ValueError("配置文件版本无效") from exc
    if version != EGG_CONFIG_VERSION:
        raise ValueError(f"不支持的孵蛋配置版本: {version}")
    return build_egg_config_payload(
        payload.get("game"),
        payload.get("nx_model"),
        payload.get("egg_species_id"),
        payload.get("compatibility"),
        payload.get("parent_a_ivs"),
        payload.get("parent_b_ivs"),
        payload.get("start_from_prepared_254", False),
    )


def build_egg_parent_config_payload(
    species_id,
    compatibility,
    parent_a_gender,
    parent_a_ivs,
    parent_b_gender,
    parent_b_ivs,
) -> dict:
    """Build a portable parent-only egg configuration."""
    try:
        species_id = int(species_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("蛋种全国图鉴编号必须是整数") from exc
    if not 1 <= species_id <= 386:
        raise ValueError("蛋种全国图鉴编号必须在 1-386 之间")
    try:
        compatibility = int(compatibility)
    except (TypeError, ValueError) as exc:
        raise ValueError("双亲相性只能填写 20、50 或 70") from exc
    if compatibility not in {20, 50, 70}:
        raise ValueError("双亲相性只能填写 20、50 或 70")
    parent_a_gender = str(parent_a_gender).strip()
    parent_b_gender = str(parent_b_gender).strip()
    if parent_a_gender not in EGG_PARENT_GENDERS:
        raise ValueError("孵蛋亲本 A 必须是雄、雌、无性别或百变怪")
    if parent_b_gender not in EGG_PARENT_GENDERS:
        raise ValueError("孵蛋亲本 B 必须是雄、雌、无性别或百变怪")
    if not is_valid_egg_parent_pair(parent_a_gender, parent_b_gender):
        raise ValueError("孵蛋亲本组合必须是雄+雌，或一只百变怪搭配另一只非百变怪")
    for values, label in ((parent_a_ivs, "亲本A"), (parent_b_ivs, "亲本B")):
        if isinstance(values, (str, bytes)):
            raise ValueError(f"{label}必须包含六项 IV")
        try:
            len(values)
        except TypeError as exc:
            raise ValueError(f"{label}必须包含六项 IV") from exc
    parent_a_ivs = parse_exact_ivs(parent_a_ivs, "亲本A")
    parent_b_ivs = parse_exact_ivs(parent_b_ivs, "亲本B")
    return {
        "kind": EGG_PARENT_CONFIG_KIND,
        "version": EGG_CONFIG_VERSION,
        "egg_species_id": species_id,
        "compatibility": compatibility,
        "parent_a_gender": parent_a_gender,
        "parent_a_ivs": list(parent_a_ivs),
        "parent_b_gender": parent_b_gender,
        "parent_b_ivs": list(parent_b_ivs),
    }


def parse_egg_parent_config_payload(payload) -> dict:
    """Read a parent configuration, including legacy whole-page version 1 files."""
    if not isinstance(payload, dict):
        raise ValueError("配置文件顶层必须是 JSON 对象")
    kind = payload.get("kind")
    if kind is None:
        legacy = parse_egg_config_payload(payload)
        return build_egg_parent_config_payload(
            legacy["egg_species_id"],
            legacy["compatibility"],
            payload.get("parent_a_gender", "雌"),
            legacy["parent_a_ivs"],
            payload.get("parent_b_gender", "雄"),
            legacy["parent_b_ivs"],
        )
    if kind != EGG_PARENT_CONFIG_KIND:
        raise ValueError("所选文件不是孵蛋亲本配置")
    try:
        version = int(payload.get("version", EGG_CONFIG_VERSION))
    except (TypeError, ValueError) as exc:
        raise ValueError("配置文件版本无效") from exc
    if version != EGG_CONFIG_VERSION:
        raise ValueError(f"不支持的孵蛋亲本配置版本: {version}")
    return build_egg_parent_config_payload(
        payload.get("egg_species_id"),
        payload.get("compatibility"),
        payload.get("parent_a_gender"),
        payload.get("parent_a_ivs"),
        payload.get("parent_b_gender"),
        payload.get("parent_b_ivs"),
    )


def build_egg_full_config_payload(
    game,
    nx_model,
    seed_mode,
    target_seed,
    held_advances,
    pickup_advances,
    species_id,
    compatibility,
    parent_a_gender,
    parent_a_ivs,
    parent_b_gender,
    parent_b_ivs,
    start_from_prepared_254=False,
    home_buffer_adaptive_threshold=False,
    seed_startup_scheme=0,
    seed_calibration_scheme=2,
    debug_log_output=1,
    reverse_expansion_layers=None,
    reverse_expansion_seed_tolerances=None,
    reverse_expansion_frame_half_widths=None,
) -> dict:
    """Validate and build a complete egg-page configuration."""
    parent = build_egg_parent_config_payload(
        species_id,
        compatibility,
        parent_a_gender,
        parent_a_ivs,
        parent_b_gender,
        parent_b_ivs,
    )
    game = str(game).strip()
    if game not in {"火红", "叶绿"}:
        raise ValueError("游戏版本只能是火红或叶绿")
    try:
        nx_model = int(nx_model)
    except (TypeError, ValueError) as exc:
        raise ValueError("机型必须是 Switch 1 或 Switch 2") from exc
    if nx_model not in {1, 2}:
        raise ValueError("机型必须是 Switch 1 或 Switch 2")
    try:
        seed_mode = int(seed_mode)
    except (TypeError, ValueError) as exc:
        raise ValueError("孵蛋 Seed 模式必须在 0-9 之间") from exc
    try:
        held_advances = int(held_advances)
        pickup_advances = int(pickup_advances)
    except (TypeError, ValueError) as exc:
        raise ValueError("Held/生成帧和 Pickup/领取帧必须是整数") from exc
    if not isinstance(start_from_prepared_254, bool):
        raise ValueError("254 步启动模式必须是布尔值")
    if not isinstance(home_buffer_adaptive_threshold, bool):
        raise ValueError("HOME_BUFFER 稳定低分自适应开关必须是布尔值")
    try:
        seed_startup_scheme = int(seed_startup_scheme)
    except (TypeError, ValueError) as exc:
        raise ValueError("Seed 启动方案只能是 0 或 1") from exc
    if seed_startup_scheme not in {0, 1}:
        raise ValueError("Seed 启动方案只能是 0（当前 HOME_BUFFER）或 1（固定用户界面 HOME）")
    try:
        seed_calibration_scheme = int(seed_calibration_scheme)
    except (TypeError, ValueError) as exc:
        raise ValueError("Seed 校准方案只能是 0、1 或 2") from exc
    if seed_calibration_scheme not in {0, 1, 2}:
        raise ValueError("Seed 校准方案只能是 0（原始 12 轮众数）、1（实验锁定细调）或 2（命中保持后的方向票接续）")
    try:
        debug_log_output = int(debug_log_output)
    except (TypeError, ValueError) as exc:
        raise ValueError("脚本输出日志模式只能是 0（精简）或 1（完整调试）") from exc
    if debug_log_output not in {0, 1}:
        raise ValueError("脚本输出日志模式只能是 0（精简）或 1（完整调试）")
    if reverse_expansion_layers is not None:
        try:
            reverse_expansion_layers = int(reverse_expansion_layers)
            reverse_expansion_seed_tolerances = tuple(
                int(value) for value in reverse_expansion_seed_tolerances
            )
            reverse_expansion_frame_half_widths = tuple(
                int(value) for value in reverse_expansion_frame_half_widths
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("反查扩窗配置必须包含整数层数、三层 Seed 容差和三层帧半宽") from exc
    game_code = ("fr" if game == "火红" else "lg") + ("_nx2" if nx_model == 2 else "_nx")
    request = EggRunRequest(
        game=game_code,
        seed_mode=seed_mode,
        target_seed=str(target_seed),
        held_advances=held_advances,
        pickup_advances=pickup_advances,
        species_id=parent["egg_species_id"],
        compatibility=parent["compatibility"],
        parent_a_gender=parent["parent_a_gender"],
        parent_a_ivs=tuple(parent["parent_a_ivs"]),
        parent_b_gender=parent["parent_b_gender"],
        parent_b_ivs=tuple(parent["parent_b_ivs"]),
        start_from_prepared_254=start_from_prepared_254,
        home_buffer_adaptive_threshold=home_buffer_adaptive_threshold,
        seed_startup_scheme=seed_startup_scheme,
        seed_calibration_scheme=seed_calibration_scheme,
        debug_log_output=debug_log_output,
        reverse_expansion_layers=reverse_expansion_layers,
        reverse_expansion_seed_tolerances=(
            None
            if reverse_expansion_seed_tolerances is None
            else tuple(reverse_expansion_seed_tolerances)
        ),
        reverse_expansion_frame_half_widths=(
            None
            if reverse_expansion_frame_half_widths is None
            else tuple(reverse_expansion_frame_half_widths)
        ),
    )
    request.validate()
    return {
        "kind": EGG_FULL_CONFIG_KIND,
        "version": EGG_CONFIG_VERSION,
        "game": game,
        "nx_model": nx_model,
        "seed_mode": seed_mode,
        "target_seed": request.normalized_seed,
        "held_advances": held_advances,
        "pickup_advances": pickup_advances,
        "egg_species_id": parent["egg_species_id"],
        "compatibility": parent["compatibility"],
        "parent_a_gender": parent["parent_a_gender"],
        "parent_a_ivs": parent["parent_a_ivs"],
        "parent_b_gender": parent["parent_b_gender"],
        "parent_b_ivs": parent["parent_b_ivs"],
        "start_from_prepared_254": start_from_prepared_254,
        "home_buffer_adaptive_threshold": home_buffer_adaptive_threshold,
        "seed_startup_scheme": seed_startup_scheme,
        "seed_calibration_scheme": seed_calibration_scheme,
        "debug_log_output": request.debug_log_output,
        "reverse_expansion_layers": request.reverse_expansion_layers,
        "reverse_expansion_seed_tolerances": (
            None
            if request.reverse_expansion_seed_tolerances is None
            else list(request.reverse_expansion_seed_tolerances)
        ),
        "reverse_expansion_frame_half_widths": (
            None
            if request.reverse_expansion_frame_half_widths is None
            else list(request.reverse_expansion_frame_half_widths)
        ),
    }


def parse_egg_full_config_payload(payload) -> dict:
    """Validate a saved complete egg-page configuration."""
    if not isinstance(payload, dict):
        raise ValueError("配置文件顶层必须是 JSON 对象")
    if payload.get("kind") != EGG_FULL_CONFIG_KIND:
        raise ValueError("所选文件不是孵蛋全部配置")
    try:
        version = int(payload.get("version", EGG_CONFIG_VERSION))
    except (TypeError, ValueError) as exc:
        raise ValueError("配置文件版本无效") from exc
    if version != EGG_CONFIG_VERSION:
        raise ValueError(f"不支持的孵蛋全部配置版本: {version}")
    return build_egg_full_config_payload(
        payload.get("game"),
        payload.get("nx_model"),
        payload.get("seed_mode"),
        payload.get("target_seed"),
        payload.get("held_advances"),
        payload.get("pickup_advances"),
        payload.get("egg_species_id"),
        payload.get("compatibility"),
        payload.get("parent_a_gender"),
        payload.get("parent_a_ivs"),
        payload.get("parent_b_gender"),
        payload.get("parent_b_ivs"),
        payload.get("start_from_prepared_254", False),
        payload.get("home_buffer_adaptive_threshold", False),
        payload.get("seed_startup_scheme", 0),
        payload.get("seed_calibration_scheme", 2),
        payload.get("debug_log_output", 1),
        payload.get("reverse_expansion_layers"),
        payload.get("reverse_expansion_seed_tolerances"),
        payload.get("reverse_expansion_frame_half_widths"),
    )
