"""Replay the actual HOME_BUFFER ECS subset without touching hardware.

This is a deterministic control-flow regression harness, not a substitute for
the mandatory real EasyCon 1.6.4-a format check or Switch acceptance testing.
"""

import re
import unittest

from automation.easycon118 import (
    EGG_HOME_BUFFER_GLOBALS,
    EGG_HOME_BUFFER_OVERRIDE_PATH,
    HOME_BUFFER_ADAPTIVE_GLOBALS,
    HOME_BUFFER_RECOVERY_PATH,
    STANDARD_HOME_BUFFER_OVERRIDE_PATH,
)


class ECSReplay:
    def __init__(self, controller=None, frames=()):
        self.values = {
            name: int(value)
            for name, value in re.findall(
                r"(?m)^\$(\w+) = (-?\d+)$",
                HOME_BUFFER_ADAPTIVE_GLOBALS + EGG_HOME_BUFFER_GLOBALS,
            )
        }
        self.values.update(NX机型=1, 调试日志输出=0, HOME_BUFFER延迟=1200)
        self.actions = []
        self.waits = []
        self.frames = list(frames) or [{}]
        self.frame = 0
        self.steps = 0
        self.env = {
            "v": self.values,
            "label": lambda name: self.frames[self.frame].get(name, 0),
            "wait": self.wait,
            "button": lambda name, duration=0: self.actions.append(name),
            "tick": self.tick,
            "range": range,
            "int": int,
        }
        source = HOME_BUFFER_RECOVERY_PATH.read_text(encoding="utf-8")
        if controller:
            source += "\n" + controller.read_text(encoding="utf-8")
        self.load(source)

    def wait(self, duration):
        self.waits.append(duration)
        self.frame = min(self.frame + 1, len(self.frames) - 1)

    def tick(self):
        self.steps += 1
        if self.steps > 10000:
            raise AssertionError("ECS replay exceeded its instruction budget")

    def load(self, source):
        for match in re.finditer(
            r"(?ms)^FUNC (\w+)(?:\((.*?)\))?(?:: INT)?\n(.*?)^ENDFUNC",
            source,
        ):
            name, header, body = match.groups()
            params = re.findall(r"\$(\w+): INT", header or "")

            def expression(text):
                text = re.sub(
                    r"\$(\w+)",
                    lambda m: m[1] if m[1] in params else f"v[{m[1]!r}]",
                    text,
                )
                return re.sub(r"@(\w+)", lambda m: f"label({m[1]!r})", text)

            lines = [f"def {name}({', '.join(params)}):"]
            indent = 1
            loop_id = 0
            for raw in body.splitlines():
                line = raw.split("#", 1)[0].strip()
                if not line:
                    continue
                if line in ("ENDIF", "NEXT"):
                    indent -= 1
                    continue
                if line.startswith("ELIF ") or line == "ELSE":
                    indent -= 1
                prefix = "    " * indent
                if line.startswith("IF ") or line.startswith("ELIF "):
                    word, condition = line.split(" ", 1)
                    lines.append(prefix + word.lower() + " " + expression(condition) + ":")
                    indent += 1
                elif line == "ELSE":
                    lines.append(prefix + "else:")
                    indent += 1
                elif line == "FOR":
                    lines.append(prefix + "while True:")
                    indent += 1
                    lines.append("    " * indent + "tick()")
                elif line.startswith("FOR "):
                    loop_id += 1
                    loop = re.fullmatch(r"FOR \$(\w+) = (.+) TO (.+)", line)
                    if loop is None:
                        raise AssertionError(f"Unsupported ECS loop: {line}")
                    var, start, end = loop.groups()
                    lines.append(prefix + f"for _i{loop_id} in range(int({expression(start)}), int({expression(end)}) + 1):")
                    indent += 1
                    lines.append("    " * indent + f"v[{var!r}] = _i{loop_id}")
                    lines.append("    " * indent + "tick()")
                elif line.startswith("PRINT "):
                    lines.append(prefix + "pass")
                elif line.startswith("WAIT "):
                    lines.append(prefix + "wait(" + expression(line[5:]) + ")")
                elif re.fullmatch(r"(?:A|B|X|HOME)(?: \d+)?", line):
                    parts = line.split()
                    lines.append(prefix + f"button({parts[0]!r}, {parts[1] if len(parts) > 1 else 0})")
                elif line.startswith("RETURN"):
                    lines.append(prefix + "return " + expression(line[6:].strip() or "None"))
                elif line in ("CONTINUE", "BREAK"):
                    lines.append(prefix + line.lower())
                elif re.match(r"\$\w+ = ", line):
                    lines.append(prefix + expression(line))
                else:
                    raise AssertionError(f"Unsupported ECS statement: {line}")
            exec(compile("\n".join(lines), f"<ECS replay: {name}>", "exec"), self.env)

    def call(self, name, *args):
        return self.env[name](*args)


