from __future__ import annotations

import copy
from datetime import date, timedelta
import csv
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from backtester import certify_backtest_result as cert
from backtester import future_leak_certification as leak

SHA_A = "1" * 40
SHA_B = "2" * 40
SHA_C = "3" * 40
H64_A = "a" * 64
H64_B = "b" * 64


def write_gzip_csv(path: Path, fieldnames, rows):
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def create_dataset(root: Path, *, unknown=False, incomplete_terminal=0, unresolved_actions=0,
                   metadata_after=0, future_metadata=0, many_sessions=False):
    root.mkdir(parents=True, exist_ok=True)
    if many_sessions:
        sessions=[]
        d=date(2006,1,2)
        while len(sessions)<170:
            if d.weekday()<5:
                sessions.append(d.isoformat())
            d += timedelta(days=1)
    else:
        sessions=["2006-01-03","2006-01-04","2006-01-05"]
    obs=[]
    for i,s in enumerate(sessions):
        for sid,ticker,stype,base in [("1","AAA","" if unknown else "common",100.0),("2","BBB","non_common",50.0)]:
            obs.append({"security_id":sid,"ticker":ticker,"session":s,"security_type":stype,
                        "listing_active":"1","tradeable":"1","signal_close":str(base+i*0.1),
                        "raw_close":str(base+i*0.1),"raw_open":str(base+i*0.1-0.05),
                        "reported_volume":"1000000","ff12":"TECH"})
    write_gzip_csv(root/"observations-2006.csv.gz", list(obs[0]), obs)
    write_gzip_csv(root/"metadata-timeline.csv.gz", ["security_id","ticker","effective_session"], [
        {"security_id":"1","ticker":"AAA","effective_session":"2006-01-03"},
        {"security_id":"2","ticker":"BBB","effective_session":"2006-01-03"}])
    write_gzip_csv(root/"actions.csv.gz", ["session","security_id","action"], [])
    write_gzip_csv(root/"terminal-events.csv.gz", ["session","security_id","kind"], [])
    with (root/"session-hashes.csv").open("w",encoding="utf-8",newline="") as h:
        w=csv.DictWriter(h,fieldnames=["session","hash"]); w.writeheader()
        for s in sessions: w.writerow({"session":s,"hash":hashlib.sha256(s.encode()).hexdigest()})
    write_gzip_csv(root/"cash.csv.gz", ["session","gap_factor","intraday_factor"], [{"session":s,"gap_factor":"1","intraday_factor":"1"} for s in sessions])
    write_gzip_csv(root/"benchmark.csv.gz", ["session","level","close_to_close_factor"], [{"session":s,"level":str(1+i/1000),"close_to_close_factor":"1.001"} for i,s in enumerate(sessions)])
    members={}
    for p in sorted(root.iterdir()):
        if p.name!="manifest.json": members[p.name]={"sha256":cert.sha256_file(p)}
    manifest={"schema":"backtester.canonical-pit-dataset/2","status":"PASS","dataset_id":"fixture",
              "dataset_hash":H64_A,"reconstruction_code_sha":SHA_C,
              "window":{"warmup_start":sessions[0],"measurement_start":sessions[0],"end":sessions[-1]},
              "members":members,"counts":{"observation_rows":len(obs),"session_count":len(sessions),
              "security_count":2,"unknown_security_type_observations":len(sessions) if unknown else 0,
              "unresolved_corporate_actions":unresolved_actions,"incomplete_terminal_terms":incomplete_terminal},
              "identity_audit":{"blocking_identity_conflicts":0},
              "causal_metadata_audit":{"metadata_after_decision_consumptions":metadata_after,
              "future_metadata_authority_violations":future_metadata}}
    (root/"manifest.json").write_text(json.dumps(manifest,sort_keys=True)+"\n")
    pointer={"schema":cert.POINTER_SCHEMA,"status":"PASS","dataset_id":"fixture","dataset_hash":H64_A,
             "manifest_sha256":cert.sha256_file(root/"manifest.json"),"reconstruction_code_sha":SHA_C,
             "package":"ghcr.io/flabber1835/stocker-canonical-pit@sha256:"+"d"*64,
             "source_run_id":"1","source_run_url":"https://github.com/flabber1835/stocker/actions/runs/1",
             "window":manifest["window"],"counts":manifest["counts"]}
    pointer_path=root.parent/"pointer.json"; pointer_path.write_text(json.dumps(pointer,sort_keys=True)+"\n")
    return pointer_path


