"""Falsify source/cursor/commitment fencing and overnight ownership."""
import inspect
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from research.slow15_replay import continue_run, model, test_continue, test_model


def main():
    variants = {
        'source_binding': ('validate_resume',
            'if not isinstance(extra, dict) or extra.get("binding") != binding:', 'if False:',
            'test_resume_binding_and_cursor_and_commitment'),
        'cursor_binding': ('validate_resume',
            'if extra.get("cursor") != cursor or extra["economics"]["last_session"] != cursor:', 'if False:',
            'test_resume_binding_and_cursor_and_commitment'),
        'state_commitment': ('validate_resume',
            'if extra.get("sha256") != expected:', 'if False:',
            'test_resume_binding_and_cursor_and_commitment'),
        'overnight_ownership': ('oracle', 'old = D(str(previous["held_allocation"]))', 'old = new',
            'test_exit_pays_for_overnight_loss_before_selling'),
    }
    results = {}
    for name, (function, before, after, test) in variants.items():
        source = inspect.getsource(getattr(model, function))
        assert source.count(before) == 1
        ns = dict(vars(model))
        exec(compile(source.replace(before, after), '<research-mutant>', 'exec'), ns)
        original = getattr(test_model, function)
        setattr(test_model, function, ns[function])
        try:
            getattr(test_model, test)()
        except BaseException as exc:
            if not isinstance(exc, AssertionError) and type(exc).__name__ != 'Failed':
                raise
            results[name] = 'KILLED'
        else:
            raise AssertionError('surviving mutation: '+name)
        finally:
            setattr(test_model, function, original)
    source = inspect.getsource(continue_run.segment_directories)
    assert source.count(' if path.is_dir()') == 1
    ns = dict(vars(continue_run))
    exec(compile(source.replace(' if path.is_dir()', ''), '<research-mutant>', 'exec'), ns)
    original = test_continue.segment_directories
    test_continue.segment_directories = ns['segment_directories']
    try:
        with TemporaryDirectory() as directory:
            test_continue.test_restart_selects_segment_directory_not_its_newer_log(Path(directory))
    except AssertionError:
        results['resume_directory_selection'] = 'KILLED'
    else:
        raise AssertionError('surviving resume directory mutation')
    finally:
        test_continue.segment_directories = original
    out = Path('audit/slow15-twenty-year')
    out.mkdir(parents=True, exist_ok=True)
    (out/'mutations.json').write_text(json.dumps(results, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(results))


if __name__ == '__main__':
    main()
