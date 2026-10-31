"""Independent journey verdicts: incomplete evidence is never product success."""
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
PROJECTS = ('webkit-iphone', 'chromium-pwa')


def observed_report(project, *, product_failure=False):
    """Literal wire evidence; do not derive the oracle from runner decisions."""
    return {
        'schema': 'sentinel.dashboard-journey/1',
        'project': project,
        'capture': {'complete': True, 'status': 'COMPLETE', 'event_overflow': False,
                    'expected_html_responses': 3},
        'responses': [{}, {}, {}],
        'events': [{'type': 'capture-start'}],
        'acceptance': {
            'status': 'FAIL' if product_failure else 'PASS',
            'findings': [{'code': 'HEALTHY_REFRESH_FLICKER'}] if product_failure else [],
        },
        'physical_home_screen': {'status': 'NOT_RUN', 'reason': 'Desktop browser evidence only'},
    }


def reports():
    return [observed_report(project) for project in PROJECTS]


def raw_playwright():
    """Two actual one-pass journey cases, independently declared wire values."""
    return {
        'errors': [],
        'stats': {'expected': 2, 'unexpected': 0, 'skipped': 0, 'flaky': 0},
        'suites': [{'title': 'dashboard-journey.spec.js', 'suites': [{
            'title': 'Unmodified dashboard journey', 'specs': [{
                'title': 'records cold navigation and two actual HTML refreshes',
                'file': 'dashboard-journey.spec.js', 'line': 8,
                'tests': [{
                    'projectName': project, 'expectedStatus': 'passed', 'status': 'expected',
                    'results': [{'status': 'passed', 'retry': 0, 'errors': []}],
                } for project in PROJECTS],
            }],
        }]}],
    }


class DashboardJourneyRunnerContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        name = 'independent_dashboard_journey_runner'
        spec = importlib.util.spec_from_file_location(name, ROOT/'scripts/sentinel_dashboard_journey.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        cls.runner = module

    def assert_incomplete(self, evidence, *, exit_code=0, timed_out=False):
        outcome = self.runner.assess_run(exit_code, evidence, PROJECTS, timed_out=timed_out)
        self.assertEqual(outcome['status'], 'INCOMPLETE')

    def test_explicit_https_and_http_loopback_roots_are_accepted(self):
        for url in ('https://dashboard.example.test/', 'http://127.0.0.1:18004/',
                    'http://localhost:18004/', 'http://[::1]:18004/'):
            with self.subTest(url=url):
                self.assertEqual(self.runner.validate_url(url), url)

    def test_credentials_queries_fragments_paths_and_nonloopback_http_are_rejected(self):
        for url in ('https://user:secret@dashboard.example.test/',
                    'https://user@dashboard.example.test/',
                    'https://dashboard.example.test/?token=secret',
                    'https://dashboard.example.test/#saved',
                    'https://dashboard.example.test/panel.json',
                    'http://dashboard.example.test/', 'http://192.168.1.10/',
                    'http://0.0.0.0/', 'http://127.0.0.1.example.test/',
                    'dashboard.example.test', '//dashboard.example.test/',
                    '/relative', 'file:///tmp/dashboard', 'ftp://dashboard.example.test/'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.runner.validate_url(url)

    def test_two_complete_passing_desktop_projects_cannot_clear_the_physical_gate(self):
        outcome = self.runner.assess_run(0, reports(), PROJECTS)
        self.assertEqual(outcome['status'], 'PASSED_DESKTOP')
        self.assertEqual(outcome['physical_home_screen']['status'], 'NOT_RUN')

    def test_a_captured_product_failure_is_observed_failure_not_incomplete_or_success(self):
        evidence = reports()
        evidence[1] = observed_report(PROJECTS[1], product_failure=True)
        outcome = self.runner.assess_run(1, evidence, PROJECTS)
        self.assertEqual(outcome['status'], 'OBSERVED_FAILURE')

    def test_missing_duplicate_or_unexpected_projects_are_incomplete(self):
        for evidence in ([], reports()[:1], [observed_report(PROJECTS[0])]*2,
                         [observed_report(PROJECTS[0]), observed_report('another-browser')]):
            with self.subTest(projects=[item['project'] for item in evidence]):
                self.assert_incomplete(evidence)

    def test_incomplete_capture_or_overflow_cannot_be_hidden_by_acceptance_pass(self):
        for field, value in (('complete', False), ('status', 'TIMED_OUT'),
                             ('status', 'RUNNING'), ('event_overflow', True)):
            evidence = reports()
            evidence[0]['capture'][field] = value
            with self.subTest(field=field, value=value):
                self.assert_incomplete(evidence)

    def test_missing_response_or_event_evidence_is_not_a_complete_journey(self):
        for defect in ('few-responses', 'no-responses', 'no-events', 'wrong-target-count'):
            evidence = reports()
            if defect == 'few-responses': evidence[0]['responses'] = [{}, {}]
            elif defect == 'no-responses': evidence[0].pop('responses')
            elif defect == 'no-events': evidence[0]['events'] = []
            else: evidence[0]['capture']['expected_html_responses'] = 2
            with self.subTest(defect=defect):
                self.assert_incomplete(evidence)

    def test_exit_mismatches_timeout_and_infrastructure_errors_are_incomplete(self):
        failing = reports()
        failing[0] = observed_report(PROJECTS[0], product_failure=True)
        for code, evidence, timed_out in ((0, failing, False), (1, reports(), False),
                                         (2, failing, False), (0, reports(), True)):
            with self.subTest(code=code, timed_out=timed_out):
                self.assert_incomplete(evidence, exit_code=code, timed_out=timed_out)

    def test_a_desktop_report_cannot_claim_physical_home_screen_execution(self):
        for claim in ('PASSED', 'COMPLETE', 'RUNNING'):
            evidence = reports()
            evidence[0]['physical_home_screen']['status'] = claim
            with self.subTest(claim=claim):
                self.assert_incomplete(evidence)

    def test_wrong_schema_or_unreasoned_acceptance_is_incomplete(self):
        for defect in ('schema', 'pass-with-findings', 'fail-without-findings',
                       'finding-without-code', 'unknown-acceptance'):
            evidence = reports()
            code = 0
            if defect == 'schema': evidence[0]['schema'] = 'sentinel.dashboard-journey/0'
            elif defect == 'pass-with-findings':
                evidence[0]['acceptance']['findings'] = [{'code': 'HEALTHY_REFRESH_FLICKER'}]
            elif defect == 'fail-without-findings':
                evidence[0]['acceptance']['status'] = 'FAIL'
                code = 1
            elif defect == 'finding-without-code':
                evidence[0]['acceptance'] = {'status': 'FAIL', 'findings': [{}]}
                code = 1
            else: evidence[0]['acceptance']['status'] = 'UNKNOWN'
            with self.subTest(defect=defect):
                self.assert_incomplete(evidence, exit_code=code)

    def test_assessment_preserves_original_capture_and_acceptance_evidence(self):
        evidence = reports()
        original = deepcopy(evidence)
        self.runner.assess_run(0, evidence, PROJECTS)
        self.assertEqual(evidence, original)

    def test_actual_playwright_passes_must_match_both_capture_projects(self):
        raw = raw_playwright()
        original = deepcopy(raw)
        self.assertTrue(self.runner.playwright_matches(raw, reports(), PROJECTS, 'capture'))
        self.assertEqual(raw, original)

    def test_a_true_product_failure_matches_one_actual_failed_browser_case(self):
        evidence, raw = reports(), raw_playwright()
        evidence[1] = observed_report(PROJECTS[1], product_failure=True)
        raw['stats'].update(expected=1, unexpected=1)
        failed = raw['suites'][0]['suites'][0]['specs'][0]['tests'][1]
        failed.update(status='unexpected', results=[{
            'status': 'failed', 'retry': 0,
            'errors': [{'message': 'UX acceptance: HEALTHY_REFRESH_FLICKER'}],
        }])
        self.assertTrue(self.runner.playwright_matches(raw, evidence, PROJECTS, 'capture'))
        self.assertEqual(self.runner.assess_run(1, evidence, PROJECTS)['status'], 'OBSERVED_FAILURE')

    def test_raw_skipped_extra_retried_foreign_or_infrastructure_cases_cannot_hide_behind_reports(self):
        for defect in ('skipped', 'extra', 'retry', 'second-result', 'wrong-case',
                       'wrong-group', 'wrong-project', 'global-error', 'stats'):
            raw = raw_playwright()
            group = raw['suites'][0]['suites'][0]
            spec = group['specs'][0]
            test = spec['tests'][0]
            if defect == 'skipped':
                test.update(status='skipped', expectedStatus='skipped')
                test['results'][0]['status'] = 'skipped'
                raw['stats'].update(expected=1, skipped=1)
            elif defect == 'extra': spec['tests'].append(deepcopy(test))
            elif defect == 'retry': test['results'][0]['retry'] = 1
            elif defect == 'second-result': test['results'].append(deepcopy(test['results'][0]))
            elif defect == 'wrong-case': spec['title'] = 'some other successful browser case'
            elif defect == 'wrong-group': group['title'] = 'another browser suite'
            elif defect == 'wrong-project': test['projectName'] = 'unrequested-project'
            elif defect == 'global-error': raw['errors'] = [{'message': 'browser infrastructure error'}]
            else: raw['stats']['expected'] = 3
            with self.subTest(defect=defect):
                self.assertFalse(self.runner.playwright_matches(raw, reports(), PROJECTS, 'capture'))

    def test_capture_gate_bypass_mutant_is_caught_by_the_same_negative_oracle(self):
        original = self.runner.assess_run
        evidence = reports()
        evidence[0]['capture']['complete'] = False
        self.assert_incomplete(evidence)

        def missing_capture_gate(exit_code, supplied, expected_projects, *, timed_out=False):
            unchecked = deepcopy(supplied)
            for item in unchecked:
                item['capture']['complete'] = True
            return original(exit_code, unchecked, expected_projects, timed_out=timed_out)

        with mock.patch.object(self.runner, 'assess_run', side_effect=missing_capture_gate):
            with self.assertRaises(AssertionError):
                self.assert_incomplete(evidence)


if __name__ == '__main__':
    unittest.main()
