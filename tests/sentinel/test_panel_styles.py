"""Compute the reviewed palette and mobile cascade, including specificity.

This bounded parser covers the stylesheet's declarative rules. It does not
claim browser layout/rendering parity; the current HTML still receives visual
review separately. Expected values are the effective 0067e90b presentation.
"""
import re

import pytest

from sentinel.panel.styles import CSS


OVERVIEW = dict(zip(
    ('bg', 'card', 'ink', 'muted', 'line', 'ok', 'warn', 'fail', 'pending',
     'okbg', 'warnbg', 'failbg', 'pendingbg', 'shadow'),
    ('#16111f', '#241c30', '#f5eee3', '#c2b7c8', '#4d3c57', '#8ce0b4',
     '#f2cd83', '#ffa69e', '#c4bfd1', '#20392f', '#493b23', '#492c32',
     '#30283c', '0 8px 28px #0002')))
OS_DARK = dict(zip(OVERVIEW,
    ('#0e0e19', '#1b1c2b', '#faf4e8', '#c5bdaf', '#494338', '#80e4b2',
     '#ffcb78', '#ff918b', '#c0bfd3', '#12261c', '#2a2113', '#2c1615',
     '#1b2028', '0 1px 2px rgba(0,0,0,.4)')))


def _rules(css, media=()):
    cursor = 0
    while cursor < len(css):
        start = css.find('{', cursor)
        if start < 0:
            return
        header = css[cursor:start].strip()
        depth, quote, escaped, end = 1, None, False, start+1
        while depth and end < len(css):
            char = css[end]
            if quote:
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == quote:
                    quote = None
            elif char in ('"', "'"):
                quote = char
            elif char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
            end += 1
        assert depth == 0, 'unbalanced stylesheet'
        content = css[start+1:end-1]
        if header.startswith('@media'):
            yield from _rules(content, (*media, header))
        elif not header.startswith('@'):
            # Commas within :not()/other selector functions are not group
            # boundaries. Current selectors have no nested function arguments.
            selectors = re.split(r',(?![^()]*\))', header)
            for selector in selectors:
                yield selector.strip(), content, media
        cursor = end


def _active(media, width, dark):
    for query in media:
        limit = re.search(r'(max|min)-width:\s*(\d+)px', query)
        if limit and ((limit[1] == 'max' and width > int(limit[2]))
                      or (limit[1] == 'min' and width < int(limit[2]))):
            return False
        if 'prefers-color-scheme:dark' in query.replace(' ', '') and not dark:
            return False
        if 'prefers-reduced-motion' in query:
            return False
    return True


def _matches(selector, target, theme):
    if target == 'root':
        if not selector.startswith(':root'):
            return False
        exclusions = re.findall(r':not\(\[data-theme="([^"]*)"\]\)', selector)
        if theme in exclusions:
            return False
        positive = re.sub(r':not\([^)]*\)', '', selector)
        values = re.findall(r'\[data-theme="([^"]*)"\]', positive)
        return not values or theme in values
    selectors = {
        'body': {'body'}, 'footer': {'footer'}, 'row': {'.row'},
        'row-details': {'.row', '#system-details .row'},
        'value': {'.value'}, 'value-details': {'.value', '#system-details .value'},
        'retained-prefix': {'.refreshing-status .row.ok .value::before'},
    }
    return selector in selectors[target]


def _specificity(selector):
    # :not() itself adds no specificity; its attribute arguments do.
    return (len(re.findall(r'#[\w-]+', selector)),
        len(re.findall(r'\.[\w-]+|\[[^]]+\]', selector))
        + sum(name != 'not' for name in re.findall(r'(?<!:):(?!:)([\w-]+)', selector)),
        int(selector in {'body', 'footer'}))


def _computed(css, target, width=375, dark=False, theme=None):
    winners = {}
    for order, (selector, content, media) in enumerate(_rules(css)):
        if not _active(media, width, dark) or not _matches(selector, target, theme):
            continue
        priority = (_specificity(selector), order)
        for entry in content.split(';'):
            if ':' not in entry:
                continue
            name, value = [item.strip() for item in entry.split(':', 1)]
            declarations = {name: value}
            if name == 'font' and (size := re.match(r'(\d+px)(?:/[^ ]+)? ', value)):
                declarations['font-size'] = size[1]
            if name == 'padding' and re.fullmatch(r'[\dpx\s]+', value):
                parts = value.split()
                sides = ((parts*4)[:4] if len(parts) == 1 else parts*2 if len(parts) == 2 else parts)
                declarations.update(zip(('padding-top', 'padding-right', 'padding-bottom', 'padding-left'), sides))
            for key, selected in declarations.items():
                if key not in winners or priority >= winners[key][0]:
                    winners[key] = (priority, selected)
    return {name: value for name, (_, value) in winners.items()}


@pytest.mark.parametrize('width', [320, 360, 375, 430, 768])
@pytest.mark.parametrize('dark,theme', [(False, None), (True, None), (False, 'light'),
    (True, 'light'), (False, 'dark'), (True, 'dark'), (False, 'unknown'), (True, 'unknown')])
def test_effective_palette_and_mobile_metrics_match_the_installed_presentation(width, dark, theme):
    expected = OS_DARK if dark and theme not in {'light', 'dark'} else OVERVIEW
    root = _computed(CSS, 'root', width, dark, theme)
    assert {name: root['--'+name] for name in expected} == expected
    assert _computed(CSS, 'body', width, dark, theme)['font-size'] == '15px'
    row = _computed(CSS, 'row', width, dark, theme)
    assert (row['padding-top'], row['padding-right']) == ('17px', '18px')
    row = _computed(CSS, 'row-details', width, dark, theme)
    assert (row['padding-top'], row['padding-right']) == ('14px', '13px')
    assert _computed(CSS, 'value', width, dark, theme)['font-size'] == ('16px' if width <= 360 else '22px')
    assert _computed(CSS, 'value-details', width, dark, theme)['font-size'] == '17px'
    assert _computed(CSS, 'footer', width, dark, theme)['text-align'] == 'center'


def _prefix(css):
    content = _computed(css, 'retained-prefix')['content'][1:-1]
    return re.sub(r'\\([0-9a-fA-F]{1,6})\s?', lambda match: chr(int(match[1], 16)), content)


def test_retained_value_prefix_keeps_literal_spacing():
    assert _prefix(CSS) == 'LAST KNOWN · '


@pytest.mark.parametrize('before,after', [
    ('footer{text-align:center}', 'footer{}'),
    ('@media(max-width:360px){.value', '@media(max-width:360px){body{font-size:14px}.value'),
    ('@media(max-width:360px){.value', '@media(max-width:360px){.row{padding:12px}.value'),
    (':not([data-theme="dark"])', ''),
])
def test_cascade_regressions_detect_removed_footer_or_changed_narrow_theme_rules(monkeypatch, before, after):
    assert CSS.count(before) == 1
    monkeypatch.setitem(globals(), 'CSS', CSS.replace(before, after))
    with pytest.raises((AssertionError, KeyError)):
        test_effective_palette_and_mobile_metrics_match_the_installed_presentation(320, True, 'dark')


def test_css_escape_whitespace_regression_is_detected():
    broken = CSS.replace('content:"LAST KNOWN · "', 'content:"LAST KNOWN \\00B7 "')
    assert _prefix(broken) == 'LAST KNOWN ·'
    assert _prefix(broken) != _prefix(CSS)
