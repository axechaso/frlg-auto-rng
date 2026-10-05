"""Offline Qt guide screenshots at the requested sizes and process DPI scale."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtCore import QTimer,QEventLoop
from PySide6.QtGui import QFont,QFontDatabase
from PySide6.QtWidgets import QApplication
from pyside_app.migration import CompleteWindow
from pyside_app.services import AppPaths
from pyside_preview import NAV_ITEMS


def settle():
    loop=QEventLoop();QTimer.singleShot(50,loop.quit);loop.exec()


def main(output):
    output.mkdir(parents=True,exist_ok=True)
    app=QApplication.instance() or QApplication([])
    for name in ("msyh.ttc","segoeui.ttf"):
        font=Path("C:/Windows/Fonts")/name
        if font.is_file():
            assert QFontDatabase.addApplicationFont(str(font))>=0
    app.setFont(QFont("Microsoft YaHei UI",9))
    report=[]
    with tempfile.TemporaryDirectory(prefix="frlg-layout-") as temp:
        w=CompleteWindow(paths=AppPaths(user=Path(temp),output=Path(temp)/"runtime"),auto_detect=False)
        w.advanced_check.setChecked(True);w.show();settle()
        for width,height in ((1280,800),(1920,1080)):
            w.resize(width,height);settle()
            for advanced in (False, True):
                w.advanced_check.setChecked(advanced);settle()
                for flow in ("sid", "tid", "wild", "egg"):
                    w.select_page(flow);settle();w.page_guides.start_controls();settle()
                    for i in range(len(w.page_guides.active_steps)):
                        w.page_guides.index=i;w.page_guides.render();settle()
                        guide=w.page_guides.overlay
                        assert guide.isVisible()
                        assert w.stop_button.isVisible()
                        target=guide.spot.target
                        assert not target.isEmpty(), ("controls",flow,advanced,i)
                        assert not guide.geometry().intersects(target.translated(w.mapToGlobal(w.rect().topLeft()))), ("controls",flow,advanced,i)
                        step=w.page_guides.active_steps[i].step_id
                        if flow=="egg" and step in ("adaptive","calibration","startup"):
                            base=f"{width}x{height}-controls-{step}-advanced-{int(advanced)}"
                            w.grab().save(str(output/(base+".png")))
                            guide.grab().save(str(output/(base+"-card.png")))
                        report.append({"size":[width,height],"page":"controls","flow":flow,"advanced":advanced,"step":step,"anchor_visible":True,"stop_visible":True,"device_pixel_ratio":w.devicePixelRatioF()})
                    w.page_guides.minimize()
            w.advanced_check.setChecked(True);settle()
            for page,_,_ in NAV_ITEMS:
                w.select_page(page);settle();w.page_guides.start(page,restart=True);settle()
                guide=w.page_guides.overlay
                for i in range(len(w.page_guides.active_steps)):
                    w.page_guides.index=i;w.page_guides.render();settle()
                    assert guide.isVisible()
                    assert w.stop_button.isVisible()
                    target=guide.spot.target
                    if not target.isEmpty():
                        assert not guide.geometry().intersects(target.translated(w.mapToGlobal(w.rect().topLeft()))), (page,i)
                    if i==0 or i==len(w.page_guides.active_steps)-1 or w.page_guides.active_steps[i].step_id=="seed_modes":
                        base=f"{width}x{height}-{page}-{i}"
                        w.grab().save(str(output/(base+".png")))
                        guide.grab().save(str(output/(base+"-card.png")))
                    report.append({"size":[width,height],"page":page,"step":w.page_guides.active_steps[i].step_id,"anchor_visible":not target.isEmpty(),"stop_visible":True,"device_pixel_ratio":w.devicePixelRatioF()})
                w.page_guides.minimize()
            w.select_page("wild");settle()
            for page,dialog in (("profile",w.profile_dialog),("common",w.settings_dialog),("advanced",w.advanced_dialog)):
                dialog.show();settle();w.page_guides.start(page);settle()
                for i in range(len(w.page_guides.active_steps)):
                    w.page_guides.index=i;w.page_guides.render();settle()
                    guide=w.page_guides.overlay
                    assert guide.isVisible()
                    target=guide.spot.target
                    assert not target.isEmpty(), (page,i)
                    assert not guide.geometry().intersects(target.translated(dialog.mapToGlobal(dialog.rect().topLeft()))), (page,i)
                    step=w.page_guides.active_steps[i].step_id
                    if i==0 or step in ("entry","parity","output_log"):
                        dialog.grab().save(str(output/f"{width}x{height}-{page}-{step}.png"))
                        guide.grab().save(str(output/f"{width}x{height}-{page}-{step}-card.png"))
                    report.append({"size":[width,height],"page":page,"step":step,"anchor_visible":True,"device_pixel_ratio":dialog.devicePixelRatioF()})
                w.page_guides.minimize();dialog.hide()
        w.close()
        for _ in range(100):
            if not w.history_controller.busy:break
            settle()
        w.close();app.processEvents()
    (output/"layout-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Checked {len(report)} page steps at DPI scale {os.environ.get('QT_SCALE_FACTOR','1')}")


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True)
    main(parser.parse_args().output)
