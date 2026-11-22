"""Explicit review controls; JavaScript never grants green."""
from datetime import datetime
from html import escape
import json
from urllib.parse import urlencode

from sentinel.panel.presentation import _pacific
from sentinel.panel.review_history import condition_label, summarize
from sentinel.panel.review_model import PAGE_SIZE


_REASONS = {
    'BACKEND_SOURCE_UNAVAILABLE': 'A dashboard data source could not be read.',
    'CURRENT_FACT_MISSING': 'The check did not supply current evidence.',
    'ROW_CLOCK_FUTURE': 'The check returned a timestamp ahead of the dashboard clock.',
    'ROW_PROOF_EXPIRED': 'The last verified result expired before a new result was available.',
    'FEED_BOUND_VERDICT_PENDING': 'Market data was awaiting verification.',
    'FEED_PUBLICATION_PIN_REFUSED': 'The market-data publication could not be verified during the read.',
    'FEED_FRONTIER_READ_TIMEOUT': 'Reading the latest market-data session timed out.',
    'FEED_READ_UNAVAILABLE': 'The latest market data could not be read.',
    'FEED_CONTRACT_FAILED': 'The market data did not pass its readiness checks.',
    'WORKER_OBSERVATION_TIMEOUT': 'The dashboard timed out while checking the strategy worker.',
}


def _time(value):
    try:
        moment = datetime.fromisoformat(value) if isinstance(value, str) else value
        label = _pacific(moment)
    except (ValueError, OverflowError):
        label = None
    if not label:
        return 'time unavailable'
    return '<time datetime="'+escape(moment.isoformat(), quote=True)+'">'+escape(label)+'</time>'


def _check_names(keys):
    return ', '.join(dict.fromkeys(condition_label(key) for key in keys))


def _standalone(event):
    details = event['details']
    kind = event['kind']
    if kind == 'ACKNOWLEDGED':
        return 'History acknowledged'
    if kind == 'STARTED':
        return {
            'dashboard': 'Dashboard started or restarted',
            'verifier': 'Verification service started or restarted',
            'database': 'Database restarted',
        }.get(details.get('component'), 'Software started or restarted')
    if details.get('alert_ids'):
        count = len(details['alert_ids'])
        return f'{count} critical notification'+('' if count == 1 else 's')+' recorded for review'
    return str(details.get('reason') or {
        'FAILED': 'A health check reported a failure',
        'RECOVERED': 'A health check recorded a status change',
        'REVIEW': 'A change was recorded for review',
    }.get(kind, 'Health record'))


def _cause(entry):
    for event in reversed(entry.records):
        details = event['details']
        evidence = details.get('evidence')
        stored = evidence.get(entry.key) if isinstance(evidence, dict) else None
        evidence = stored if isinstance(stored, dict) else {}
        code = evidence.get('code')
        if isinstance(code, str) and code in _REASONS:
            return _REASONS[code]
        if entry.key == 'alert_dispatcher' and (
                evidence.get('recovery_phase') == 'ALERT_TRANSPORT'
                or evidence.get('effective_status') == 'fail'):
            return 'The notification sender reported a delivery failure or a retry.'
        if details.get('recovered_before_recording'):
            return 'The dashboard recovered before it could record the interruption.'
        if isinstance(code, str) and code.startswith('FINANCIAL_RECEIPT_'):
            return 'The dashboard could not verify the recorded result.'
        if isinstance(code, str) and code.startswith('OPERATIONAL_COLLECTION_'):
            return 'The dashboard could not refresh its system checks.'
    return 'The recorded check changed status. A more specific cause is unavailable.'


def _summaries(events):
    articles = []
    for entry in summarize(events):
        if not entry.key:
            event = entry.records[0]
            headline = _standalone(event)
            body = '<p>'+_time(event['at'])+'</p>'
        else:
            headline = condition_label(entry.key)
            body = '<p>'+escape(_cause(entry))+'</p>'
            if entry.started_at:
                body += '<p>First recorded '+_time(entry.started_at)+'</p>'
            if entry.recovered_at:
                body += '<p class="review-recovered">Recovery recorded '+_time(entry.recovered_at)+'</p>'
            elif not entry.started_at:
                body += '<p>Earlier status change recorded '+_time(entry.records[0]['at'])+'</p>'
            else:
                body += '<p>Recovery is outside these records or has yet to be recorded.</p>'
        articles.append('<article class="review-incident"><h3>'+escape(headline)+'</h3>'
                        +body+'</article>')
    if not articles and events:
        return '<p>The recorded evidence below provides more detail about these checks.</p>'
    return ''.join(articles)


def _record_details(events, *, key):
    if not events:
        return ''
    labels = {'STARTED': 'Started or restarted', 'FAILED': 'Failure recorded',
              'RECOVERED': 'Status change recorded', 'REVIEW': 'Warning recorded',
              'ACKNOWLEDGED': 'Acknowledgment recorded'}
    items = []
    for event in events:
        detail = event['details']
        checks = detail.get('conditions') or detail.get('previous') or []
        description = _check_names(checks) if checks else _standalone(event)
        body = (_time(event['at'])+' · '+labels.get(event['kind'], 'Health record')
                +' · '+escape(description))
        # The original signed record remains inspectable. Human summaries use
        # only the finite status metadata above.
        if detail:
            body += ('<details><summary>Stored record</summary><pre>'
                     +escape(json.dumps(event, indent=2, sort_keys=True))+'</pre></details>')
        items.append('<li>'+body+'</li>')
    count_text = f'{len(events)} recorded entr'+('y' if len(events) == 1 else 'ies')
    return ('<details data-detail-key="'+key+'"><summary>Recorded evidence ('+count_text
            +')</summary><ol>'+''.join(items)+'</ol></details>')


