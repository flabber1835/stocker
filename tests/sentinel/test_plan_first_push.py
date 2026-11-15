"""Plan-first disclosure keeps notification controls mounted and functional.

Only browser and transport doubles are used: no subscription or outbox writes.
"""
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from sentinel.panel.app import app
from sentinel.panel.model import Panel
from sentinel.panel.render import DEVICE_ASSET, PUSH_SCRIPT, render


class Dashboard(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.stack = []
        self.elements = []
        self.scripts = []
        self.script = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        item = (tag, dict(attrs))
        self.elements.append((item, tuple(self.stack)))
        if tag == 'script':
            self.script = []
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img',
                       'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(item)

    def handle_endtag(self, tag):
        if tag == 'script' and self.script is not None:
            self.scripts.append(''.join(self.script))
            self.script = None
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)

    def by_id(self, name):
        matches = [(item, ancestors) for item, ancestors in self.elements
                   if item[1].get('id') == name]
        assert len(matches) == 1, f'{name} must be mounted exactly once'
        return matches[0]


def document(*, retained=False):
    return Dashboard(render(Panel(now=datetime(2026, 10, 23, 5,
                                              tzinfo=timezone.utc)),
                            refresh_pending=retained))


def mounted_push_controller(page):
    mounts = [attrs for (tag, attrs), _ in page.elements
              if tag == 'script' and attrs.get('src') == f'/static/{DEVICE_ASSET}']
    assert len(mounts) == 1, 'page must mount its notification controller exactly once'
    assert 'defer' in mounts[0]
    assert all(PUSH_SCRIPT not in script for script in page.scripts)
    response = TestClient(app).get(mounts[0]['src'])
    assert response.status_code == 200
    assert response.headers['content-type'].split(';')[0] == 'text/javascript'
    assert response.headers['cache-control'] == 'public, max-age=31536000, immutable'
    assert sha256(response.content).hexdigest() == DEVICE_ASSET.split('.')[1]
    assert response.text.count(PUSH_SCRIPT) == 1
    return response.text


@pytest.mark.parametrize('retained', [False, True])
def test_collapsed_system_details_preserves_push_controls_and_refresh_identity(retained):
    page = document(retained=retained)
    (tag, details), _ = page.by_id('system-details')
    assert tag == 'details'
    assert details.get('data-detail-key') == 'system-details'
    assert 'open' not in details, 'technical disclosure should start collapsed'
    assert 'hidden' not in details
    for name in ('push-card', 'push-enable', 'push-remove', 'push-status'):
        (tag, attrs), ancestors = page.by_id(name)
        assert ('details', details) in ancestors
        assert not any('inert' in ancestor[1] or ancestor[0] == 'template'
                       for ancestor in ancestors), 'closed disclosure must not unmount controls'
        if name in {'push-enable', 'push-remove'}:
            assert tag == 'button' and attrs.get('type') == 'button'
            assert 'disabled' not in attrs
    mounted_push_controller(page)


@pytest.mark.parametrize('scenario', ['existing-accepted', 'new-accepted',
                                     'remove-present', 'permission-denied',
                                     'queued-expired'])
def test_push_controller_mounted_in_plan_first_page_retains_device_behavior(scenario):
    node = shutil.which('node')
    if node is None:
        pytest.fail('Node is required for notification controller qualification')
    script = mounted_push_controller(document())
    result = subprocess.run(
        [node, str(Path(__file__).with_name('panel_push_harness.cjs'))],
        input=json.dumps({'script': script, 'scenario': scenario}),
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'PASS\n'
