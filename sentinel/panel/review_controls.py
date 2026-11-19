"""Explicit review controls; JavaScript never grants green."""
from html import escape
import json
from urllib.parse import urlencode

from sentinel.panel.review_model import PAGE_SIZE


def _items(events, *, evidence=False):
    labels = {'STARTED': 'Deployment or restart', 'FAILED': 'Failure recorded',
              'RECOVERED': 'Condition recovered', 'REVIEW': 'Change requiring review',
              'ACKNOWLEDGED': 'Acknowledged'}
    items = []
    for event in events:
        detail = event['details']
        conditions = detail.get('conditions') or detail.get('previous') or []
        description = detail.get('reason') or ', '.join(conditions)
        if detail.get('alert_ids'):
            description = str(len(detail['alert_ids']))+' critical notifications; see System details for recorded reasons'
        parts = [event['at'], labels[event['kind']]]
        if description:
            parts.append(str(description))
        body = ' · '.join(escape(part) for part in parts)
        if evidence and detail:
            body += ('<details><summary>Recorded evidence</summary><pre>'
                     +escape(json.dumps(detail, indent=2, sort_keys=True))+'</pre></details>')
        items.append('<li>'+body+'</li>')
    return ''.join(items)


def _history_url(scope, head, reviewed_head, first):
    query = urlencode(dict(scope=scope, head=head, reviewed_head=reviewed_head, first=first))
    return '/review/history?' + escape(query, quote=True)


def history_document(content, stylesheet):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Health history</title><link rel="stylesheet" href="/static/'+escape(stylesheet, quote=True)
            +'"></head><body><main><h1>Health history</h1>'+content
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
                            +'<ol start="'+str(start)+'">'+_items(events, evidence=True)+'</ol>'
                            +'<nav aria-label="History pages">'+' · '.join(links)+'</nav>', stylesheet)

def render(review, *, current=True):
    if review is None:
        return ''
    stamp = review.reviewed_at.isoformat() if review.reviewed_at else 'Not yet acknowledged'
    text = {
        'CLEAN': 'Expected operation. No unreviewed incident since acknowledgement.',
        'FAILED': 'An active check is failing. Acknowledgement cannot clear an active failure.',
        'REVIEW': 'Recorded changes or recovered incidents need review. Earlier history is retained.',
        'UNAVAILABLE': 'Review history cannot be read. A clean state cannot be established.',
    }[review.status]
    total = review.head - review.reviewed_head
    count = ''
    if total:
        count = '<p>'+str(total)+(' unreviewed entry.' if total == 1 else ' unreviewed entries.')
        if total > PAGE_SIZE and current:
            count += (' Showing the latest '+str(PAGE_SIZE)+'. <a target="_blank" rel="noopener" href="'
                      +_history_url(review.scope, review.head, review.reviewed_head, review.head)
                      +'">Review all '+str(total)+' entries (opens in a new tab)</a>.')
        count += '</p>'
    action = ''
    if review.token and current:
        action = ('<button id="review-acknowledge" type="button" data-view-token="'
                  +escape(review.token, quote=True)+'">Acknowledge reviewed state</button>')
    elif review.status in {'FAILED','REVIEW'} and current:
        action = '<p>Resolve current conditions before acknowledging a healthy state.</p>'
    return ('<section id="operator-review" class="review-card" aria-labelledby="review-heading">'
        '<h2 id="review-heading">Health history</h2><p>'+escape(text)+'</p>'
        +('<p>'+escape(review.detail)+'</p>' if review.detail else '')
        +count+'<small>Clean interval begins: '+escape(stamp)+'</small>'
        '<details data-detail-key="review-history"><summary>Recent recorded history</summary><ol>'
        +_items(review.events)+'</ol></details><p>Review the <a href="#system-details">current checks and recorded alerts</a> '
        'before acknowledging. This does not verify pending PAPER results.</p>'
        +action+'<p id="review-result" role="status" aria-live="polite"></p></section>')


SCRIPT = """<script>
(function(){
  document.addEventListener('click', async function(event){
    var button = event.target && event.target.closest('#review-acknowledge');
    if (!button || button.disabled || button.dataset.reviewSubmitting === 'true') { return; }
    button.disabled = true;
    button.dataset.reviewSubmitting = 'true';
    var result = document.getElementById('review-result');
    result.textContent = 'Checking the current state…';
    var controller = new AbortController();
    var timeout = setTimeout(function(){ controller.abort(); }, 15000);
    try {
      var response = await fetch('/review/acknowledge', {
        method:'POST', cache:'no-store', credentials:'same-origin',
        headers:{'Content-Type':'application/json'}, signal:controller.signal,
        body:JSON.stringify({token:button.dataset.viewToken})
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
      // A consumed or stale view must never be submitted again from this page.
    }
  });
})();
</script>"""
