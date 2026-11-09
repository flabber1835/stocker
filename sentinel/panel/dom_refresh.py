"""In-place rendering; this helper grants no server or financial currentness."""

SCRIPT = r'''
function reconcileDocument(next) {
  var current = document.querySelector('.wrap');
  var incoming = next.querySelector('.wrap');
  if (!current || !incoming) { throw new Error('Dashboard structure is missing'); }
  function key(node) {
    if (node.nodeType !== 1) { return null; }
    return node.id || (node.hasAttribute('data-detail-key') ? 'detail:'+node.dataset.detailKey : null);
  }
  function copy(node) {
    var value = node.cloneNode(true);
    if (value.nodeType === 1) { value.querySelectorAll('script').forEach(function(item) { item.remove(); }); }
    return value;
  }
  function sameKind(a, b) { return a.nodeType === b.nodeType && a.nodeName === b.nodeName; }
  function update(target, source) {
    if (target.nodeType !== 1) {
      if (target.nodeValue !== source.nodeValue) { target.nodeValue = source.nodeValue; }
      return;
    }
    // These are device-owned controls/images, initialized once for this page.
    if (target.id === 'push-card' || target.id === 'review-result' || target.classList.contains('brand')) { return; }
    var ignore = function(name) {
      return (target.tagName === 'DETAILS' && name === 'open') || name === 'data-review-submitting' ||
        (name === 'disabled' && target.dataset.reviewSubmitting === 'true');
    };
    Array.from(target.attributes).forEach(function(attr) {
      if (!ignore(attr.name) && !source.hasAttribute(attr.name)) { target.removeAttribute(attr.name); }
    });
    Array.from(source.attributes).forEach(function(attr) {
      if (!ignore(attr.name) && target.getAttribute(attr.name) !== attr.value) { target.setAttribute(attr.name, attr.value); }
    });
    var available = Array.from(target.childNodes).filter(function(node) { return node.nodeName !== 'SCRIPT'; });
    var keyed = new Map();
    available.forEach(function(node) { if (key(node)) { keyed.set(key(node), node); } });
    var used = new Set();
    var cursor = target.firstChild;
    Array.from(source.childNodes).forEach(function(node) {
      if (node.nodeName === 'SCRIPT') { return; }
      while (cursor && cursor.nodeName === 'SCRIPT') { cursor = cursor.nextSibling; }
      var identity = key(node);
      var match = identity ? keyed.get(identity) :
        (cursor && !key(cursor) && sameKind(cursor, node) && !used.has(cursor) ? cursor : null);
      if (!match || !sameKind(match, node)) { match = copy(node); }
      if (match !== cursor) { target.insertBefore(match, cursor); }
      used.add(match);
      if (!match.isEqualNode(node)) { update(match, node); }
      cursor = match.nextSibling;
    });
    available.forEach(function(node) { if (!used.has(node)) { node.remove(); } });
  }
  update(current, incoming);
  Array.from(document.body.attributes).forEach(function(attr) {
    if (attr.name.startsWith('data-') && !next.body.hasAttribute(attr.name)) { document.body.removeAttribute(attr.name); }
  });
  Array.from(next.body.attributes).forEach(function(attr) {
    if (attr.name.startsWith('data-') && document.body.getAttribute(attr.name) !== attr.value) {
      document.body.setAttribute(attr.name, attr.value);
    }
  });
  var oldStyle = document.querySelector('head style');
  var newStyle = next.querySelector('head style');
  if (oldStyle && newStyle && oldStyle.textContent !== newStyle.textContent) { oldStyle.textContent = newStyle.textContent; }
  if (document.title !== next.title) { document.title = next.title; }
}
'''.strip()
