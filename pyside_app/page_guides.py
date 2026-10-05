"""Read-only page tutorials with isolated, atomic per-page reading progress."""
import json
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QMenu, QScrollArea, QMessageBox
from assets.pyside_preview.guide_steps import GUIDES, GUIDE_VERSION
from tid_session import write_json_atomic
from .guide_overlay import GuideOverlay


class PageGuides:
    def __init__(self, window):
        self.w = window
        self.path = window.paths.user / "guide_state.json"
        self.state = {"schema":"frlg-page-guides/v1", "version":GUIDE_VERSION, "pages":{}}
        self.error = ""
        self.active_page = None
        self.active_steps = ()
        self.index = 0
        self.overlay = None
        self.child = None
        try:
            if self.path.exists():
                value = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(value, dict) or value.get("schema") != self.state["schema"] or type(value.get("version")) is not int or not isinstance(value.get("pages"), dict):
                    raise ValueError("引导进度格式无效")
                for page, record in value["pages"].items():
                    if not isinstance(record, dict) or not isinstance(record.get("step_id", ""), str) or type(record.get("opt_out", False)) is not bool:
                        raise ValueError("引导步骤格式无效")
                self.state["pages"] = value["pages"]
        except (OSError, ValueError, UnicodeError) as exc:
            self.error = f"引导进度读取失败，原文件保留：{exc}"
        self.menu = QMenu(window.guide_button)
        for title, callback in (("开始 / 继续", self.start_current), ("重新开始", self.restart_current), ("顶部功能与 Seed 模式", self.start_controls), ("引导目录与设置教程", self.directory)):
            self.menu.addAction(title, callback)
        window.guide_button.setMenu(self.menu)
        window.guide_hint.clicked.connect(self.start_current)
        window.guide_hint_close.clicked.connect(self.dismiss_hint)
        for page, dialog in (("profile", window.profile_dialog), ("common", window.settings_dialog), ("advanced", window.advanced_dialog)):
            button = QPushButton("本窗口引导（继续）", dialog)
            button.clicked.connect(lambda _checked=False, p=page: self.start(p))
            dialog.layout().addWidget(button)
        self.page_changed(window.current_page)

    def anchors(self):
        registry = dict(self.w.fields)
        for name in ("profile_chip", "profile_selector", "profile_mystery_gift", "qq_notification_button", "common_device_hint", "qq_guide_entry", "advanced_check", "advanced_scope", "home_buffer_check", "precalibration_check", "label_supervision_check", "sid_ack", "tid_flow_check", "tid_auto_rng_check", "traversal_check", "item_check", "record_shiny_video_check", "search_button", "start_button", "stop_button", "overview", "records_table", "log_view", "result_panel", "script_action_card", "label_incident_open", "history_table", "history_status", "history_log_view"):
            registry[name] = getattr(self.w, name)
        registry["sid_party"] = self.w.sid_party_widgets[0][0]
        registry["egg_parent_widgets"] = self.w.egg_parent_widgets[0][0]
        registry["tid_progress_card"] = self.w.tid_progress_status
        registry["frame_parity"] = self.w.fields["parity"]
        if self.child:
            if self.active_page == "label":
                for name in ("scene_confirm", "label_choice", "canvas", "same_button", "fresh_button", "negative_button", "apply_button", "manual_confirm_button"):
                    registry[name] = getattr(self.child, name)
            elif self.active_page == "profile":
                registry.update(profile_selector=self.child.list,profile_game=self.child.game,profile_mystery_gift=self.child.mystery_gift)
        return registry

    def _visible(self, step):
        return not step.visible_when or (step.visible_when == "traversal" and self.w.traversal_check.isChecked())

    def start_current(self):
        self.start(self.w.current_page)

    def start_controls(self):
        self.start("controls")

    def restart_current(self):
        self.start(self.active_page or self.w.current_page, restart=True, child=self.child if self.active_page else None)

    def start(self, page, *, restart=False, child=None):
        self.minimize()
        self.child = child
        if page == "script_test" and not self.w.advanced_check.isChecked():
            QMessageBox.information(self.w, "高级页引导", "请先在主窗口顶部打开“高级模式”，再从左侧进入“脚本测试”页。")
            return
        self.active_page = page
        self.active_steps = tuple(s for s in GUIDES[page] if self._visible(s))
        record = self.state["pages"].get(page, {})
        previous = record.get("step_id", "") if not restart else ""
        self.index = next((i for i,s in enumerate(self.active_steps) if s.step_id == previous), 0)
        if previous and not any(s.step_id == previous for s in self.active_steps):
            self.w.guide_hint.setText("教程内容有更新，已从当前适用的第一步开始；你的功能设置没有改变。")
        self.render()

    def render(self):
        current = self.active_steps[self.index]
        anchor = self.anchors().get(current.anchor_id)
        host = self.child or {"profile":self.w.profile_dialog,"common":self.w.settings_dialog,"advanced":self.w.advanced_dialog}.get(self.active_page,self.w)
        # Never open a settings window on the user's behalf.
        if not host.isVisible():
            self.w.guide_hint.setText("请先打开这个功能的设置窗口，再点里面的“本窗口引导”。")
            self.active_page = None
            return
        ancestor = anchor.parentWidget() if anchor else None
        while ancestor and ancestor is not host:
            if isinstance(ancestor, QScrollArea):
                ancestor.ensureWidgetVisible(anchor, 20, 20)
                break
            ancestor = ancestor.parentWidget()
        if self.overlay is None or self.overlay.host is not host:
            if self.overlay:
                self.overlay.deleteLater()
            self.overlay = GuideOverlay(self, host)
        self.overlay.present(current, anchor, self.index, len(self.active_steps), self.status(current, anchor))
        self.persist()

    def status(self, step, anchor):
        if self.w.running:
            return "脚本正在运行，参数暂时不能修改。要停止请点底部“停止 EasyCon”；Esc 只收起教程。"
        if anchor is None or not anchor.isVisible() or (self.overlay and anchor.window() is not self.overlay.host):
            return "这项在当前模式下没有显示。请先选择对应功能，或打开它的设置窗口，再看这一步。"
        if step.completion_check == "devices":
            return "已完成检测，请核对串口和采集卡，并确认监视画面正常。" if self.w.devices_checked else "尚未检测设备。请到主窗口顶部点“重新检测”，再选串口和采集卡；看教程不会自动连接。"
        if step.completion_check == "plan":
            prepared = getattr(self.w,"workflow",None) or self.w.prepared
            return "方案已生成。先按运行要求准备好游戏，再点“开始运行”。" if prepared else "还没有方案。请先点“搜索并生成方案”；教程的“下一步”不会生成脚本。"
        if step.completion_check == "scene":
            return "你已勾选现场确认，接下来检查标签；勾选不会改变游戏画面。" if self.child.scene_confirm.isChecked() else "先确认截图和游戏都在正确页面，再勾选现场确认；页面不对时不要制作标签。"
        if self.active_page == "controls":
            if step.step_id == "calibration":
                if self.w.input_mode == "tid":
                    return "TID 建档不使用此选项；接续御三家时实际校准固定为 0，不以此处显示值为准。"
                if self.w.input_mode == "sid":
                    return "SID 采集不使用这里的 Seed 校准；HOME_BUFFER 的低分自适应仍由独立开关控制。"
            if step.step_id == "startup" and self.w.input_mode in {"sid", "tid"}:
                return "这里只设置连续御三家等 2.0 流程的启动；TID 建档、SID 采集沿用各自启动操作。"
            if hasattr(anchor, "isChecked"):
                state = "开启" if anchor.isChecked() else "关闭"
                return f"当前：{state}。阅读教程不会切换开关；需要改动时请手动操作，生成脚本的选项要重新生成才生效。"
            if hasattr(anchor, "currentText"):
                edit = "可在空闲时手动修改" if anchor.isEnabled() else "当前不可修改；要手动选择需先开启高级模式，运行中仍不能修改"
                return f"当前显示：{anchor.currentText()}。{edit}。"
        if self.active_page == "wild":
            return f"已选：{self.w.fields['wild_method'].currentText()} / {self.w.fields['wild_category'].currentText()}。请照本次方案准备队伍、道具和站位。"
        if self.active_page == "egg":
            return f"当前选择：{self.w.fields['egg_start'].currentText()}。请确认游戏已做好对应准备，不确定时先完成完整准备。"
        return "“下一步”只翻到下一段说明，不会自动填写、保存或运行。"

    def update_status(self):
        if self.active_page and self.overlay:
            steps = tuple(s for s in GUIDES[self.active_page] if self._visible(s))
            if steps != self.active_steps:
                previous = self.active_steps[self.index].step_id
                self.active_steps = steps
                self.index = next((i for i,s in enumerate(steps) if s.step_id == previous),0)
                self.render()
                return
            step = self.active_steps[self.index]
            self.overlay.state.setText(self.status(step,self.anchors().get(step.anchor_id)))

    def move(self, delta):
        if delta > 0 and self.index == len(self.active_steps)-1:
            self.minimize()
            return
        self.index = max(0,min(len(self.active_steps)-1,self.index+delta))
        self.render()

    def persist(self):
        if not self.active_page or self.error:
            return
        record = self.state["pages"].setdefault(self.active_page,{})
        record["step_id"] = self.active_steps[self.index].step_id
        record.setdefault("opt_out",False)
        try:
            write_json_atomic(self.path,self.state)
        except (OSError,ValueError) as exc:
            self.w.guide_hint.setText(f"引导进度未保存：{exc}")

    def minimize(self):
        self.persist()
        if self.overlay:
            self.overlay.hide()
        self.active_page = None

    def opt_out(self):
        if self.active_page:
            self.state["pages"].setdefault(self.active_page,{})["opt_out"] = True
        self.minimize()
        self.page_changed(self.w.current_page)

    def dismiss_hint(self):
        self.state["pages"].setdefault(self.w.current_page,{})["opt_out"] = True
        self.w.guide_hint.hide()
        self.w.guide_hint_close.hide()
        if not self.error:
            try:
                write_json_atomic(self.path,self.state)
            except (OSError,ValueError):
                pass

    def page_changed(self, page):
        self.minimize()
        record = self.state["pages"].get(page,{})
        visible = not record.get("opt_out",False)
        self.w.guide_hint.setText(self.error or "不知道从哪开始？点这里看本页用法；顶部开关和 Seed 模式在“本页引导”菜单中")
        self.w.guide_hint.setVisible(visible)
        self.w.guide_hint_close.setVisible(visible)

    def directory(self):
        menu = QMenu(self.w.guide_button)
        menu.addAction("顶部功能与 Seed 模式", self.start_controls)
        for page, title, _ in __import__("pyside_preview").NAV_ITEMS:
            menu.addAction(title, lambda p=page: self.start(p) if p==self.w.current_page else self.explain_page(p))
        for page,title in (("profile","存档信息 / 管理"),("common","共通设置"),("advanced","高级设置"),("label","标签制作与修复")):
            menu.addAction(title, lambda p=page: self.explain_page(p))
        menu.addAction("QQ 通知：已有绑定教程", lambda: QMessageBox.information(self.w,"QQ 通知教程","点击主窗口“QQ 通知”，使用已有绑定教程。"))
        menu.exec(self.w.guide_button.mapToGlobal(self.w.guide_button.rect().bottomLeft()))

    def explain_page(self,page):
        message = "请先在主窗口顶部打开“高级模式”，再从左侧进入“脚本测试”页。" if page=="script_test" else "先从左侧打开想了解的页面；如果要看设置说明，先打开对应设置窗口，再点“本页引导”或“本窗口引导”。"
        QMessageBox.information(self.w,"功能引导",message)
