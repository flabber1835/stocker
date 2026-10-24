"""Plan-first disclosure keeps notification controls mounted and functional.

Only browser and transport doubles are used: no subscription or outbox writes.
"""
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from sentinel.panel.model import Panel
from sentinel.panel.render import PUSH_SCRIPT, render


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
    assert sum(script == PUSH_SCRIPT for script in page.scripts) == 1


@pytest.mark.parametrize('scenario', ['existing-accepted', 'new-accepted',
                                     'remove-present', 'permission-denied',
                                     'queued-expired'])
def test_push_controller_embedded_in_plan_first_page_retains_device_behavior(scenario):
    node = shutil.which('node')
    if node is None:
        pytest.fail('Node is required for notification controller qualification')
    scripts = [script for script in document().scripts if script == PUSH_SCRIPT]
    assert len(scripts) == 1, 'page must mount its notification controller exactly once'
    result = subprocess.run(
        [node, str(Path(__file__).with_name('panel_push_harness.cjs'))],
        input=json.dumps({'script': scripts[0], 'scenario': scenario}),
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'PASS\n'
