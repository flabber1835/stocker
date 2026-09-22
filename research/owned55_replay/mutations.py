"""Kill policy, composition, accounting, and resume guard mutations."""
import inspect
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from research.owned55_replay import continue_run, model, test_continue, test_model


def kill_function(name, function, before, after, test):
    source = inspect.getsource(getattr(model, function))
    if source.count(before) != 1:
        raise AssertionError(f"mutation source mismatch: {name}")
    namespace = dict(vars(model))
    exec(compile(source.replace(before, after), "<owned55-mutant>", "exec"), namespace)
    original = getattr(test_model, function)
    setattr(test_model, function, namespace[function])
    try:
        getattr(test_model, test)()
    except BaseException as exc:
        if not isinstance(exc, AssertionError) and type(exc).__name__ != "Failed":
            raise
        return "KILLED"
    finally:
        setattr(test_model, function, original)
    raise AssertionError("surviving mutation: "+name)


def kill_class(name, before, after, test):
    source = inspect.getsource(model.Owned55)
    if source.count(before) != 1:
        raise AssertionError(f"mutation source mismatch: {name}")
    namespace = dict(vars(model))
    exec(compile(source.replace(before, after), "<owned55-mutant>", "exec"), namespace)
    original = test_model.Owned55
    test_model.Owned55 = namespace["Owned55"]
    try:
        getattr(test_model, test)()
    except BaseException as exc:
        if not isinstance(exc, AssertionError) and type(exc).__name__ != "Failed":
            raise
        return "KILLED"
    finally:
        test_model.Owned55 = original
    raise AssertionError("surviving mutation: "+name)


def main():
    results = {
        "partial_ceiling": kill_function("partial_ceiling", "owned55_rule",
            "dict(parent, active_ceiling=.55)", "dict(parent, active_ceiling=1.)",
            "test_only_parent_active_ceiling_changes"),
        "fifth_bad_close": kill_class("fifth_bad_close",
            'self.entry_streak >= rule["entry_sessions"]',
            'self.entry_streak > rule["entry_sessions"]',
            "test_enters_on_fifth_bad_close_at_partial_ceiling_and_restarts"),
        "eighth_healthy_close": kill_class("eighth_healthy_close",
            'self.recovery_streak >= rule["recovery_sessions"]',
            'self.recovery_streak > rule["recovery_sessions"]',
            "test_release_requires_eighth_owned_healthy_close"),
        "independent_zero_cause": kill_class("independent_zero_cause",
            'target=min(base["target"], ceiling)', 'target=ceiling',
            "test_existing_zero_cause_remains_zero"),
        "overnight_ownership": kill_function("overnight_ownership", "oracle",
            'old = D(str(previous["held_allocation"]))', "old = new",
            "test_exit_pays_for_overnight_loss_before_partial_reallocation"),
        "resume_binding": kill_function("resume_binding", "validate_resume",
            'if not isinstance(extra, dict) or extra.get("binding") != binding:', "if False:",
            "test_resume_binding_cursor_and_commitment"),
    }
    source = inspect.getsource(continue_run.segment_directories)
    if source.count(" if path.is_dir()") != 1:
        raise AssertionError("resume-directory mutation source mismatch")
    namespace = dict(vars(continue_run))
    exec(compile(source.replace(" if path.is_dir()", ""), "<owned55-mutant>", "exec"), namespace)
    original = test_continue.segment_directories
    test_continue.segment_directories = namespace["segment_directories"]
    try:
        with TemporaryDirectory() as directory:
            test_continue.test_restart_selects_segment_directory_not_log(Path(directory))
    except AssertionError:
        results["resume_directory_selection"] = "KILLED"
    else:
        raise AssertionError("surviving mutation: resume_directory_selection")
    finally:
        test_continue.segment_directories = original
    output = Path("audit/owned55-twenty-year")
    output.mkdir(parents=True, exist_ok=True)
    (output/"mutations.json").write_text(json.dumps(results, indent=2)+"\n", encoding="utf-8", newline="\n")
    print(json.dumps(results))


if __name__ == "__main__":
    main()
