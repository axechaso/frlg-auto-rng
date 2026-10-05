import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from pyside_app.migration import CompleteWindow
from pyside_app.services import AppPaths
from pyside_preview import NAV_ITEMS
from assets.pyside_preview.guide_steps import GUIDES


class PageGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.paths=AppPaths(user=self.root,output=self.root/"runtime")
        self.w=CompleteWindow(paths=self.paths,auto_detect=False)
        self.w.show()
        self.app.processEvents()

    def tearDown(self):
        self.w.close()
        for _ in range(100):
            if not self.w.history_controller.busy: break
            QTest.qWait(10)
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_all_nav_pages_have_stable_steps_and_real_anchors_no_device_actions(self):
        guides=self.w.page_guides
        registry=guides.anchors()
        self.w.advanced_check.setChecked(True)
        with patch.object(self.w,"request_start") as start,patch.object(self.w,"search") as search,patch.object(self.w,"detect_devices") as detect:
            for page,title,_ in NAV_ITEMS:
                with self.subTest(page=page):
                    self.assertIn(page,GUIDES)
                    self.assertGreaterEqual(len(GUIDES[page]),4)
                    self.assertEqual(len({s.step_id for s in GUIDES[page]}),len(GUIDES[page]))
                    for step in GUIDES[page]: self.assertIn(step.anchor_id,registry)
                    self.w.select_page(page)
                    self.app.processEvents()
                    guides.start(page,restart=True)
                    self.assertEqual(guides.active_page,page)
                    for _ in range(len(guides.active_steps)-1): guides.move(1)
                    guides.move(-1)
                    step=guides.active_steps[guides.index].step_id
                    guides.minimize()
                    guides.start(page)
                    self.assertEqual(guides.active_steps[guides.index].step_id,step)
                    guides.opt_out()
                    self.assertTrue(guides.state["pages"][page]["opt_out"])
                    guides.start(page,restart=True)
                    self.assertEqual(guides.index,0)
                    guides.minimize()
            start.assert_not_called();search.assert_not_called();detect.assert_not_called()

    def test_shared_controls_guide_is_reachable_read_only_and_keeps_its_own_progress(self):
        guides = self.w.page_guides
        action = next(a for a in guides.menu.actions() if a.text() == "顶部功能与 Seed 模式")
        page = self.w.current_page
        before = self._mode_snapshot()
        with patch.object(self.w, "request_start") as start, patch.object(self.w, "search") as search, patch.object(self.w, "detect_devices") as detect:
            action.trigger()
            self.assertEqual(guides.active_page, "controls")
            self.assertEqual(guides.overlay.host, self.w)
            registry = guides.anchors()
            for index, step in enumerate(guides.active_steps):
                with self.subTest(step=step.step_id):
                    self.assertIn(step.anchor_id, registry)
                    self.assertTrue(registry[step.anchor_id].isVisible())
                    guides.index = index
                    guides.render()
                    self.assertTrue(guides.overlay.isVisible())
                    self.assertTrue(self.w.stop_button.isVisible())
            start.assert_not_called(); search.assert_not_called(); detect.assert_not_called()
        self.assertEqual(before, self._mode_snapshot())
        guides.index = 1
        guides.render()
        guides.minimize()
        guides.start_current()
        self.assertEqual(guides.active_page, page)
        guides.minimize()
        guides.start_controls()
        self.assertEqual(guides.active_steps[guides.index].step_id, "adaptive")
        state = json.loads((self.root / "guide_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["pages"]["controls"]["step_id"], "adaptive")
        self.assertIn(page, state["pages"])
        next(a for a in guides.menu.actions() if a.text() == "重新开始").trigger()
        self.assertEqual(guides.active_page, "controls")
        self.assertEqual(guides.index, 0)
        self.assertEqual(self.w.current_page, page)
        self.assertEqual(before, self._mode_snapshot())

    def test_shared_guide_reads_actual_switches_and_respects_seed_scope(self):
        guides = self.w.page_guides
        for mode in ("wild", "egg", "tid", "sid"):
            self.w.select_page(mode)
            self.app.processEvents()
            before = self._mode_snapshot()
            guides.start("controls", restart=True)
            guides.index = next(i for i,s in enumerate(guides.active_steps) if s.step_id == "calibration")
            guides.render()
            self.assertFalse(self.w.advanced_check.isChecked())
            self.assertEqual(before, self._mode_snapshot())
            state = guides.overlay.state.text()
            if mode == "tid":
                self.assertIn("实际校准固定为 0", state)
            elif mode == "sid":
                self.assertIn("SID 采集不使用", state)
            else:
                self.assertIn("当前不可修改", state)
                self.assertIn(self.w.fields["seed_calibration"].currentText(), state)
        guides.index = next(i for i,s in enumerate(guides.active_steps) if s.step_id == "adaptive")
        guides.render()
        self.assertIn("当前：关闭", guides.overlay.state.text())
        self.w.home_buffer_check.setChecked(True)
        guides.update_status()
        self.assertIn("当前：开启", guides.overlay.state.text())
        self.w.running = True
        guides.update_status()
        self.assertIn("参数暂时不能修改", guides.overlay.state.text())
        self.w.running = False

    def test_mode_explanations_do_not_require_enabling_a_business_option(self):
        guides = self.w.page_guides
        self.w.select_page("wild")
        self.app.processEvents()
        self.assertFalse(self.w.traversal_check.isChecked())
        self.assertFalse(self.w.item_check.isChecked())
        guides.start("wild", restart=True)
        self.assertTrue({"seed_modes", "item", "traversal", "capture"}.issubset({s.step_id for s in guides.active_steps}))
        self.assertFalse(self.w.traversal_check.isChecked())
        self.assertFalse(self.w.item_check.isChecked())

    def test_small_settings_guides_leave_each_highlighted_control_uncovered(self):
        self.w.select_page("wild")
        self.w.advanced_check.setChecked(True)
        self.app.processEvents()
        guides = self.w.page_guides
        for page, dialog in (("profile", self.w.profile_dialog), ("common", self.w.settings_dialog), ("advanced", self.w.advanced_dialog)):
            dialog.show()
            self.app.processEvents()
            guides.start(page, restart=True)
            for index, step in enumerate(guides.active_steps):
                with self.subTest(page=page, step=step.step_id):
                    guides.index = index
                    guides.render()
                    self.app.processEvents()
                    overlay = guides.overlay
                    overlay.reposition()
                    target = overlay.spot.target.translated(dialog.mapToGlobal(dialog.rect().topLeft()))
                    self.assertFalse(target.isEmpty())
                    self.assertFalse(overlay.geometry().intersects(target))
            guides.minimize()
            dialog.hide()

    def _mode_snapshot(self):
        fields = {}
        for name, widget in self.w.fields.items():
            if hasattr(widget, "currentIndex"):
                fields[name] = widget.currentIndex()
            elif hasattr(widget, "value"):
                fields[name] = widget.value()
            elif hasattr(widget, "text"):
                fields[name] = widget.text()
        flags = {name: getattr(self.w, name).isChecked() for name in (
            "advanced_check", "home_buffer_check", "precalibration_check", "label_supervision_check",
            "traversal_check", "item_check", "tid_flow_check", "tid_any_check", "tid_denoise_check",
            "tid_auto_rng_check", "tid_calibration_check", "tid_manual_delay",
        )}
        return fields, flags

    def test_progress_resume_corruption_and_unknown_steps_preserve_business_settings(self):
        guides=self.w.page_guides
        guides.start("sid");guides.move(1);guides.minimize()
        path=self.root/"guide_state.json"
        self.assertEqual(json.loads(path.read_text())["pages"]["sid"]["step_id"],"count")
        from pyside_app.page_guides import PageGuides
        second=PageGuides(self.w)
        second.start("sid")
        self.assertEqual(second.index,1)
        second.minimize()
        raw='{"broken":'
        path.write_text(raw,encoding="utf-8")
        corrupt=PageGuides(self.w)
        self.assertTrue(corrupt.error)
        corrupt.start("sid");corrupt.move(1);corrupt.minimize()
        self.assertEqual(path.read_text(encoding="utf-8"),raw)
        self.assertIsNone(self.w.job)
        self.assertFalse(self.w.running)

    def test_hidden_advanced_and_actual_device_state_are_honest(self):
        with patch("pyside_app.page_guides.QMessageBox.information"):
            self.w.page_guides.start("script_test")
        self.assertFalse(self.w.advanced_check.isChecked())
        self.w.page_guides.start("sid")
        self.w.page_guides.index=4
        self.w.page_guides.render()
        self.assertIn("尚未检测",self.w.page_guides.overlay.state.text())
        self.w.running=True
        self.w.page_guides.update_status()
        self.assertIn("参数暂时不能修改",self.w.page_guides.overlay.state.text())
        self.w.running=False

    def test_escape_closes_only_the_tutorial_and_keeps_stop_visible(self):
        self.w.page_guides.start("sid")
        overlay=self.w.page_guides.overlay
        self.assertTrue(self.w.stop_button.isVisible())
        with patch.object(self.w,"stop_run") as stop:
            QTest.keyClick(overlay,Qt.Key.Key_Escape)
            stop.assert_not_called()
        self.assertIsNone(self.w.page_guides.active_page)
        self.assertFalse(overlay.isVisible())


class GuideCopyTests(unittest.TestCase):
    def test_every_step_explains_its_purpose_and_a_concrete_action(self):
        for page, steps in GUIDES.items():
            for step in steps:
                with self.subTest(page=page, step=step.step_id):
                    self.assertTrue(step.body.startswith("作用："))
                    self.assertIn("\n\n操作：", step.body)
                    self.assertLessEqual(len(step.body), 320)
                    self.assertNotIn("不执行业务操作", step.body)
                    self.assertNotIn("终态证据", step.body)
                    self.assertNotIn("有界预览", step.title)

    def test_key_terms_and_safety_boundaries_use_plain_language(self):
        by_id = {page: {step.step_id: step for step in steps} for page, steps in GUIDES.items()}
        checks = (
            ("sid", "identity", "隐藏训练家编号"),
            ("sid", "individuals", "EV 就是努力值"),
            ("wild", "conditions", "个体值（IV）"),
            ("wild", "advance", "推进的步数"),
            ("wild", "traversal", "不会直接修改游戏存档里的 SID"),
            ("egg", "parents", "亲本 A 是第一只"),
            ("egg", "seed", "Held 是蛋生成的时机"),
            ("egg", "seed", "Pickup 是向 NPC 领取蛋的时机"),
            ("egg", "save", "都不是给游戏存档"),
            ("logs", "stop", "Esc 只收起本教程"),
            ("history_logs", "preview", "原文件没有被删减"),
            ("profile", "gift", "不会帮你在游戏里开启神秘礼物"),
            ("advanced", "windows", "倒推实际 Seed"),
            ("label", "negative", "不应该识别成功"),
        )
        for page, step, text in checks:
            with self.subTest(page=page, step=step):
                self.assertIn(text, by_id[page][step].body)
        self.assertIn("覆盖旧存档", by_id["tid"]["mode"].risk_note)

    def test_missing_controls_and_all_named_mode_choices_have_comparisons(self):
        by_id = {page: {step.step_id: step for step in steps} for page, steps in GUIDES.items()}
        required = {
            ("controls", "adaptive"): ("关闭", "开启", "连续 3 次", "唯一最高分", "至少 90", "不会降低"),
            ("controls", "calibration"): ("0“原始众数”", "1“锁定细调”", "2“命中保持”", "2 仅孵蛋", "固定 0"),
            ("controls", "startup"): ("0“HOME_BUFFER”", "1“固定 HOME”", "1500 ms", "3000 ms", "记录不混用"),
            ("controls", "seed_terms"): ("Seed 模式", "Seed 启动", "Seed 校准", "不同的事"),
            ("controls", "precalibration"): ("开启", "关闭", "完整命中", "默认开启"),
            ("controls", "protection"): ("关闭", "开启", "原始 EasyCon", "另管是否弹窗"),
            ("tid", "mode"): ("穷举模式", "乱数模式", "起点＋最大范围", "中心帧＋半径"),
            ("tid", "sid_mode"): ("目标 SID", "不乱数 SID", "固定 F3", "实际"),
            ("tid", "auto_rng"): ("不开", "开启", "回到穷举", "号码差"),
            ("tid", "game_settings"): ("MONO/STEREO", "HELP", "LR", "L=A", "A/START/L", "取名进入键 A/B"),
            ("tid", "timing"): ("自动回填", "手动编辑固定延迟"),
            ("tid", "continuation"): ("保留去噪", "关闭", "6V"),
            ("wild", "reachable"): ("自动选择", "手动指定", "精确", "等待最短", "筛选搜索"),
            ("wild", "seed_modes"): ("0/1", "2/3", "4/5", "6/7", "8/9", "HELP", "日版御三家", "模式 10"),
            ("wild", "capture"): ("关闭", "开启", "非目标闪光停止", "录像"),
            ("wild", "item"): ("普通流程", "道具乱数模式", "互斥"),
            ("egg", "seed_modes"): ("0/1", "2/3", "4/5", "6/7", "8/9", "自动选择"),
            ("egg", "start"): ("完整准备", "254 步"),
            ("egg", "compatibility"): ("20", "50", "70", "中文/英文/日文"),
            ("script_test", "file"): ("正式版", "时间轴版", "自选 ECS", "不替换参数"),
            ("script_test", "backend"): ("工具兼容运行器", "原始 EasyCon", "不提供"),
            ("common", "output_log"): ("精简日志", "完整调试日志", "匹配分数", "重新生成"),
            ("common", "updates"): ("自动", "GitHub", "Gitee", "不跨源"),
            ("advanced", "entry"): ("正式版", "时间轴版", "WAIT", "目标时刻", "自选 ECS"),
            ("advanced", "parity"): ("方案 1", "方案 0", "F1 加 1", "F2 减 1", "SID ADV"),
            ("advanced", "windows"): ("野生 / 定点", "波克比", "孵蛋", "不累加"),
        }
        for (page, step_id), terms in required.items():
            step = by_id[page][step_id]
            for term in terms:
                with self.subTest(page=page, step=step_id, term=term):
                    self.assertIn(term, step.title + step.body)

    def test_hover_help_agrees_with_guides_instead_of_old_manual_only_copy(self):
        from assets.pyside_preview.help_text import HELP_TEXT, FIELD_HELP
        self.assertEqual(FIELD_HELP["wild_seed_mode"], "seed_mode")
        self.assertIn("Seed 模式可选自动", HELP_TEXT["direct"][1])
        self.assertNotIn("必须手动", HELP_TEXT["direct"][1])
        self.assertIn("默认自动选择", HELP_TEXT["egg_seed"][1])
        self.assertIn("默认开启", HELP_TEXT["precalibration"][1])
        self.assertIn("连续 3 次", HELP_TEXT["adaptive"][1])
        for mode in ("0", "1", "2"):
            self.assertIn("Seed", HELP_TEXT[f"seed_calibration_{mode}"][1])
