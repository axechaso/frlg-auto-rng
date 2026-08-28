"""Execute the actual ECS arithmetic/control flow; compare with exhaustive pairs.

This replay is hardware-free. Real pinned 1.6.4-a compilation/evaluation remains
a separate release check (the Python translation is not a runtime replacement).
"""

import ast
import itertools
import random
import re
import unittest

from automation.seed_common_regions import ASSET, upgrade_entry, upgrade_library


class CommonReplay:
    def __init__(self, seed_span=100, adv_span=30):
        source = ASSET.read_text(encoding="utf-8")
        self.v = {n: ast.literal_eval(value) for n, value in re.findall(r"(?m)^\$(\w+) = (\d+|\[[^\n]*\])$", source)}
        self.v.update(共同区Seed总跨度=seed_span, 共同区ADV总跨度=adv_span)
        self.logs = []
        self.env = {"v": self.v, "print_log": self.logs.append,
                    "取Seed最大索引": lambda game: 10000,
                    "取MS": lambda game, index: index * index + 10,
                    "候选MSE评分": lambda dx, dy, sx, sy: dx * dx * sx + dy * dy * sy}
        for name, header, body in re.findall(r"(?ms)^FUNC (\w+)(?:\(([^\n]*)\))?(?:: INT)?\n(.*?)^ENDFUNC", source):
            params = re.findall(r"\$(\w+): INT", header)

            def expr(s):
                s = re.sub(r"\$(\w+)", lambda m: m[1] if m[1] in params else f"v[{m[1]!r}]", s)
                return s.replace(" / ", " // ")

            lines = [f"def {name}({', '.join(params)}):"]
            depth = 1
            for raw in body.splitlines():
                line = raw.split("#", 1)[0].strip()
                if not line:
                    continue
                if line in ("ENDIF", "NEXT"):
                    depth -= 1
                    continue
                if line.startswith("ELIF ") or line == "ELSE":
                    depth -= 1
                prefix = "    " * depth
                if line.startswith(("IF ", "ELIF ")):
                    word, condition = line.split(" ", 1)
                    lines.append(prefix + word.lower() + " " + expr(condition) + ":")
                    depth += 1
                elif line == "ELSE":
                    lines.append(prefix + "else:")
                    depth += 1
                elif line == "FOR":
                    lines.append(prefix + "while True:")
                    depth += 1
                elif line.startswith("FOR "):
                    var, start, end = re.fullmatch(r"FOR (\$\w+) = (.+) TO (.+)", line).groups()
                    lines.append(prefix + f"for {expr(var)} in range({expr(start)}, {expr(end)} + 1):")
                    depth += 1
                elif line.startswith("PRINT "):
                    lines.append(prefix + "pass")
                elif line.startswith("CALL "):
                    lines.append(prefix + line[5:] + "()")
                elif line.startswith("RETURN"):
                    lines.append(prefix + "return " + expr(line[6:].strip() or "None"))
                elif line in ("BREAK", "CONTINUE"):
                    lines.append(prefix + line.lower())
                elif line.startswith("$"):
                    lines.append(prefix + expr(line))
                else:
                    raise AssertionError(line)
            exec(compile("\n".join(lines), f"<actual ECS: {name}>", "exec"), self.env)

    def call(self, name, *args):
        return self.env[name](*args)

    def submit(self, points):
        self.call("共同区开始扫描")
        for seed, adv in points:
            self.call("共同区收集配对", seed, adv, seed)
        return self.call("共同区提交")

    def rank(self):
        return (-self.v["C_最佳覆盖"], self.v["C_最佳ADV跨度"], self.v["C_最佳Seed跨度"])


def brute_force(rounds, seed_span, adv_span):
    best = (0, 0, 0)
    # Each round chooses zero or ONE actual pair, never independent axis ranges.
    for chosen in itertools.product(*[[None] + list(set(r)) for r in rounds]):
        points = [p for p in chosen if p is not None]
        if not points:
            continue
        sx = max(p[0] for p in points) - min(p[0] for p in points)
        sy = max(p[1] for p in points) - min(p[1] for p in points)
        if sx <= seed_span and sy <= adv_span:
            best = min(best, (-len(points), sy, sx))
    return best


