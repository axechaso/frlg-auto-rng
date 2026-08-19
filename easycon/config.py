import os
import yaml
from typing import Any, Dict

from app_paths import DATA_ROOT, RESOURCE_ROOT


_PROJECT_ROOT = str(RESOURCE_ROOT)
_DEFAULT_PATH = os.environ.get(
    "EASYCON_CONFIG", os.path.join(_PROJECT_ROOT, "default.yaml"))
_CUSTOM_PATH = os.path.join(str(DATA_ROOT), "custom.yaml")

config_data: Dict[str, Any] = {}
loaded_flag = False


def _load_yaml(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """深度合并：override 优先于 base，同为 dict 时递归合并。"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(config_path: str = None) -> Dict[str, Any]:
    """加载配置：默认读取 default.yaml 与 custom.yaml 并合并（custom 优先）。
    传入 config_path 时仅加载该单文件（向后兼容）。"""
    global config_data, loaded_flag

    if loaded_flag and config_path is None:
        return config_data

    if config_path is not None:
        config_data = _load_yaml(config_path)
    else:
        default = _load_yaml(_DEFAULT_PATH)
        custom = _load_yaml(_CUSTOM_PATH)
        config_data = _deep_merge(default, custom)

    loaded_flag = True
    return config_data


def get_config() -> Dict[str, Any]:
    if not loaded_flag:
        load_config()
    return config_data


def get(key: str, default: Any = None) -> Any:
    cfg = get_config()
    keys = key.split(".")
    val = cfg
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        else:
            return default
        if val is None:
            return default
    return val


def set(key: str, value: Any) -> None:
    """写入 custom.yaml（custom 优先级高于 default，故用户操作触发的更改写这里）。
    写完后重新合并 default+custom 到内存，后续 get() 立即可见合并结果。"""
    keys = key.split(".")

    # 1. 写回 custom.yaml（仅写入该 key，保留其它已有内容）
    custom = _load_yaml(_CUSTOM_PATH)
    d = custom
    for k in keys[:-1]:
        if not isinstance(d.get(k), dict):
            d[k] = {}
        d = d[k]
    d[keys[-1]] = value
    with open(_CUSTOM_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(custom, f, allow_unicode=True, sort_keys=False)

    # 2. 重新合并 default+custom 到内存（不能直接替换，否则丢失 default 部分）
    global config_data
    default = _load_yaml(_DEFAULT_PATH)
    config_data = _deep_merge(default, custom)


def reload_config(config_path: str = None):
    global config_data, loaded_flag
    config_data = {}
    loaded_flag = False
    return load_config(config_path)