class HomeBufferRecoveryTests(unittest.TestCase):
    def locked(self):
        replay = ECSReplay()
        replay.values.update(HOME_BUFFER锁定启用=1, HOME_BUFFER锁定延迟=1200)
        return replay

    def test_mixed_unknown_normal_unknown_does_not_unlock_or_move(self):
        replay = self.locked()
        # The failing log's 94/63/57, 61/100/47, 50/50/0 classifications.
        for state in (0, 2, 0):
            delay = replay.call("HOME_BUFFER规划下一延迟", state)
            self.assertEqual(delay, 1200)
            replay.values["HOME_BUFFER延迟"] = delay
        self.assertEqual(replay.values["HOME_BUFFER锁定启用"], 1)
        self.assertEqual(replay.values["HOME_BUFFER锁定连续失败"], 0)

    def test_three_confirmed_normal_exits_unlock_with_fifty_ms_step(self):
        replay = self.locked()
        self.assertEqual(
            [replay.call("HOME_BUFFER规划下一延迟", 2) for _ in range(3)],
            [1200, 1200, 1150],
        )
        self.assertEqual(replay.values["HOME_BUFFER锁定启用"], 0)

    def test_unknown_only_probes_when_no_value_is_locked(self):
        replay = self.locked()
        self.assertEqual([replay.call("HOME_BUFFER规划下一延迟", 0) for _ in range(6)], [1200] * 6)
        replay = ECSReplay()
        self.assertEqual([replay.call("HOME_BUFFER规划下一延迟", 0) for _ in range(3)], [1200, 1200, 1250])
        replay.values["HOME_BUFFER延迟"] = 1250
        # Returning to 1200 is a legitimate retry, not a false empty bracket.
        self.assertEqual(replay.call("HOME_BUFFER规划下一延迟", 2), 1200)

    def test_strict_resample_recovers_94_then_97_without_keys(self):
        replay = ECSReplay()
        states = iter([0, 1])
        replay.env["HOME_BUFFER识别稳定状态"] = lambda nx: next(states)
        self.assertEqual(replay.call("HOME_BUFFER重采样状态", 1), 1)
        self.assertEqual(replay.waits, [200])
        self.assertEqual(replay.actions, [])
        self.assertEqual(replay.values["HOME_BUFFER有效识图阈值"], 95)

    def test_home_icon_with_low_playing_score_is_not_closed(self):
        replay = ECSReplay(frames=[{"主页": 97, "正确退出": 94, "HOME_BUFFER正确退出": 61}])
        self.assertEqual(replay.call("HOME_BUFFER恢复启动原点"), 0)
        self.assertEqual(replay.actions, [])

    def test_unknown_recovery_presses_home_at_most_once_across_retries(self):
        replay = ECSReplay(frames=[{"主页": 50, "正确退出": 50, "HOME_BUFFER正确退出": 50}])
        for _ in range(3):
            self.assertEqual(replay.call("HOME_BUFFER恢复启动原点"), 0)
        self.assertEqual(replay.actions, ["HOME"])

    def test_playing_screen_closes_without_home_toggle(self):
        closed = {"主页": 97, "正确退出": 50, "HOME_BUFFER正确退出": 50}
        replay = ECSReplay(frames=[
            {"主页": 97, "正确退出": 61, "HOME_BUFFER正确退出": 97},
            {"正在关闭": 97}, closed, closed, closed,
        ])
        self.assertEqual(replay.call("HOME_BUFFER恢复启动原点"), 1)
        self.assertEqual(replay.actions, ["X", "A"])

    def test_other_console_home_label_cannot_confirm_ns1_origin(self):
        replay = ECSReplay(frames=[{"主页_NS2": 100, "正确退出_NS2": 100}])
        self.assertEqual(replay.call("HOME_BUFFER恢复启动原点"), 0)
        self.assertNotIn("X", replay.actions)
        self.assertNotIn("A", replay.actions)

    def test_playing_state_has_priority_over_sleep_marker(self):
        closed = {"主页": 97, "正确退出": 50, "HOME_BUFFER正确退出": 50}
        replay = ECSReplay(frames=[
            {"主页": 97, "正确退出": 97, "错误退出": 97},
            {"正在关闭": 97}, closed, closed, closed,
        ])
        self.assertEqual(replay.call("HOME_BUFFER恢复启动原点"), 1)
        self.assertEqual(replay.actions, ["X", "A"])

    def test_closing_animation_only_waits(self):
        replay = ECSReplay(frames=[{"主页": 97, "正在关闭": 97}])
        self.assertEqual(replay.call("HOME_BUFFER恢复启动原点"), 0)
        self.assertEqual(replay.actions, [])

    def test_unlocked_1200_1250_retry_does_not_stop_at_old_boundary(self):
        replay = ECSReplay(EGG_HOME_BUFFER_OVERRIDE_PATH)
        states = iter([0, 0, 0, 2, 1])
        observed = []

        def observe(nx):
            observed.append(replay.values["HOME_BUFFER延迟"])
            return next(states)

        replay.env["HOME_BUFFER重采样状态"] = observe
        replay.env["HOME_BUFFER恢复启动原点"] = lambda: 1
        replay.call("HOME_BUFFER")
        self.assertEqual(observed, [1200, 1200, 1200, 1250, 1200])
        self.assertEqual(replay.values["孵蛋HOME_BUFFER失败"], 0)
        self.assertEqual(replay.values["HOME_BUFFER锁定延迟"], 1200)

    def test_both_controllers_replay_log_and_keep_1200(self):
        for controller in (EGG_HOME_BUFFER_OVERRIDE_PATH, STANDARD_HOME_BUFFER_OVERRIDE_PATH):
            with self.subTest(controller=controller.name):
                replay = ECSReplay(controller)
                replay.values.update(HOME_BUFFER锁定启用=1, HOME_BUFFER锁定延迟=1200)
                states = iter([0, 2, 0, 1])
                replay.env["HOME_BUFFER重采样状态"] = lambda nx: next(states)
                replay.env["HOME_BUFFER恢复启动原点"] = lambda: 1
                replay.call("HOME_BUFFER")
                self.assertEqual(replay.values["HOME_BUFFER延迟"], 1200)
                self.assertEqual(replay.values["HOME_BUFFER锁定启用"], 1)
                self.assertEqual(replay.values["孵蛋HOME_BUFFER失败"], 0)
                self.assertEqual(replay.actions.count("HOME"), 4)

    def test_failed_recovery_never_launches_and_is_bounded(self):
        replay = ECSReplay(EGG_HOME_BUFFER_OVERRIDE_PATH)
        replay.env["HOME_BUFFER恢复启动原点"] = lambda: 0
        replay.call("HOME_BUFFER")
        self.assertEqual(replay.actions, [])
        self.assertEqual(replay.values["孵蛋HOME_BUFFER失败"], 1)
        self.assertEqual(replay.values["孵蛋HOME_BUFFER尝试"], 21)
