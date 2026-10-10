"""Strict, read-only authority and image checks for qualified PR promotion.

Host-compatible Python 3.8. No Docker, signing, broker or mutation operations.
"""
from copy import deepcopy
import re

REPOSITORY = "flabber1835/stocker"
REPOSITORY_ID = 1233957439
WORKFLOWS = (
    ".github/workflows/sentinel-safety.yml",
    ".github/workflows/production-composition-harness.yml",
    ".github/workflows/sentinel-operator-browser.yml",
    ".github/workflows/backup-reliability.yml",
    ".github/workflows/internal-state-harness.yml",
)
PLAN_SCHEMA = "sentinel.qualified-pr-promotion/1"
PROMOTION_SCHEMA = "sentinel.software-qualification-reuse/1"
GIT = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class PromotionRefused(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise PromotionRefused(message)


def positive(value):
    require(type(value) is int and value > 0, "invalid integer identity")
    return value


def git(value):
    require(isinstance(value, str) and GIT.fullmatch(value), "invalid Git identity")
    return value


def digest(value):
    require(isinstance(value, str) and DIGEST.fullmatch(value), "invalid image/artifact digest")
    return value


def rows(client, path, key):
    result = []
    for page in range(1, 11):
        value = client.json(path + ("&" if "?" in path else "?") +
                            "per_page=100&page=%d" % page)
        batch = value.get(key)
        require(isinstance(batch, list) and all(isinstance(x, dict) for x in batch),
                "malformed paged GitHub authority")
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise PromotionRefused("GitHub authority exceeds pagination bound")


def same_repo(value):
    return (isinstance(value, dict) and type(value.get("id")) is int and
            value["id"] == REPOSITORY_ID and value.get("full_name") == REPOSITORY)


def tree(client, commit):
    value = client.json("/repos/%s/git/commits/%s" % (REPOSITORY, git(commit)))
    require(value.get("sha") == commit and isinstance(value.get("tree"), dict),
            "commit authority differs")
    return git(value["tree"].get("sha"))


def check_pr(client, plan):
    pr = client.json("/repos/%s/pulls/%d" % (REPOSITORY, positive(plan["pr"])))
    require(pr.get("merged") is True and pr.get("merge_commit_sha") == plan["source_commit"]
            and isinstance(pr.get("base"), dict) and pr["base"].get("ref") == "main"
            and same_repo(pr["base"].get("repo")) and isinstance(pr.get("head"), dict)
            and same_repo(pr["head"].get("repo"))
            and pr["head"].get("sha") == plan["tested_commit"], "merged PR binding differs")
    require(tree(client, plan["source_commit"]) == plan["source_tree"] ==
            tree(client, plan["tested_commit"]) == plan["tested_tree"],
            "complete merged tree differs from tested tree")
    checks = rows(client, "/repos/%s/commits/%s/check-runs?filter=latest" %
                  (REPOSITORY, plan["tested_commit"]), "check_runs")
    names = [x.get("name") for x in checks]
    require(len(names) == len(set(names)) and
            {"host-python-38-exact-head", "sentinel-exact-head", "iPhone WebKit and PWA",
             "composition-synthetic-merge"}.issubset(names) and
            all(x.get("status") == "completed" and x.get("conclusion") == "success"
                and x.get("head_sha") == plan["tested_commit"] for x in checks),
            "applicable exact-head PR checks are not successful")


def check_run(client, row, commit):
    require(set(row) == {"path", "run", "attempt"} and row["path"] in WORKFLOWS,
            "unknown qualification workflow")
    run = client.json("/repos/%s/actions/runs/%d" % (REPOSITORY, positive(row["run"])))
    require(type(run.get("workflow_id")) is int and run["workflow_id"] > 0
            and run.get("path") == row["path"] and run.get("head_sha") == commit
            and run.get("event") == "pull_request" and run.get("status") == "completed"
            and run.get("conclusion") == "success" and same_repo(run.get("repository"))
            and same_repo(run.get("head_repository"))
            and type(run.get("run_attempt")) is int
            and run["run_attempt"] == positive(row["attempt"]), "original workflow binding differs")
    if row["path"] == WORKFLOWS[0]:
        require(run["workflow_id"] == 333697638, "safety workflow authority differs")
    jobs = rows(client, "/repos/%s/actions/runs/%d/attempts/%d/jobs" %
                (REPOSITORY, row["run"], row["attempt"]), "jobs")
    require(jobs and all(x.get("conclusion") == "success" for x in jobs),
            "original qualification contains nonpassing jobs")
    return run


def check_artifact(client, artifact, name, run):
    require(set(artifact) == {"id", "digest", "name", "run"} and
            artifact["name"] == name and artifact["run"] == run,
            "artifact binding differs")
    digest(artifact["digest"])
    value = client.json("/repos/%s/actions/artifacts/%d" %
                        (REPOSITORY, positive(artifact["id"])))
    require(value.get("id") == artifact["id"] and type(value.get("id")) is int
            and value.get("name") == name and value.get("expired") is False
            and value.get("digest") == artifact["digest"]
            and isinstance(value.get("workflow_run"), dict)
            and type(value["workflow_run"].get("id")) is int
            and value["workflow_run"]["id"] == run, "retained artifact authority differs")


def validate_plan(plan):
    require(isinstance(plan, dict) and set(plan) == {
        "schema", "mode", "source_commit", "source_tree", "pr", "tested_commit",
        "tested_tree", "workflows", "artifact", "checkout_proofs"} and
        plan["schema"] == PLAN_SCHEMA and plan["mode"] == "promote", "promotion plan schema differs")
    for key in ("source_commit", "source_tree", "tested_commit", "tested_tree"):
        git(plan[key])
    positive(plan["pr"])
    require(plan["source_tree"] == plan["tested_tree"], "tested tree differs")
    require(isinstance(plan["workflows"], list) and len(plan["workflows"]) == len(WORKFLOWS)
            and all(isinstance(x, dict) and set(x) == {"path", "run", "attempt"}
                    for x in plan["workflows"])
            and {x["path"] for x in plan["workflows"]} == set(WORKFLOWS),
            "qualification workflow inventory differs")
    for row in plan["workflows"]:
        positive(row["run"])
        positive(row["attempt"])
    require(isinstance(plan["artifact"], dict) and
            set(plan["artifact"]) == {"id", "digest", "name", "run"}, "tested artifact schema differs")
    positive(plan["artifact"]["id"])
    positive(plan["artifact"]["run"])
    digest(plan["artifact"]["digest"])
    require(isinstance(plan["checkout_proofs"], list) and len(plan["checkout_proofs"]) == 2,
            "checkout proof inventory differs")


def verify_plan(client, plan):
    validate_plan(plan)
    check_pr(client, plan)
    workflow_rows = plan["workflows"]
    require(isinstance(workflow_rows, list) and len(workflow_rows) == len(WORKFLOWS)
            and all(isinstance(x, dict) for x in workflow_rows)
            and {x.get("path") for x in workflow_rows} == set(WORKFLOWS),
            "qualification workflow inventory differs")
    for row in workflow_rows:
        check_run(client, row, plan["tested_commit"])
    safety = next(x for x in workflow_rows if x["path"] == WORKFLOWS[0])
    check_artifact(client, plan["artifact"], "sentinel-tested-image-" + plan["tested_commit"], safety["run"])
    proofs = plan["checkout_proofs"]
    require(isinstance(proofs, list) and len(proofs) == 2, "checkout proof inventory differs")
    seen = set()
    for entry in proofs:
        require(isinstance(entry, dict) and set(entry) == {"artifact", "proof"}, "checkout proof shape differs")
        proof = entry["proof"]
        require(isinstance(proof, dict) and set(proof) == {
            "repository", "path", "commit", "tree", "run", "attempt"} and
            proof["repository"] == REPOSITORY and proof["path"] in WORKFLOWS[1:3]
            and proof["path"] not in seen and proof["tree"] == plan["source_tree"],
            "actual harness checkout tree differs")
        seen.add(proof["path"])
        row = next(x for x in workflow_rows if x["path"] == proof["path"])
        require(proof["run"] == row["run"] and type(proof["run"]) is int and
                proof["attempt"] == row["attempt"] and type(proof["attempt"]) is int
                and tree(client, proof["commit"]) == proof["tree"], "harness checkout identity differs")
        role = "composition" if proof["path"] == WORKFLOWS[1] else "browser"
        check_artifact(client, entry["artifact"],
                       "ci-checkout-proof-%s-%d" % (role, row["attempt"]), row["run"])


def image_record(image):
    require(isinstance(image, dict), "image inspection is not an object")
    value = {key: image.get(key) for key in ("Id", "Architecture", "Os", "Config", "RootFS")}
    digest(value["Id"])
    require(all(isinstance(value[x], str) and value[x] for x in ("Architecture", "Os"))
            and isinstance(value["Config"], dict) and isinstance(value["RootFS"], dict)
            and set(value["RootFS"]) == {"Type", "Layers"} and value["RootFS"]["Type"] == "layers"
            and isinstance(value["RootFS"]["Layers"], list) and value["RootFS"]["Layers"],
            "image configuration/layers are malformed")
    for layer in value["RootFS"]["Layers"]:
        digest(layer)
    return value


def normalize_config(config, revision):
    value = deepcopy(config)
    labels = value.get("Labels")
    env = value.get("Env")
    require(isinstance(labels, dict) and labels.get("org.opencontainers.image.revision") == revision
            and isinstance(env, list) and all(isinstance(x, str) and "=" in x for x in env),
            "image source metadata differs")
    keys = [x.split("=", 1)[0] for x in env]
    require(len(keys) == len(set(keys)) and env.count("SENTINEL_IMAGE_SOURCE_REVISION=" + revision) == 1,
            "runtime source environment differs")
    labels["org.opencontainers.image.revision"] = "<revision>"
    value["Env"] = ["SENTINEL_IMAGE_SOURCE_REVISION=<revision>" if
                    x.startswith("SENTINEL_IMAGE_SOURCE_REVISION=") else x for x in env]
    return value


def verify_images(before, after, tested, merged):
    require(set(before) == set(after) == {"Id", "Architecture", "Os", "Config", "RootFS"},
            "image proof schema differs")
    require(image_record(before) == before and image_record(after) == after,
            "image proof differs")
    require(before["Architecture"] == after["Architecture"] and before["Os"] == after["Os"]
            and before["RootFS"] == after["RootFS"] and
            normalize_config(before["Config"], tested) == normalize_config(after["Config"], merged),
            "promotion changed tested filesystem or executable configuration")


def verify_reuse(value, evidence):
    require(isinstance(value, dict) and set(value) == {
        "schema", "plan", "original_input", "tested_image", "promoted_image"}
        and value["schema"] == PROMOTION_SCHEMA, "qualification reuse schema differs")
    original = value["original_input"]
    plan = value["plan"]
    require(isinstance(original, dict) and set(original) == set(evidence) - {"qualification_reuse"}
            and original.get("schema") == "sentinel.software-certification-input/2"
            and isinstance(plan, dict) and plan.get("schema") == PLAN_SCHEMA and plan.get("mode") == "promote",
            "original qualification schema differs")
    validate_plan(plan)
    require(isinstance(value["tested_image"], dict) and isinstance(value["promoted_image"], dict),
            "image reuse evidence is malformed")
    positive(original["test_workflow_run"])
    positive(original["test_workflow_attempt"])
    require(plan["source_commit"] == evidence["source_commit"] and
            plan["source_tree"] == evidence["source_tree"] == plan["tested_tree"] == original["source_tree"]
            and plan["tested_commit"] == original["source_commit"], "qualification source binding differs")
    safety = [x for x in plan["workflows"] if x.get("path") == WORKFLOWS[0]]
    require(len(safety) == 1 and original["test_workflow_run"] == safety[0]["run"]
            and original["test_workflow_attempt"] == safety[0]["attempt"], "original test attempt differs")
    for key in original:
        if key not in ("schema", "source_commit", "test_workflow_run", "test_workflow_attempt", "runtime_image_id"):
            require(original[key] == evidence.get(key), "reused evidence differs: " + key)
    require(value["tested_image"].get("Id") == original["runtime_image_id"] and
            value["promoted_image"].get("Id") == evidence["runtime_image_id"], "tested/promoted image ID differs")
    verify_images(value["tested_image"], value["promoted_image"], plan["tested_commit"], plan["source_commit"])


def manifest_reuse(manifest):
    """Bind signed counts and executable identity to original PR execution."""
    tests, source, ci, runtime = (manifest[x] for x in ("tests", "source", "ci", "runtime"))
    evidence = {
        "schema": "sentinel.software-certification-input/3", "repository": source["repository"],
        "source_commit": source["commit"], "source_tree": source["tree"],
        "test_workflow_path": ci["test_workflow_path"], "test_workflow_run": ci["test_workflow_run"],
        "test_workflow_attempt": ci["test_workflow_attempt"], "runtime_image_id": runtime["ci_local_image_id"],
        "runtime_capability_sha256": runtime["runtime_capability_sha256"],
        "dependency_lock_hashes": manifest["dependencies"]["lock_hashes"],
        "test_manifest_sha256": tests["manifest_sha256"],
        "test_counts": {"total": {x: y for x, y in tests["required_counts"].items() if x != "suites_completed"},
                        "suites_completed": tests["required_counts"]["suites_completed"],
                        "suite_counts": tests["suite_counts"], "expected_xfails": tests["expected_xfails"]},
        "adversarial_evidence": tests["adversarial_evidence"], "mutation_evidence": tests["mutation_evidence"],
        "runtime_schema_epoch": manifest["epochs"]["runtime_schema"],
        "semantic_epoch": manifest["epochs"]["semantic"], "qualification_reuse": manifest["qualification_reuse"],
    }
    verify_reuse(evidence["qualification_reuse"], evidence)


def verify_promotion_dependencies(needs):
    expected = {"qualification-source": "success", "runtime-build": "success",
                "parallel-certification": "skipped", "sharadar-replay": "skipped"}
    require(isinstance(needs, dict) and set(needs) == set(expected) and
            all(isinstance(needs[x], dict) and needs[x].get("result") == result
                for x, result in expected.items()), "main promotion dependency inventory differs")
