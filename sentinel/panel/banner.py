"""Recover only a failed brand resource, independently of financial evidence."""

MARQUEE_ASSETS = frozenset(
    f'caesars-status-{color}{suffix}.gif'
    for color in ('green', 'amber', 'red')
    for suffix in ('', '-still')
)

BANNER_SCRIPT = r"""
(function(){
  var image = document.querySelector('.brand img[data-banner-src]');
  var fallback = document.querySelector('.brand-fallback');
  if (!image || !fallback) { return; }
  var body = document.body;
  var root = document.documentElement;
  var motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  var states = window.__sentinelMarqueeResources || Object.create(null);
  window.__sentinelMarqueeResources = states;
  var asset, state;
  function unavailable() {
    image.hidden = true;
    fallback.hidden = false;
  }
  function loaded() {
    if (!image.complete || image.naturalWidth === 0) { return; }
    image.hidden = false;
    fallback.hidden = true;
  }
  function inspect() {
    if (state.failed) { unavailable(); return; }
    if (!image.complete || image.naturalWidth !== 0) { return; }
    if (state.recovered) {
      state.failed = true;
      unavailable();
      return;
    }
    // document.open can retain a failed resource for the same URL. Give only
    // that failed resource one new identity; a slow download is left alone.
    state.recovered = true;
    state.url = asset + '?banner-load=' + Date.now().toString(36) + '-' +
      Math.random().toString(36).slice(2,10);
    image.src = state.url;
  }
  function sync() {
    var color = body.dataset.health;
    var known = ['green', 'amber', 'red'].includes(color);
    var disconnected = root.classList.contains('not-current');
    var checking = root.classList.contains('checking-status') || body.dataset.refreshPending === 'true';
    // A stale green must lose its color. Retain dated warnings during a check.
    var unknown = !known || disconnected || (checking && color === 'green');
    var still = unknown || checking || motion.matches;
    var next = '/static/caesars-status-' + (unknown ? 'green' : color) +
      (still ? '-still' : '') + '.gif';
    image.classList.toggle('unknown-sign', unknown);
    if (asset === next) { return; }
    asset = next;
    state = states[asset];
    if (!state || (state.url !== asset &&
        !(typeof state.url === 'string' && state.url.startsWith(asset + '?banner-load=') &&
          /^[a-z0-9-]+$/.test(state.url.slice(asset.length + '?banner-load='.length))))) {
      state = {url:asset, recovered:false, failed:false};
      states[asset] = state;
    }
    if (state.failed) { unavailable(); return; }
    if (image.getAttribute('src') !== state.url) {
      // Do not lend the previous color to a new status while its image decodes.
      image.hidden = true;
      image.src = state.url;
    }
    loaded();
    inspect();
  }
  image.addEventListener('error', inspect);
  image.addEventListener('load', loaded);
  window.addEventListener('pageshow', inspect);
  if (motion.addEventListener) { motion.addEventListener('change', sync); }
  else if (motion.addListener) { motion.addListener(sync); }
  var update = new MutationObserver(sync);
  update.observe(body, {attributes:true, attributeFilter:['data-health','data-refresh-pending']});
  update.observe(root, {attributes:true, attributeFilter:['class']});
  sync();
})();
"""
