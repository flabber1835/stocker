"""Recover only a failed brand resource, independently of financial evidence."""

BANNER_SCRIPT = r"""
(function(){
  var image = document.querySelector('.brand img[data-banner-src]');
  var fallback = document.querySelector('.brand-fallback');
  if (!image || !fallback) { return; }
  var asset = '/static/caesars-palace-512.png';
  if (image.getAttribute('data-banner-src') !== asset) { return; }
  var state = window.__sentinelBannerResource;
  if (!state || state.asset !== asset || typeof state.url !== 'string' ||
      (state.url !== asset && !/^\/static\/caesars-palace-512\.png\?banner-load=[a-z0-9-]+$/.test(state.url)) ||
      typeof state.recovered !== 'boolean' || typeof state.failed !== 'boolean') {
    state = {asset:asset, url:asset, recovered:false, failed:false};
    window.__sentinelBannerResource = state;
  }
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
  image.addEventListener('error', inspect);
  image.addEventListener('load', loaded);
  window.addEventListener('pageshow', inspect);
  if (state.failed) { unavailable(); return; }
  if (image.getAttribute('src') !== state.url) { image.src = state.url; }
  loaded();
  inspect();
})();
"""