def _history_url(scope, head, reviewed_head, first):
    query = urlencode(dict(scope=scope, head=head, reviewed_head=reviewed_head, first=first))
    return '/review/history?' + escape(query, quote=True)


def history_document(content, stylesheet):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Health history</title><link rel="stylesheet" href="/static/'+escape(stylesheet, quote=True)
            +'"></head><body><main class="review-page"><h1>Health history</h1>'+content
            +'<p><a href="/#system-details">Return to dashboard</a></p></main></body></html>')


def history_page(events, *, scope, head, reviewed_head, first, stylesheet):
    total = head - reviewed_head
    start = head - first + 1
    end = start + len(events) - 1
    links = []
    for cursor, label in ((first+PAGE_SIZE, 'Newer entries'), (first-PAGE_SIZE, 'Older entries')):
        if reviewed_head < cursor <= head:
            links.append('<a href="'+_history_url(scope, head, reviewed_head, cursor)+'">'+label+'</a>')
    return history_document(f'<p>Showing {start}–{end} of {total} unreviewed entries.</p>'
                            +_summaries(events)+_record_details(events, key='review-history-page')
                            +'<nav aria-label="History pages">'+' · '.join(links)+'</nav>', stylesheet)


def _current_decision(review, current):
    if not current:
        return 'Refresh the dashboard to see current checks before acknowledging.'
    if review.status == 'UNAVAILABLE':
        return 'Health history is unavailable. Refresh before acknowledging.'
    blockers = sorted(set(review.active) | set(review.warnings))
    if blockers:
        return 'Resolve current conditions before acknowledging. Checks needing attention include '+_check_names(blockers)+'.'
    if review.token:
        return 'Current checks are clear. Acknowledge after reviewing the outstanding history.'
    if review.status == 'CLEAN':
        return 'Expected operation. All health history has been reviewed.'
    return 'Refresh the dashboard to get a current review before acknowledging.'


def render(review, *, current=True):
    if review is None:
        return ''
    total = review.head - review.reviewed_head
    outstanding = review.events[:total]
    earlier = review.events[len(outstanding):]
    count = ''
    if total:
        count = '<p>'+str(total)+(' unreviewed entry.' if total == 1 else ' unreviewed entries.')
        if total > PAGE_SIZE and current:
            count += (' Showing the latest '+str(PAGE_SIZE)+'. <a target="_blank" rel="noopener" href="'
                      +_history_url(review.scope, review.head, review.reviewed_head, review.head)
                      +'">Review all '+str(total)+' entries (opens in a new tab)</a>.')
        count += '</p>'
    past = ''
    if earlier:
        past = ('<details data-detail-key="review-earlier"><summary>Previously reviewed history</summary>'
                +_summaries(earlier)+_record_details(earlier, key='review-earlier-evidence')+'</details>')
    action = ''
    if review.token and current:
        action = ('<p>This action records your review of all '+str(total)+' outstanding '
                  +('entry' if total == 1 else 'entries')
                  +'. PAPER results have a separate verification check.</p>'
                  '<button id="review-acknowledge" type="button" data-view-token="'
                  +escape(review.token, quote=True)+'">Acknowledge reviewed history</button>')
    return ('<section id="operator-review" class="review-card" aria-labelledby="review-heading">'
        '<h2 id="review-heading">Health history</h2><p class="review-decision">'
        +escape(_current_decision(review, current))+'</p>'
        +('<p>'+escape(review.detail)+'</p>' if review.detail else '')
        +count+_summaries(outstanding)+_record_details(outstanding, key='review-history')
        +'<p><a href="#system-details">Current checks and recorded alerts</a></p>'
        +action+('<p><small>Last acknowledged '+_time(review.reviewed_at)+'</small></p>' if review.reviewed_at else '')
        +past+'<p id="review-result" role="status" aria-live="polite"></p></section>')

SCRIPT = """<script>
(function(){
  var pending = false;
  var spent = new Set();
  window.syncReviewControl = function() {
    var control = document.getElementById('review-acknowledge');
    if (control) { control.disabled = pending || !control.dataset.viewToken || spent.has(control.dataset.viewToken); }
  };
  document.addEventListener('click', async function(event){
    var button = event.target && event.target.closest('#review-acknowledge');
    if (!button || button.disabled || pending || !button.dataset.viewToken || spent.has(button.dataset.viewToken)) { return; }
    var token = button.dataset.viewToken;
    pending = true;
    spent.add(token);
    button.disabled = true;
    var result = document.getElementById('review-result');
    result.textContent = 'Checking the current state…';
    var controller = new AbortController();
    var timeout = setTimeout(function(){ controller.abort(); }, 15000);
    try {
      var response = await fetch('/review/acknowledge', {
        method:'POST', cache:'no-store', credentials:'same-origin',
        headers:{'Content-Type':'application/json'}, signal:controller.signal,
        body:JSON.stringify({token:token})
      });
      if (!response.ok) { throw new Error('changed'); }
      var reviewed = await response.json();
      if (reviewed.status !== 'CLEAN' || reviewed.head !== reviewed.reviewed_head) {
        throw new Error('acknowledgement not established');
      }
      result.textContent = 'Acknowledgement recorded. Refreshing current status…';
      window.location.reload();
    } catch (_error) {
      result.textContent = 'State changed or is unavailable. Refresh and review again.';
    } finally {
      clearTimeout(timeout);
      pending = false;
      window.syncReviewControl();
    }
  });
})();
</script>"""