def identity(pointer_path: Path, *, mode="research", source=SHA_A, strategy=SHA_A, params=None):
    p=cert.verify_pointer(pointer_path)
    return cert.build_identity(mode=mode,source_sha=source,strategy_sha=strategy,workflow_sha=source,
        dataset_hash=p["dataset_hash"],warmup_start=p["window"]["warmup_start"],
        measurement_start=p["window"]["measurement_start"],end=p["window"]["end"],
        parameters=params or {"mode":"fullpit"},source_closure_sha256=H64_B,runtime_identity_sha256="c"*64)


def replay_evidence(root: Path, idv, *, current_tickers=False, meta_after=0, splits=0, held=0, checkpoint=cert.PASS):
    root.mkdir(parents=True,exist_ok=True)
    (root/"summary.json").write_text(json.dumps({"status":"PASS","canonical_pit_dataset_hash":idv["dataset_hash"],"backtester_sha":idv["source_sha"]}))
    (root/"metadata_authority_audit.json").write_text(json.dumps({
        "current_SHARADAR_TICKERS_economically_active_fields":["sector"] if current_tickers else [],
        "metadata_after_decision_consumptions":meta_after,"unresolved_economically_relevant_splits":splits,
        "held_terminal_disappearances_unresolved":held,
        "financial_grade":{"requires_resolved_nav":True,"missing_leadership_return_policy":"FAIL_CLOSED","dividend_lag_sessions":15}}))
    return cert.collect_replay_evidence(mode=idv["mode"],identity=idv,output_root=root,checkpoint_resume=checkpoint)


def build_test_evidence(dataset_root: Path, pointer: Path, idv, **overrides):
    audit=cert.audit_dataset_contract(dataset_root,pointer)
    args=dict(static_forward_bias=cert.PASS,dynamic_future_leak=cert.PASS,runtime_causal_read_boundary=cert.PASS,
              financial_semantics=cert.PASS,checkpoint_resume=cert.PASS); args.update(overrides)
    return cert.collect_test_evidence(identity=idv,dataset_audit=audit,**args)


def write_evidence(path: Path, value): cert.write_json(path,value)


class CertificationTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def complete(self, *, unknown=False, terminal=0, actions=0, metadata_after=0, replay_kw=None, test_kw=None, idv=None):
        ds=self.root/"dataset"; pointer=create_dataset(ds,unknown=unknown,incomplete_terminal=terminal,unresolved_actions=actions,metadata_after=metadata_after)
        idv=idv or identity(pointer); r=replay_evidence(self.root/"replay",idv,**(replay_kw or {})); t=build_test_evidence(ds,pointer,idv,**(test_kw or {}))
        rp=self.root/"replay.json"; tp=self.root/"tests.json"; write_evidence(rp,r); write_evidence(tp,t)
        return cert.finalise(identity=idv,dataset_root=ds,pointer_path=pointer,replay_evidence_path=rp,test_evidence_path=tp), ds,pointer,rp,tp,idv
    def test_01_certified_dataset_replay_and_suite_certifies(self): c,*_=self.complete(); self.assertEqual(c["status"],cert.CERTIFIED)
    def test_02_unknown_security_type_fails(self): c,*_=self.complete(unknown=True); self.assertEqual(c["status"],cert.NOT_CERTIFIED); self.assertEqual(c["checks"]["universe_resolution"],cert.FAIL)
    def test_03_current_tickers_economic_use_is_not_certified(self):
        ds=self.root/"d"; p=create_dataset(ds); i=identity(p)
        with self.assertRaisesRegex(RuntimeError,"current SHARADAR_TICKERS"): replay_evidence(self.root/"r",i,current_tickers=True)
        t=build_test_evidence(ds,p,i); tp=self.root/"t.json"; write_evidence(tp,t)
        c=cert.finalise(identity=i,dataset_root=ds,pointer_path=p,replay_evidence_path=None,test_evidence_path=tp); self.assertEqual(c["status"],cert.NOT_CERTIFIED)
    def test_04_future_dated_metadata_consumption_fails(self): c,*_=self.complete(metadata_after=1); self.assertEqual(c["status"],cert.NOT_CERTIFIED); self.assertEqual(c["checks"]["pit_metadata"],cert.FAIL)
    def test_05_dynamic_future_read_negative_control_is_detected(self): ds=self.root/"d"; create_dataset(ds,many_sessions=True); out=leak.run(ds); self.assertEqual(out["status"],cert.PASS); self.assertTrue(all(r["negative_control_detected"] for r in out["cutoffs"]))
    def test_06_poisoned_future_preserves_correct_prefix_hashes(self): ds=self.root/"d"; create_dataset(ds,many_sessions=True); out=leak.run(ds); self.assertTrue(all(not r["pre_cutoff_mismatches"] for r in out["cutoffs"]))
    def test_truncated_future_preserves_correct_prefix_hashes(self): ds=self.root/"d"; create_dataset(ds,many_sessions=True); out=leak.run(ds); self.assertTrue(all(not r["truncation_mismatches"] for r in out["cutoffs"]))
    def test_07_deliberate_future_dependency_changes_prefix(self): ds=self.root/"d"; create_dataset(ds,many_sessions=True); out=leak.run(ds); self.assertTrue(any(r["negative_control_differences"] for r in out["cutoffs"]))
    def test_08_missing_held_terminal_disposition_fails(self): c,*_=self.complete(replay_kw={"held":1}); self.assertEqual(c["status"],cert.NOT_CERTIFIED); self.assertEqual(c["checks"]["terminal_events"],cert.FAIL)
    def test_09_unresolved_split_fails(self): c,*_=self.complete(replay_kw={"splits":1}); self.assertEqual(c["status"],cert.NOT_CERTIFIED); self.assertEqual(c["checks"]["corporate_actions"],cert.FAIL)
    def test_10_dataset_member_changed_after_tests_fails(self):
        c,ds,p,rp,tp,i=self.complete(); self.assertEqual(c["status"],cert.CERTIFIED)
        with gzip.open(ds/"actions.csv.gz","at",encoding="utf-8") as h: h.write("x,y,z\n")
        c2=cert.finalise(identity=i,dataset_root=ds,pointer_path=p,replay_evidence_path=rp,test_evidence_path=tp); self.assertEqual(c2["checks"]["dataset_integrity"],cert.FAIL)
    def test_11_pointer_hash_mismatch_fails(self):
        c,ds,p,rp,tp,i=self.complete(); obj=json.loads(p.read_text()); obj["manifest_sha256"]="e"*64; p.write_text(json.dumps(obj)); c2=cert.finalise(identity=i,dataset_root=ds,pointer_path=p,replay_evidence_path=rp,test_evidence_path=tp); self.assertEqual(c2["status"],cert.NOT_CERTIFIED)
    def test_12_research_source_change_after_suite_fails(self):
        c,ds,p,rp,tp,i=self.complete(); changed=copy.deepcopy(i); changed["source_sha"]=SHA_B; changed["configuration"]["source_sha"]=SHA_B; body=dict(changed); body.pop("identity_sha256",None); changed["identity_sha256"]=cert.json_hash(body); c2=cert.finalise(identity=changed,dataset_root=ds,pointer_path=p,replay_evidence_path=rp,test_evidence_path=tp); self.assertEqual(c2["status"],cert.NOT_CERTIFIED)
    def test_13_research_parameter_change_after_suite_fails(self):
        c,ds,p,rp,tp,i=self.complete(); changed=identity(p,params={"mode":"fullpit","alpha":2}); c2=cert.finalise(identity=changed,dataset_root=ds,pointer_path=p,replay_evidence_path=rp,test_evidence_path=tp); self.assertEqual(c2["status"],cert.NOT_CERTIFIED)
    def test_14_production_strategy_sha_mismatch_fails(self):
        ds=self.root/"d"; p=create_dataset(ds); i=identity(p,mode="production",strategy=SHA_B); r=replay_evidence(self.root/"r",i); t=build_test_evidence(ds,p,i); rp=self.root/"r.json";tp=self.root/"t.json";write_evidence(rp,r);write_evidence(tp,t); changed=identity(p,mode="production",strategy=SHA_C); c=cert.finalise(identity=changed,dataset_root=ds,pointer_path=p,replay_evidence_path=rp,test_evidence_path=tp); self.assertEqual(c["status"],cert.NOT_CERTIFIED)
    def test_15_successful_replay_failed_suite_fails(self): c,ds,p,rp,tp,i=self.complete(); c2=cert.finalise(identity=i,dataset_root=ds,pointer_path=p,replay_evidence_path=rp,test_evidence_path=tp,tests_job_result="failure"); self.assertEqual(c2["status"],cert.NOT_CERTIFIED)
    def test_16_failed_replay_successful_suite_fails(self): c,ds,p,rp,tp,i=self.complete(); c2=cert.finalise(identity=i,dataset_root=ds,pointer_path=p,replay_evidence_path=rp,test_evidence_path=tp,replay_job_result="failure"); self.assertEqual(c2["status"],cert.NOT_CERTIFIED)
    def test_17_different_source_shas_do_not_join(self):
        c,ds,p,rp,tp,i=self.complete(); t=cert.load_json(tp); t["identity"]=identity(p,source=SHA_B); t["evidence_hash"]=cert.json_hash({k:v for k,v in t.items() if k!="evidence_hash"}); write_evidence(tp,t); c2=cert.finalise(identity=i,dataset_root=ds,pointer_path=p,replay_evidence_path=rp,test_evidence_path=tp); self.assertEqual(c2["status"],cert.NOT_CERTIFIED)
    def test_18_different_dataset_hashes_do_not_join(self):
        c,ds,p,rp,tp,i=self.complete(); t=cert.load_json(tp); t["identity"]["dataset_hash"]="f"*64; body=dict(t["identity"]);body.pop("identity_sha256",None);t["identity"]["identity_sha256"]=cert.json_hash(body);t["evidence_hash"]=cert.json_hash({k:v for k,v in t.items() if k!="evidence_hash"});write_evidence(tp,t); c2=cert.finalise(identity=i,dataset_root=ds,pointer_path=p,replay_evidence_path=rp,test_evidence_path=tp); self.assertEqual(c2["status"],cert.NOT_CERTIFIED)
    def test_19_checkpoint_resume_mismatch_fails(self): c,*_=self.complete(test_kw={"checkpoint_resume":cert.FAIL}); self.assertEqual(c["checks"]["checkpoint_resume"],cert.FAIL)
    def test_20_certificate_hash_changes_with_economic_evidence(self):
        c1,*_=self.complete(); h1=c1["certificate_hash"]; self.tmp.cleanup(); self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); ds=self.root/"d";p=create_dataset(ds);i=identity(p,params={"mode":"fullpit","alpha":3});r=replay_evidence(self.root/"r",i);t=build_test_evidence(ds,p,i);rp=self.root/"r.json";tp=self.root/"t.json";write_evidence(rp,r);write_evidence(tp,t); c2=cert.finalise(identity=i,dataset_root=ds,pointer_path=p,replay_evidence_path=rp,test_evidence_path=tp); self.assertNotEqual(h1,c2["certificate_hash"])
    def test_human_summary_uses_precise_claim(self): c,*_=self.complete(); text=cert.render_summary(c); self.assertIn("PIT CERTIFIED",text); self.assertNotIn("free of bias",text.lower()); self.assertNotIn("bias free",text.lower())


