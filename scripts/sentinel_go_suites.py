"""Shared complete-suite execution for the two local GO certification callers."""
SENTINEL_PARTITIONS = ('general', 'rolling', 'warmup', 'automation')
AUTOMATION_MODULES = frozenset((
    'test_automation_service.py', 'test_automation_composition.py',
    'test_automation_worker_source_recovery.py', 'test_issue_201_automation_financial_grade.py',
    'test_automation_p1_continuity.py', 'test_automation_safety_seams.py',
    'test_automation_process_contracts.py',
))


def partition_for(filename):
    if filename == 'test_source_seed_warmup.py':
        return 'warmup'
    if filename.startswith('test_rolling_'):
        return 'rolling'
    if filename in AUTOMATION_MODULES:
        return 'automation'
    return 'general'


def run(runner, *, image, exclusions, parse_summary):
    docker = ['docker', 'run', '--rm', '--network', 'none']
    options = ['-vv', '-ra', '--tb=short', '-x']
    groups = (
        tuple(docker + ['--entrypoint', 'python', image,
                       'tools/sentinel_test_partition.py', part] + options
              for part in SENTINEL_PARTITIONS),
        (docker + [image, 'tests/wealth_core']
         + [value for node in exclusions for value in ('--deselect', node)] + options,),
        (docker + [image, 'tests/scripts/test_sentinel_go_validate.py',
                   'tests/scripts/test_sentinel_reviewed_deploy_gate.py'] + options,),
    )
    counts = dict.fromkeys(('passed', 'failed', 'errors', 'skipped', 'xfailed', 'xpassed'), 0)
    combined_exit, completed = 0, 0
    for commands in groups:
        complete = True
        for command in commands:
            result = runner.run(command)
            observed = parse_summary((result.stdout or '') + '\n' + (result.stderr or ''))
            for key in counts:
                counts[key] += observed[key]
            if (result.returncode != 0 or observed['passed'] <= 0
                    or any(observed[key] for key in observed if key != 'passed')):
                complete = False
            if result.returncode != 0:
                combined_exit = int(result.returncode)
        completed += int(complete)
    return counts, combined_exit, completed
