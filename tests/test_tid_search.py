"""Replay the generated ECS search functions without sending device inputs."""
import ast
from dataclasses import asdict, replace
import io
import json
from itertools import product
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock, patch

from automation.tid_checkpoint import (
    SEARCH_STATE_VARIABLES, CHECKPOINT_V3_PREFIX, fixed_frame,
    instrument_tid_checkpoint, parse_checkpoint, validate_checkpoint,
)
from automation.tid_rng137 import TidRngRequest, configure_tid_template_text
from automation.tid_search import function, parse_target_tids, progress_supported
from automation.tid_search_policy import POLICY_STATE_VARIABLES
from automation.tid_starter_save import DEFAULT_TID_STARTER_SAVE_SOURCE, split_tid_modules


class Machine:
    """Execute actual generated arithmetic and control flow, with bounded loops."""
    def __init__(self, source):
        self.source = source
        self.state = {name: 0 for name in re.findall(r"\$([\w\u0080-\uffff]+)", source)}
        self.compiled = {}
        self.expressions = {}
        self.calls = []

    def value(self, expr):
        if expr not in self.expressions:
            self.expressions[expr] = ast.parse(re.sub(r"\$([\w\u0080-\uffff]+)", r"v_\1", expr), mode="eval")
        tree = self.expressions[expr]
        def visit(n):
            if isinstance(n, ast.Expression): return visit(n.body)
            if isinstance(n, ast.Constant): return n.value
            if isinstance(n, ast.Name): return self.state[n.id.removeprefix("v_")]
            if isinstance(n, ast.UnaryOp): return -visit(n.operand)
            if isinstance(n, ast.BinOp):
                a, b = visit(n.left), visit(n.right)
                quotient = lambda: (abs(a) // abs(b)) * (-1 if (a < 0) != (b < 0) else 1)
                for kind, op in ((ast.Add, lambda: a+b), (ast.Sub, lambda: a-b), (ast.Mult, lambda: a*b),
                                 (ast.Div, quotient), (ast.Mod, lambda: a-quotient()*b),
                                 (ast.RShift, lambda: a>>b), (ast.BitAnd, lambda: a&b)):
                    if isinstance(n.op, kind): return op()
            if isinstance(n, ast.Compare):
                a, b = visit(n.left), visit(n.comparators[0])
                return {ast.Eq: a == b, ast.NotEq: a != b, ast.Lt: a < b,
                        ast.LtE: a <= b, ast.Gt: a > b, ast.GtE: a >= b}[type(n.ops[0])]
            if isinstance(n, ast.BoolOp):
                return (all if isinstance(n.op, ast.And) else any)(visit(v) for v in n.values)
            if isinstance(n, ast.Call):
                if n.func.id == "RAND": return 0
                args = [visit(v) for v in n.args]
                return self.call(n.func.id, args)
            raise AssertionError(ast.dump(n))
        return visit(tree)

    def call(self, name, args=()):
        self.calls.append(name)
        if name not in self.compiled:
            text = function(self.source, name)
            header, *body = text.splitlines()
            params = re.findall(r"\$([\w\u0080-\uffff]+)", header)
            code = ["def run():"]
            indent = 1
            for raw in body[:-1]:
                line = raw.strip().split("#", 1)[0].strip()
                if not line: continue
                if line in ("ENDIF", "NEXT"):
                    indent -= 1
                    continue
                if line == "ELSE" or line.startswith("ELIF "):
                    indent -= 1
                converted = "pass"
                if line.startswith("IF "): converted = f"if value({line[3:]!r}):"
                elif line.startswith("ELIF "): converted = f"elif value({line[5:]!r}):"
                elif line == "ELSE": converted = "else:"
                elif line == "FOR": converted = "for _step in range(100000):"
                elif line == "RETURN": converted = "return"
                elif line.startswith("RETURN "): converted = f"return value({line[7:]!r})"
                elif line == "BREAK": converted = "break"
                elif line.startswith("CALL "): converted = f"call({line[5:]!r})"
                elif line.startswith("$"):
                    m = re.fullmatch(r"\$([^\s]+)\s*(=|\+=|-=|\*=|/=|%=)\s*(.*)", line)
                    if not m: raise AssertionError(line)
                    key, op, expr = m.groups()
                    if op != "=": expr = f"${key} {op[0]} ({expr})"
                    converted = f"state[{key!r}] = value({expr!r})"
                elif not line.startswith("PRINT "):
                    converted = f"raise AssertionError({'Hardware/wait executed in search test: ' + line!r})"
                code.append("    " * indent + converted)
                if converted.endswith(":"): indent += 1
            namespace = {"value": self.value, "call": self.call, "state": self.state}
            exec("\n".join(code), namespace)
            self.compiled[name] = (params, namespace["run"])
        params, run = self.compiled[name]
        old = {key: self.state.get(key) for key in params}
        self.state.update(zip(params, args))
        try: return run()
        finally: self.state.update(old)


@unittest.skipUnless(DEFAULT_TID_STARTER_SAVE_SOURCE.is_file(), "requires audited TID template")
class TidSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = DEFAULT_TID_STARTER_SAVE_SOURCE.read_text(encoding="utf-8-sig")

    def setup_machine(self, request, *, offset=24):
        source = configure_tid_template_text(self.template, request)
        m = Machine(source)
        m.state.update({v[1:]: -1 if k.startswith("H") and k.endswith("_TARGET") else 0
                        for k,v in POLICY_STATE_VARIABLES.items()})
        p = "EN" if request.language == "英文" else "JP"
        for key, value in request.to_user_values().items():
            if key.startswith("$"): m.state[key[1:]] = value
        m.state.update({p+"_TARGET_TID": request.target_tid, p+"_TARGET_SID": request.target_sid,
                        p+"_F1帧基准毫秒": 22050, p+"_F2帧基准毫秒": 16750,
                        "英文版SID_ADV补偿": 490 if p == "EN" else 380,
                        "OP固定": (30550 if p == "EN" else 30600) + request.op_correction + (0 if request.nx_model == 1 else -750)})
        m.state["F2脚本固定延迟"] += request.select_correction * 600
        if request.mode == 0:
            for axis, floor in (("F1", 22050), ("F2", 16750)):
                padding = max(0, floor - m.state[axis+"脚本固定延迟"])
                m.state[axis+"脚本固定延迟补偿"] = padding
                m.state[axis+"脚本固定延迟"] += padding
        m.call(p+"_计算脚本固定帧")
        m.call(p+"_规范搜索范围")
        if request.mode == 1:
            m.call(p+"_初始化乱数搜索")
        else:
            for axis in ("OP", "F1", "F2"):
                m.state[axis] = offset
                m.state[axis+"起点补偿"] = max(0, m.state[axis+"起点"] - m.state[axis+"脚本固定帧"])
            m.call(p+"_清空窗口")
        m.call(p+"_计算操作延迟")
        return m, p, source

    def test_distinct_near_results_trigger_same_target_and_keep_exact_timing(self):
        for language, model, select in product(("英文", "日文"), (1, 2), (0, 1, 5)):
            request = TidRngRequest(language=language, nx_model=model, mode=0, auto_rng=True,
                player_name="Alxe" if language == "英文" else "レット゛", target_tid=33333,
                additional_target_tids=(0,), sid_random=True, select_correction=select)
            m, p, _ = self.setup_machine(request)
            frames = tuple(m.state[a+"总帧"] for a in ("OP", "F1", "F2"))
            times = tuple(m.state[a+"ms"] + m.state[a+"脚本固定延迟补偿"] for a in ("F1", "F2"))
            for i, tid in enumerate((65530, 2, 5), 1):
                m.state.update({"ID": tid, f"Slot{i}": tid, "denoise_try_count": i})
                m.call(p+"_检测目标区域")
                self.assertEqual(m.state["ID_RNG"], int(i == 3))
            self.assertEqual(m.state[p+"_TARGET_TID"], 0)
            self.assertEqual(m.state["denoise_try_count"], 0)
            self.assertEqual(m.state["denoise_hit_count"], 0)
            self.assertEqual(frames, tuple(m.state[a+"总帧"] for a in ("OP", "F1", "F2")))
            self.assertEqual(times, tuple(m.state[a+"ms"] for a in ("F1", "F2")))
            self.assertEqual(tuple(m.state[a+"_RNG_Max_Range"] for a in ("OP", "F1", "F2")), (20,20,10))
            self.assertEqual(m.state["OP固定"], (30550 if p == "EN" else 30600) + (0 if model == 1 else -750))
            self.assertTrue(all(m.state[f"Slot{i}"] == -1 for i in range(1,11)))

    def test_targets_do_not_share_votes_and_windows_reset(self):
        request = TidRngRequest(mode=0, auto_rng=True, additional_target_tids=(33333,), sid_random=True)
        m,p,_ = self.setup_machine(request)
        for i,tid in enumerate((5,33330,33325),1):
            m.state.update({"ID":tid, f"Slot{i}":tid, "denoise_try_count":i})
            m.call(p+"_检测目标区域")
        self.assertEqual(m.state["ID_RNG"],0)

        self.assertEqual(m.state["TID区域次数"],2)
        m.state["denoise_hit_count"] = 2
        m.call(p+"_穷举模式偏移运算")
        self.assertEqual(m.state["denoise_try_count"],3)
        m.call(p+"_清空窗口")
        m.state.update({"ID":33334,"Slot1":33334,"denoise_try_count":1})
        m.call(p+"_检测目标区域")
        self.assertEqual(m.state["TID区域次数"],1)
        self.assertEqual(m.state["ID_RNG"],0)

    def test_extension_preserves_timing_ocr_and_bridge_helpers(self):
        for language in ("英文", "日文"):
            p = "EN" if language == "英文" else "JP"
            request = TidRngRequest(language=language, player_name="Alxe" if p == "EN" else "レット゛",
                                    mode=0,auto_rng=True,additional_target_tids=(33333,))
            source=configure_tid_template_text(self.template,request)
            allowed={p+"_"+name for name in ("匹配","计算穷举候选距离","穷举模式偏移运算","乱数模式操作延迟校验",
                "穷举推进到下一个搜索点", "乱数模式偏移运算", "乱数定位到当前壳层下一个有效组合", "乱数推进到下一个壳层组合")}
            for name in re.findall(r"(?m)^FUNC ([^\s(]+)",self.template):
                if name not in allowed:
                    self.assertEqual(function(source,name),function(self.template,name),name)

    def test_multiple_targets_use_nearest_ring_distance_and_match_exactly(self):
        request = TidRngRequest(mode=0, target_tid=11111, additional_target_tids=(0,33333,65535),
                                include_65535=False, sid_random=True)
        for language in ("英文", "日文"):
            m,p,_=self.setup_machine(replace(request, language=language, player_name="Alxe" if language=="英文" else "レット゛"))
            for tid, target, distance in ((65534,65535,1),(1,0,1),(33330,33333,3),(11111,11111,0)):
                m.state["ID"]=tid
                m.call(p+"_计算穷举候选距离")
                self.assertEqual((m.state["targetID"],m.state["AbsDelta"]),(target,distance))
            for tid in request.exhaustive_targets:
                m.state["ID"]=tid
                m.call(p+"_匹配")
                self.assertEqual(m.state["is_match"],1)

    def test_radius_clamping_and_centers_make_every_search_point_executable(self):
        for mode in (0,1):
            request=TidRngRequest(mode=mode,sid_random=True,op_rng_range=9999,f1_rng_range=-2,f2_rng_range=11,
                op_max_range=-1,f1_max_range=5,f2_max_range=7,op_target_frame=0)
            m,p,_=self.setup_machine(request, offset=0)
            self.assertEqual(tuple(m.state[a+"_Max_Range"] for a in ("OP","F1","F2")), (9998,0,10) if mode else (0,4,6))
            if mode:
                self.assertEqual(m.state["OP目标帧"],m.state["OP脚本固定帧"])
                self.assertEqual(m.state["OP_RNG_Min_Range"],0)
                self.assertGreaterEqual(m.state["OPms"],0)
            self.assertNotIn("搜索范围过大",function(m.source,p+"_乱数模式操作延迟校验"))

    def state(self,m,p):
        return {key:m.state[(f"${p}_TARGET_TID" if key=="TARGET" else variable)[1:]]
                for key,variable in SEARCH_STATE_VARIABLES.items()}

    def test_rng_shell_checkpoint_roundtrip_and_next_point(self):
        request=TidRngRequest(sid_random=True,op_rng_range=4,f1_rng_range=2,f2_rng_range=0)
        m,p,source=self.setup_machine(request)
        seen=set()
        for _ in range(15):
            state=self.state(m,p)
            validate_checkpoint(state,request)
            line=CHECKPOINT_V3_PREFIX+"|".join(f"{k}={v}" for k,v in state.items())+"|END=1"
            self.assertEqual(parse_checkpoint(line,request),state)
            seen.add((state["OP"],state["F1"],state["F2"]))
            resumed=instrument_tid_checkpoint(source,request,state)
            restore=resumed.split("# TID_CHECKPOINT_BEGIN\n",1)[1].split("# TID_CHECKPOINT_END",1)[0]
            copy=Machine(source+"\nFUNC RESTORE\n"+restore+"\nENDFUNC\n")
            copy.state.update(m.state)
            copy.call("RESTORE")
            m.call(p+"_乱数推进到下一个壳层组合")
            copy.call(p+"_乱数推进到下一个壳层组合")
            self.assertEqual(self.state(m,p),self.state(copy,p))
        self.assertEqual(len(seen),15)

    def test_switched_checkpoint_restores_target_centers_and_timing(self):
        request=TidRngRequest(mode=0, auto_rng=True, additional_target_tids=(33333,),sid_random=True)
        m,p,source=self.setup_machine(request)
        m.state["TID区域目标"]=33333
        m.call(p+"_自动转乱数")
        m.call(p+"_乱数推进到下一个壳层组合")
        state=self.state(m,p)
        validate_checkpoint(state,request)
        generated=instrument_tid_checkpoint(source,request,state)
        restore=generated.split("# TID_CHECKPOINT_BEGIN\n",1)[1].split("# TID_CHECKPOINT_END",1)[0]
        fresh,_,_=self.setup_machine(request)
        fresh.source += "\nFUNC RESTORE\n"+restore+"\nENDFUNC\n"
        fresh.call("RESTORE")
        fresh.call(p+"_计算操作延迟")
        m.call(p+"_计算操作延迟")
        self.assertEqual(self.state(fresh,p),state)
        for axis in ("OP","F1","F2"):
            self.assertEqual(fresh.state[axis+"ms"],m.state[axis+"ms"])
        for key,value in (("TARGET",12345),("OP_CENTER",1),("OP_RANGE",22),("OP_POS",500),("RADIUS",10)):
            with self.assertRaises(ValueError): validate_checkpoint({**state,key:value},request)

    def test_worker_rng_progress_and_sid_retries_use_separate_scripts(self):
        from automation.easycon118 import EasyConRuntimeCheck
        from automation.tid_checkpoint import DONE_MARKER
        from automation.tid_starter_flow import TidStarterFlowRequest
        from automation.tid_starter_save import set_starter_save_sid_correction
        from run_tid_starter_flow import FlowRunner, run_tid_plan, STARTER_SHINY_MARKER, STARTER_SID_MISS_MARKER
        from tid_session import progress_context, read_progress, write_json_atomic, TidProgressSession
        for is_flow in (False,True):
            request=TidRngRequest(op_rng_range=20,include_65535=False)
            flow_request=TidStarterFlowRequest(request,"火红","妙蛙种子")
            m,p,source=self.setup_machine(request)
            state=self.state(m,p)
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp)
                id_dir=root/"01_id" if is_flow else root
                (id_dir/"ImgLabel").mkdir(parents=True)
                (id_dir/"main.ecs").write_text(source,encoding="utf-8")
                payload=asdict(flow_request)
                payload["tid_request"]=request.to_dict()
                payload["starter_seed_calibration_scheme"]=0
                write_json_atomic(id_dir/"plan.json",{"tid_request":request.to_dict(),"source_manifest":{"scripts":{"英文":{"sha256":"a"*64}}}})
                if is_flow:
                    write_json_atomic(root/"flow_plan.json",{"request":payload,"deferred_identity":False,"sid_retry_corrections":[0,1]})
                    for index in (0,1):
                        (id_dir/f"main_attempt_{index:03d}.ecs").write_text(set_starter_save_sid_correction(source,"英文",index),encoding="utf-8")
                runner=FlowRunner(Path("unused"),port="COM4",video_device=0,log=io.StringIO())
                started=[]
                def stage(number,name,path,**kwargs):
                    if number==1:
                        self.assertIsNotNone(runner.progress)
                        actual=runner.id_main_override
                        self.assertIsNotNone(actual)
                        started.append(actual.read_text(encoding="utf-8"))
                        runner.progress.feed(CHECKPOINT_V3_PREFIX+"|".join(f"{k}={v}" for k,v in state.items())+"|END=1")
                        runner.progress.feed(DONE_MARKER)
                    else:
                        self.assertIsNone(runner.progress)
                        self.assertIsNone(runner.id_main_override)
                    if number==3:
                        runner.stage_lines=[STARTER_SID_MISS_MARKER if len(started)==1 else STARTER_SHINY_MARKER]
                    return 0
                runner.run_stage=Mock(side_effect=stage)
                with patch("run_tid_starter_flow.validate_tid_runtime",return_value=EasyConRuntimeCheck(True,(),())), patch("run_tid_starter_flow.update_starter_precalibration"):
                    result=run_tid_plan(runner,root,Path("unused"),is_flow=is_flow,progress_dir=root/"progress",game="火红")
                self.assertEqual(result,0)
                self.assertEqual(len(started),2 if is_flow else 1)
                if is_flow:
                    self.assertIn("$SID_ADV修正 = 1",started[1])
                    self.assertIn("$SID_ADV修正 = 0",started[0])
                context=progress_context(request,"火红","a"*64,payload if is_flow else None)
                self.assertEqual(read_progress(root/"progress",context)["status"],"completed")
                if is_flow:
                    next_request=replace(request,sid_advance_correction=1)
                    next_context=progress_context(next_request,"火红","a"*64,payload)
                    with TidProgressSession(root/"progress",next_context,resume=False) as paused:
                        paused.feed(CHECKPOINT_V3_PREFIX+"|".join(f"{k}={v}" for k,v in state.items())+"|END=1")
                    started.clear()
                    with patch("run_tid_starter_flow.validate_tid_runtime",return_value=EasyConRuntimeCheck(True,(),())), patch("run_tid_starter_flow.update_starter_precalibration"):
                        run_tid_plan(runner,root,Path("unused"),is_flow=True,progress_dir=root/"progress",game="火红")
                    self.assertEqual(len(started),1)
                    self.assertIn("$SID_ADV修正 = 1",started[0])
                    self.assertIn("TIDPROGRESS|RESUMED=1",started[0])

    def test_gui_collects_new_fields_and_refreshes_rng_and_switched_progress(self):
        import tkinter as tk
        from run_auto_rng_gui import AutoRngApp, TkinterDnD
        root=TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
        root.withdraw()
        try:
            with patch.object(AutoRngApp,"_install_tid_persistence"), patch.object(AutoRngApp,"check_devices"), patch("run_auto_rng_gui.resolve_tid_template",return_value=DEFAULT_TID_STARTER_SAVE_SOURCE):
                app=AutoRngApp(root)
                app.tid_mode_var.set("穷举模式")
                app.tid_language_var.set("英文")
                app.tid_name_var.set("Alxe")
                app.tid_target_var.set("00000")
                app.tid_auto_rng_var.set(True)
                app.tid_additional_targets_var.set("33333，65535")
                request=app.collect_tid_request()
                self.assertEqual(request.additional_target_tids,(33333,65535))
                self.assertEqual((request.auto_op_rng_range,request.auto_f1_rng_range,request.auto_f2_rng_range),(20,20,10))
                self.assertTrue(request.auto_rng)
                app.collect_tid_starter_flow_request=Mock(return_value=None)
                for switched in (False,True):
                    req=replace(request,sid_random=True) if switched else TidRngRequest(sid_random=True,op_rng_range=20)
                    m,p,_=self.setup_machine(req)
                    if switched:
                        m.state["TID区域目标"]=33333
                        m.call(p+"_自动转乱数")
                    state=self.state(m,p)
                    app.collect_tid_request=Mock(return_value=req)
                    with patch("run_auto_rng_gui.read_progress",return_value={"state":state,"status":"running"}):
                        app._refresh_tid_progress()
                    self.assertIn("乱数",app.tid_progress_status_var.get())
                    self.assertIn("当前壳层",app.tid_progress_status_var.get())
                    if switched: self.assertIn("33333",app.tid_progress_status_var.get())
        finally:
            root.destroy()