class WorkflowStructureTests(unittest.TestCase):
    def _repo_root(self):
        here=Path(__file__).resolve()
        for parent in (here.parent,*here.parents):
            if (parent/".github/workflows").is_dir() and (parent/"backtester").is_dir(): return parent
        self.skipTest("repository root is not present")
    def test_21_legacy_certification_workflow_cannot_emit_current_certificate(self):
        root=self._repo_root(); legacy=(root/".github/workflows/backtester-strict-pit-certification.yml").read_text(); self.assertIn("RETIRED",legacy); self.assertIn("HISTORICAL_EVIDENCE_ONLY",legacy); self.assertNotIn("PIT CERTIFIED",legacy); self.assertNotIn("certify_backtest_result.py finalize",legacy)
    def test_22_every_official_launch_path_reaches_common_finalizer(self):
        root=self._repo_root(); official=[]
        for path in (root/".github/workflows").glob("backtester-*.yml"):
            text=path.read_text()
            if "PIT_OFFICIAL_BACKTEST: '1'" in text: official.append((path.name,text))
        self.assertEqual({name for name,_ in official},{"backtester-production-strict-pit-20y.yml","backtester-research-only-20y.yml"})
        for name,text in official:
            self.assertIn("backtester-pit-certification-suite.yml",text,name); self.assertIn("certify_backtest_result.py finalize",text,name); self.assertIn("if: ${{ always() }}",text,name)


if __name__ == "__main__": unittest.main()
