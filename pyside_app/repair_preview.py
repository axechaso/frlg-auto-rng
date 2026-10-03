"""User-started capture owner for label repair, sharing the existing MJPEG API."""
import socket
import uuid
from PySide6.QtCore import QObject, QProcess, QTimer
from automation.easycon118 import prepare_compat_runner


class RepairPreview(QObject):
    def __init__(self, accessories):
        super().__init__(accessories)
        self.a, self.w = accessories, accessories.w
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(lambda: self.process.readAllStandardOutput())
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(lambda _error: self.w.set_status("修复共享预览未启动："+self.process.errorString()))
        self.url = ""
        self.waits = 0
        self.request = None

    def start(self):
        if self.w.running or self.w.job:
            raise ValueError("运行/设备任务尚未结束，请等待安全退出")
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return
        device = self.w.fields["video"].currentData()
        if device is None:
            raise ValueError("请先检测并选择采集卡")
        runner = prepare_compat_runner(self.w.paths.ezcon)
        if self.a.monitor is None:
            from .manual import MonitorWindow
            self.a.monitor = MonitorWindow(self.w)
        self.a.monitor.stop_capture()
        self.request = (runner,device)
        self.waits = 0
        self._start_when_released()

    def _start_when_released(self):
        if self.request is None or self.w.closing:
            return
        self.a.monitor.old_readers = [r for r in self.a.monitor.old_readers if r.thread.is_alive()]
        if self.a.monitor.old_readers:
            self.waits += 1
            if self.waits >= 40:
                self.request = None
                self.w.set_status("原监视通道仍在释放；没有另开采集卡，请稍后重试。")
                return
            QTimer.singleShot(100,self._start_when_released)
            return
        runner,device = self.request
        self.request = None
        directory = self.w.paths.output / f"label-preview-{uuid.uuid4().hex}"
        directory.mkdir(parents=True,exist_ok=True)
        script = directory / "preview.ecs"
        # Mock port has no physical controller. The ECS only keeps the existing
        # native preview service alive; there are no game input instructions.
        script.write_text('PRINT "标签修复共享预览"\nWAIT 3600000\n',encoding="utf-8")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0))
            port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}/mjpeg"
        self.process.setWorkingDirectory(str(directory))
        self.process.start(str(runner),["run",str(script),"--port","mock","--device",str(device),
            "--videotype","DSHOW","--preview-port",str(port),"--preview-video"])
        self.a.monitor.show()
        self.a.monitor.restart()
        self.w.set_status("修复共享预览：仅采集画面，模拟串口；测试复用此通道。")

    def stop(self):
        self.request = None
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self.url = ""
            return True
        if self.a.monitor:
            self.a.monitor.stop_capture()
        self.url = ""
        self.process.terminate()
        # Only this owned process can be killed after a bounded grace period.
        QTimer.singleShot(1500,self._kill_if_still_running)
        return False

    def _kill_if_still_running(self):
        if not self.url and self.process.state()!=QProcess.ProcessState.NotRunning:
            self.process.kill()

    def _finished(self,*_):
        self.url = ""
        if self.a.monitor and self.a.monitor.reader and isinstance(self.a.monitor.reader.source,str):
            self.a.monitor.stop_capture()
