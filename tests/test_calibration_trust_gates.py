import unittest

from automation.calibration_trust_gates import (
    MARKER,
    apply_calibration_trust_gates_text,
)


def legacy_fixture() -> str:
    return """\
FUNC 执行自动校准与等待更新(): INT
    # 非目标Seed的±1剩余帧不喂相位簇；绝对偏差大于1和目标Seed照常。TV圈样本、Seed样本始终写入。
    IF $本轮剩余帧校准允许 == 1
        $投票忽略 = 投票设置帧窗($本轮消耗帧误差, $消耗帧实际执行修正量, $进入TV)
    ENDIF
    $投票忽略 = 投票设置Seed窗($命中差索引, $Seed累计修正索引)
    IF $Seed校准方案 == 0
        $投票忽略 = 投票设置Seed校准样本($命中差索引, $Seed累计修正索引)
    ENDIF
    $投票忽略 = 投票设置TV帧窗($本轮消耗帧误差, $消耗帧实际执行修正量, $进入TV)

    IF $Seed校准方案 == 0
        $Seed本次修正索引 = 计算Seed原始众数修正()
    ELSE
        $Seed本次修正索引 = 计算Seed锁定众数修正()
        IF $Seed锁定启用 == 1
            $Seed簇内 = 1
        ELSE
            $Seed簇内 = 0
        ENDIF
    ENDIF

        # 只用目标Seed建立双分支证据；非目标Seed不能单独把随机VBlank路径认成稳定双分支。
        IF $命中差索引 == 0
        ENDIF
        $TV帧慢修正触发 = 0
        IF $TV帧慢修正参数有效 == 0 or $TV帧慢修正参数累计修正 != $消耗帧实际执行修正量
            $TV帧慢修正参数有效 = 1
        ENDIF
        IF $TV双分支锁定 == 1 and $TV双分支跟踪等待帧 == $TV等待帧
            $TV帧慢修正当前票数 = 0
        ELSE
            $TV帧慢修正窗口[$TV帧慢修正窗口指针] = $圈误差
            $TV帧慢修正当前票数 = 0
        ENDIF
        IF $TV双分支锁定 == 1 and $TV双分支跟踪等待帧 == $TV等待帧 and $圈误差绝对 <= 1 and $消耗帧归一化绝对 <= $TV双分支相位阈值
            $TV帧本次修正 = 0
        ENDIF

    # 剩余帧窗口只接收目标Seed；非目标Seed的VBlank相位不参与持续偏差判断。
    IF $命中差索引 == 0
        $剩余帧慢修正窗口[$剩余帧慢修正窗口指针] = $剩余帧慢修正当前绝对相位
    ENDIF
    IF $剩余帧慢修正触发 == 1
        $剩余帧簇内 = 1
    ENDIF

    IF $Seed校准方案 == 0
        IF $Seed差绝对 <= 1
            $SeedMS本轮收敛 = 1
        ENDIF
    ELSE
        IF $Seed锁定启用 == 1 and $Seed命中保持启用 == 1
            $SeedMS本轮收敛 = 1
        ENDIF
    ENDIF
    IF $本轮剩余帧校准允许 == 1 and $消耗帧真绝对 <= $直接选择接近阈值
        $消耗帧本轮收敛 = 1
    ENDIF
    RETURN 1
ENDFUNC

FUNC 输出本轮校准决策
    PRINT 原因: Seed命中偏离路径可信窗，本轮表内命中会显示ｘ(修正仍下发)
    PRINT 原因: 消耗帧至少一轴偏离路径可信窗，本轮表内命中会显示ｘ(修正仍下发)
    PRINT 原因: Seed与消耗帧均偏离路径可信窗，本轮表内命中会显示ｘ(修正仍下发)
ENDFUNC
"""


class CalibrationTrustGateTests(unittest.TestCase):
    def test_untrusted_axes_do_not_write_windows_or_drive_controllers(self):
        configured = apply_calibration_trust_gates_text(legacy_fixture())

        self.assertIn(MARKER, configured)
        self.assertIn(
            "IF $本轮剩余帧校准允许 == 1 and $剩余帧本轮可信 == 1",
            configured,
        )
        self.assertIn("IF $Seed本轮可信 == 1\n        $投票忽略 = 投票设置Seed窗", configured)
        self.assertIn("IF $TV帧本轮可信 == 1\n        $投票忽略 = 投票设置TV帧窗", configured)
        self.assertIn("IF $Seed本轮可信 == 0\n        # 冻结本轴", configured)
        self.assertIn("IF $TV帧本轮可信 == 0\n            $TV帧簇内 = 0", configured)
        self.assertIn("IF $剩余帧本轮可信 == 0\n        $剩余帧簇内 = 0", configured)
        self.assertIn("$Seed本次修正索引 = 0", configured)
        self.assertIn("$TV帧本次修正 = 0", configured)
        self.assertIn("$本次相位修正 = 0", configured)
        self.assertNotIn("修正仍下发", configured)

    def test_slow_windows_and_convergence_require_trusted_observations(self):
        configured = apply_calibration_trust_gates_text(legacy_fixture())

        self.assertIn(
            "IF $命中差索引 == 0 and $TV帧本轮可信 == 1",
            configured,
        )
        self.assertIn("ELIF $TV帧本轮可信 == 1", configured)
        self.assertIn(
            "IF $命中差索引 == 0 and $剩余帧本轮可信 == 1",
            configured,
        )
        self.assertIn("IF $Seed本轮可信 == 1 and $Seed差绝对 <= 1", configured)
        self.assertIn(
            "IF $消耗帧本轮可信 == 1 and $本轮剩余帧校准允许 == 1",
            configured,
        )

    def test_install_is_idempotent(self):
        once = apply_calibration_trust_gates_text(legacy_fixture())
        self.assertEqual(apply_calibration_trust_gates_text(once), once)

    def test_unknown_controller_shape_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "可信路径窗写入段"):
            apply_calibration_trust_gates_text(
                "FUNC 执行自动校准与等待更新(): INT\n    RETURN 1\nENDFUNC"
            )


if __name__ == "__main__":
    unittest.main()
