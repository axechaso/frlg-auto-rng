"""Generate a deterministic SID route matrix and format with real 1.6.4-a."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from automation.easycon118 import EasyCon118Options,write_configured_project,inspect_script_corpus,validate_generated_project_consistency
from automation.planner import search_best_plan
from automation.target_verification import TargetVerificationSpec,validate_injected_target_verification
from automation.sid_traversal_policy import validate_traversal_request
from tests.test_auto_planner import request,target,route


def main(args):
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    version=subprocess.run([str(args.ezcon),"--version"],capture_output=True,text=True,encoding="utf-8",timeout=20)
    assert version.returncode==0 and "1.6.4-a+9c86137" in version.stdout
    rows=[]
    for name in ("NS火叶全自动一键乱数2.0.ecs","NS火叶全自动一键乱数2.0-时间轴.ecs"):
        for kind in ("wild", "starter-en", "starter-jp"):
            r=request(seed_mode=6,max_advances=200000)
            t=target("12345678",(31,)*6,pid="89ABCDEF")
            if kind.startswith("starter"):
                r=replace(r,method="Static 1",category="Starter",location="Starter",pokemon="Bulbasaur")
                t=replace(t,method="Static 1",pokemon="Bulbasaur",level=5)
            mode = 0 if kind == "starter-jp" else 6
            if kind == "starter-jp":
                r=replace(r,game="fr_jpn_nx",seed_mode=mode)
            options=EasyCon118Options(nx_model=1,japanese_starter=kind=="starter-jp")
            validate_traversal_request(r,options,name)
            plan=search_best_plan(r,target_search=lambda **_: [t],seed_search=lambda **_: [route("9C76",100020,mode=mode)]).plan
            spec=TargetVerificationSpec("format-run","format-attempt",plan.initial_seed.seed,plan.initial_seed.advances,plan.species_id,r.method,t.pid)
            directory=output/(name.removesuffix(".ecs")+"-"+kind)
            project=write_configured_project(args.source,directory,plan,options,template_name=name,target_verification=spec)
            validate_generated_project_consistency(project,plan,options,template_name=name)
            validate_injected_target_verification(project.read_text(encoding="utf-8"),spec)
            formatted=directory/"format-result.ecs"
            result=subprocess.run([str(args.ezcon),"format",str(project),"-o",str(formatted)],cwd=directory,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=60)
            (directory/"format.log").write_text(result.stdout+result.stderr,encoding="utf-8")
            rows.append({"entry":name,"route":kind,"format_exit":result.returncode,"sha256":hashlib.sha256(project.read_bytes()).hexdigest(),"injection":"V2","fixture":"deterministic offline plan; no device or RNG hit claim"})
            assert result.returncode==0, result.stdout+result.stderr
    rejected=False
    try:
        validate_traversal_request(replace(r,category="Gift",location="Gift",pokemon="Eevee"),options,name)
    except ValueError:
        rejected=True
    assert rejected
    report={"runtime":version.stdout.strip(),"scripts":inspect_script_corpus(args.source),"matrix":rows,"gift_rejected":rejected}
    (output/"matrix.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Real 1.6.4-a format accepted {len(rows)} generated projects; Gift rejected")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",type=Path,default=ROOT/"local_assets"/"easycon118")
    parser.add_argument("--ezcon",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    main(parser.parse_args())
