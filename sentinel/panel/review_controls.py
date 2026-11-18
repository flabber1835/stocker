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
        action = '<p>Resolve current conditions before acknowledging a healthy state.</p>'
    return ('<section id="operator-review" class="review-card" aria-labelledby="review-heading">'
        '<h2 id="review-heading">Health history</h2><p>'+escape(text)+'</p>'
        +('<p>'+escape(review.detail)+'</p>' if review.detail else '')
        +'<small>Clean interval begins: '+escape(stamp)+'</small>'
        '<details data-detail-key="review-history"><summary>Recent recorded history</summary><ol>'
        +items+'</ol></details><p>Review the <a href="#system-details">current checks and recorded alerts</a> '
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