class TidSearchInputTests(unittest.TestCase):
    def test_progress_context_matches_gui_and_generated_flow_annotations(self):
        from tid_session import progress_context
        request=TidRngRequest(op_rng_range=20)
        bare={"tid_request":request.to_dict()}
        self.assertEqual(progress_context(request,"火红","a"*64,bare),
                         progress_context(request,"火红","a"*64,{**bare,"starter_seed_calibration_scheme":0}))

    def test_parse_multiple_targets_and_json_roundtrip(self):
        from automation.tid_calibration import tid_request_from_dict
        targets=parse_target_tids("00000，33333 65535,00000")
        self.assertEqual(targets,(0,33333,65535))
        request=TidRngRequest(additional_target_tids=targets)
        self.assertEqual(tid_request_from_dict(request.to_dict()).to_dict(),request.to_dict())
        for text in ("-1", "65536", "12.5", "１２３", "123456"):
            with self.assertRaises(ValueError): parse_target_tids(text)

    def test_progress_modes_and_auto_confirmation_bounds(self):
        self.assertFalse(progress_supported(TidRngRequest()))
        self.assertTrue(progress_supported(TidRngRequest(op_rng_range=2)))
        self.assertTrue(progress_supported(TidRngRequest(mode=0)))
        self.assertFalse(progress_supported(TidRngRequest(mode=0,calibration_check=True)))
        with self.assertRaises(ValueError): TidRngRequest(mode=0,auto_rng=True,denoise_try_window=2).validate()
        TidRngRequest(denoise_need_hit=1,denoise_try_window=1).validate()


if __name__ == "__main__":
    unittest.main()
