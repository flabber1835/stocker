"""Falsify the real GET client's bounded availability and strict parsing."""
import http.client
import io
import urllib.error

import pytest

from scripts import sentinel_ci_certification_verify as verify


class Clock:
    value = 0.0

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


def client(outcomes, *, clock=None):
    clock = clock or Clock()
    calls = []
    responses = []

    def open_read(request, timeout):
        calls.append((request.get_method(), request.full_url,
                      request.get_header('Authorization'), timeout))
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        response = io.BytesIO(outcome)
        responses.append(response)
        return response

    return verify.GitHubReadClient(token='fixture-token', opener=open_read,
                                  monotonic=clock.now, sleep=clock.sleep), calls, responses, clock


def http_failure(code):
    return urllib.error.HTTPError('https://api.github.com/test', code,
                                  'fixture', {}, io.BytesIO(b'error'))


@pytest.mark.parametrize('failure', [http_failure(code) for code in
                         (408, 425, 429, 500, 502, 503, 504)] +
                         [urllib.error.URLError('fixture'), OSError('fixture'),
                          http.client.IncompleteRead(b'partial')])
def test_transient_get_retries_same_request_and_requires_complete_response(failure):
    reader, calls, responses, clock = client([failure, b'{"verified":true}'])
    assert reader.json('/test') == {'verified': True}
    assert len(calls) == 2 and clock.value == 1
    assert all(call[:3] == ('GET', verify.API_ROOT + '/test', 'Bearer fixture-token')
               for call in calls)
    assert all(0 < call[3] <= 10 for call in calls)
    assert responses[0].closed
    if isinstance(failure, urllib.error.HTTPError):
        assert failure.fp.closed


@pytest.mark.parametrize('code', [400, 401, 403, 404, 410, 501])
def test_permanent_http_failure_never_retries_into_positive_evidence(code):
    failure = http_failure(code)
    reader, calls, _, clock = client([failure, b'{"verified":true}'])
    with pytest.raises(verify.CertificationVerificationRefused) as caught:
        reader.json('/test')
    assert caught.value.code == 'CERT_GITHUB_UNAVAILABLE'
    assert len(calls) == 1 and clock.value == 0 and failure.fp.closed


def test_transient_exhaustion_is_three_attempts_without_cached_success():
    reader, calls, _, clock = client([http_failure(502) for _ in range(3)] +
                                   [b'{"verified":true}'])
    with pytest.raises(verify.CertificationVerificationRefused) as caught:
        reader.json('/test')
    assert caught.value.code == 'CERT_GITHUB_UNAVAILABLE'
    assert len(calls) == 3 and clock.value == 3


def test_all_attempts_share_original_budget_and_late_success_refuses():
    clock = Clock()
    calls = []
    responses = []

    def open_read(request, timeout):
        calls.append(timeout)
        clock.value += timeout
        if len(calls) < 3:
            raise urllib.error.URLError('fixture timeout')
        response = io.BytesIO(b'{"verified":true}')
        responses.append(response)
        return response

    reader = verify.GitHubReadClient(opener=open_read, monotonic=clock.now,
                                    sleep=clock.sleep)
    with pytest.raises(verify.CertificationVerificationRefused):
        reader.json('/test')
    assert calls == [10, 10, 7] and clock.value == 30
    assert responses[0].closed


def test_partial_body_is_closed_and_retried_without_accepting_partial_bytes():
    clock = Clock()
    calls = []

    class Partial(io.BytesIO):
        def read(self):
            raise http.client.IncompleteRead(b'{"verified":')

    partial = Partial(b'')
    complete = io.BytesIO(b'{"verified":true}')

    def open_read(request, timeout):
        calls.append(timeout)
        return partial if len(calls) == 1 else complete

    reader = verify.GitHubReadClient(opener=open_read, monotonic=clock.now,
                                    sleep=clock.sleep)
    assert reader.json('/test') == {'verified': True}
    assert len(calls) == 2 and partial.closed and complete.closed


@pytest.mark.parametrize('body', [b'{', b'{"same":1,"same":2}', b'{"bad":NaN}'])
def test_fetched_invalid_evidence_is_never_retried(body):
    reader, calls, responses, clock = client([body, b'{"verified":true}'])
    with pytest.raises(verify.CertificationVerificationRefused):
        reader.json('/test')
    assert len(calls) == 1 and clock.value == 0 and responses[0].closed