class SeedCommonRegionsTests(unittest.TestCase):
    def test_random_pairs_match_exhaustive_one_per_round_search(self):
        rng = random.Random(118164)
        for case in range(120):
            rounds = []
            replay = CommonReplay(10, 6)
            for _ in range(4):
                points = list(set((rng.randrange(24), rng.randrange(20)) for _ in range(3)))
                if set(points) not in [set(r) for r in rounds]:
                    rounds.append(points)
                replay.submit(points)
            with self.subTest(case=case):
                self.assertEqual(replay.rank(), brute_force(rounds, 10, 6))

    def test_chain_cannot_grow_across_seed_or_adv_limit(self):
        for rounds in ([[(0, 0)], [(60, 10)], [(120, 20)], [(180, 30)]],
                       [[(0, 0)], [(10, 20)], [(20, 40)], [(30, 60)]]):
            replay = CommonReplay()
            for points in rounds:
                replay.submit(points)
            self.assertEqual(replay.v["C_最佳覆盖"], 2)
            self.assertLessEqual(replay.v["C_最佳Seed跨度"], 100)
            self.assertLessEqual(replay.v["C_最佳ADV跨度"], 30)

    def test_pair_correlation_not_independent_axis_envelopes(self):
        replay = CommonReplay(10, 10)
        replay.submit([(0, 100), (100, 0)])
        replay.submit([(0, 0)])
        self.assertEqual(replay.v["C_最佳覆盖"], 1)

    def test_equal_adv_boundary_keeps_narrower_seed_alternative(self):
        replay = CommonReplay(10, 6)
        for points in ([(14, 5)], [(20, 3), (23, 3)], [(17, 4)]):
            replay.submit(points)
        self.assertEqual(replay.rank(), (-3, 2, 6))

    def test_repeated_candidates_or_permuted_batches_do_not_add_votes(self):
        replay = CommonReplay()
        replay.submit([(10, 2), (11, 3), (10, 2)])
        replay.submit([(11, 3), (10, 2)])
        self.assertEqual(replay.v["C_轮数"], 1)
        self.assertEqual(replay.v["C_重复数"], 1)
        self.assertEqual(replay.call("共同区提交"), 0)

    def test_same_seed_distinct_advs_are_retained(self):
        replay = CommonReplay()
        replay.submit([(40004, 1404), (40004, 1600)])
        self.assertEqual(replay.v["C_轮长度"][0], 2)
        self.assertEqual(replay.v["C_史ADV"][:2], [1404, 1600])

    def test_tight_five_beats_chain_of_six(self):
        replay = CommonReplay()
        for r in range(6):
            points = [(39800 + r * 20, 1400 + r * 32)]
            if r < 5:
                points.append((40000 + r * 10, 1500 + r * 3))
            replay.submit(points)
        self.assertEqual(replay.rank(), (-5, 12, 40))

    def test_separate_equal_coverage_hypotheses_do_not_influence_selection(self):
        replay = CommonReplay()
        for r in range(4):
            replay.submit([(40000 + r, 1500 + r), (40500 + r * 2, 1550 + r * 2)])
        self.assertEqual(replay.v["C_歧义"], 1)
        self.assertEqual(replay.v["C_可用"], 0)
        self.assertEqual(replay.call("共同区候选加权距离", 42000, 1800, 1, 1), 0)

    def test_unambiguous_three_rounds_support_both_axes(self):
        replay = CommonReplay()
        for r in range(3):
            replay.submit([(40000 + r, 1500 + r)])
        self.assertEqual(replay.v["C_可用"], 1)
        self.assertEqual(replay.call("共同区候选加权距离", 40001, 1501, 1, 1), 0)
        self.assertGreater(replay.call("共同区候选加权距离", 40001, 1510, 1, 1), 0)
        replay.v["共同区参与排序"] = 0
        replay.call("共同区重算")
        self.assertEqual(replay.v["C_可用"], 0)

    def test_twelve_round_sliding_window_forgets_old_points(self):
        replay = CommonReplay()
        for r in range(13):
            replay.submit([(r * 1000, r * 100)])
        self.assertEqual(replay.v["C_轮数"], 12)
        self.assertNotIn(0, [replay.v["C_史Seed"][r * 200] for r in range(12)])

    def test_capacity_overflow_never_becomes_truncated_evidence(self):
        replay = CommonReplay()
        self.assertEqual(replay.submit([(r, r) for r in range(201)]), 0)
        self.assertEqual(replay.v["C_轮数"], 0)
        self.assertEqual(replay.v["C_可用"], 0)

    def test_scan_replacement_does_not_turn_candy_into_new_round(self):
        replay = CommonReplay()
        replay.call("共同区开始扫描")
        replay.call("共同区收集配对", 10, 10, 10)
        replay.call("共同区开始扫描")
        replay.call("共同区收集配对", 20, 20, 20)
        replay.call("共同区提交")
        self.assertEqual(replay.v["C_轮数"], 1)
        self.assertEqual(replay.v["C_史Seed"][0], 20)

    def test_normalization_uses_real_table_not_fixed_ms_per_seed(self):
        replay = CommonReplay()
        replay.call("共同区收集", 1, 10, 2, 1500, 3, 250)
        self.assertEqual(replay.v["C_本Seed"][0], 12 * 12 + 10 + 250)
        self.assertEqual(replay.v["C_本ADV"][0], 1503)
        replay.call("共同区收集", 1, 0, -1, 1500, 3, 250)
        self.assertEqual(replay.v["C_本坏"], 1)

    def test_hard_limits_include_exact_boundary(self):
        replay = CommonReplay()
        replay.submit([(40000, 1500)])
        replay.submit([(40100, 1530)])
        self.assertEqual(replay.rank(), (-2, 30, 100))

    def test_library_install_is_idempotent_and_keeps_other_code(self):
        original = "$other = 1\nFUNC 保留函数(): INT\n    RETURN 7\nENDFUNC\n"
        first = upgrade_library(original)
        self.assertEqual(upgrade_library(first), first)
        self.assertIn(original.split("FUNC ")[1], first)

    def test_user_common_region_settings_survive_materialization(self):
        original = "$other = 1\nFUNC 保留函数(): INT\n    RETURN 7\nENDFUNC\n"
        first = upgrade_library(original).replace("$共同区Seed总跨度 = 100", "$共同区Seed总跨度 = 80")
        self.assertIn("$共同区Seed总跨度 = 80", upgrade_library(first))


if __name__ == "__main__":
    unittest.main()
