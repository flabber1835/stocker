"""Explicit review controls; JavaScript never grants green."""
from html import escape


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
    def description(event):
        detail=event['details']
        conditions=detail.get('conditions') or detail.get('previous') or []
        text=detail.get('reason') or ', '.join(conditions)
        if detail.get('alert_ids'):
            text=str(len(detail['alert_ids']))+' critical notifications; see System details for recorded reasons'
        return str(text or '')
    items = ''.join('<li>'+escape(event['at'])+' · '+escape({
        'STARTED':'Deployment or restart', 'FAILED':'Failure recorded',
        'RECOVERED':'Condition recovered', 'REVIEW':'Change requiring review',
        'ACKNOWLEDGED':'Acknowledged',
    }[event['kind']])+(' · '+escape(description(event)) if description(event) else '')+'</li>'
        for event in review.events)
    action = ''
    if review.token and current:
        action = ('<button id="review-acknowledge" type="button" data-view-token="'
                  +escape(review.token, quote=True)+'">Acknowledge reviewed state</button>')
    elif review.status in {'FAILED','REVIEW'} and current:
        action = '<p>Resolve active conditions before acknowledging a healthy state.</p>'
    return ('<section id="operator-review" class="review-card" aria-label="Operator review">'
        '<div class="label">Health history</div><p>'+escape(text)+'</p>'
        +('<p>'+escape(review.detail)+'</p>' if review.detail else '')
        +'<small>Clean interval begins: '+escape(stamp)+'</small>'
        '<details data-detail-key="review-history"><summary>Recent recorded history</summary><ol>'
        +items+'</ol></details>'+action+'<p id="review-result" role="status"></p></section>'
        +SCRIPT)


SCRIPT = """<script>
(function(){
  var button = document.getElementById('review-acknowledge');
  if (!button) { return; }
  button.addEventListener('click', async function(){
    button.disabled = true;
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
