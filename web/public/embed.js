(function () {
  var script = document.currentScript ||
    document.querySelector('script[data-bot-src]');
  if (!script) return;

  var botSrc    = script.getAttribute('data-bot-src');
  var openIcon  = script.getAttribute('data-open-icon') || '';
  var closeIcon = script.getAttribute('data-close-icon') || openIcon;
  var draggable = script.getAttribute('data-drag') === 'true';

  // ── 弹层 iframe ──────────────────────────────────────────────
  var iframe = document.createElement('iframe');
  iframe.src = botSrc;
  iframe.allow = 'microphone';
  Object.assign(iframe.style, {
    display:      'none',
    position:     'fixed',
    bottom:       '90px',
    right:        '24px',
    width:        '380px',
    height:       '600px',
    border:       'none',
    borderRadius: '12px',
    boxShadow:    '0 8px 32px rgba(0,0,0,.18)',
    zIndex:       '2147483646',
    background:   '#fff',
  });

  // ── 悬浮按钮 ─────────────────────────────────────────────────
  var btn = document.createElement('button');
  Object.assign(btn.style, {
    position:     'fixed',
    bottom:       '24px',
    right:        '24px',
    width:        '56px',
    height:       '56px',
    borderRadius: '50%',
    border:       'none',
    cursor:       'pointer',
    padding:      '0',
    background:   'transparent',
    boxShadow:    '0 4px 16px rgba(0,0,0,.2)',
    zIndex:       '2147483647',
    overflow:     'hidden',
  });
  var img = document.createElement('img');
  img.src = openIcon;
  img.style.cssText = 'width:100%;height:100%;object-fit:cover;';
  btn.appendChild(img);

  // ── 开关逻辑 ─────────────────────────────────────────────────
  var open = false;
  btn.addEventListener('click', function () {
    open = !open;
    iframe.style.display = open ? 'block' : 'none';
    img.src = open ? closeIcon : openIcon;
  });

  // ── 可选拖拽 ─────────────────────────────────────────────────
  if (draggable) {
    var dragging = false, startX, startY, origRight, origBottom;
    btn.addEventListener('mousedown', function (e) {
      dragging = true;
      startX = e.clientX; startY = e.clientY;
      origRight  = parseInt(btn.style.right);
      origBottom = parseInt(btn.style.bottom);
    });
    document.addEventListener('mousemove', function (e) {
      if (!dragging) return;
      var dx = startX - e.clientX, dy = startY - e.clientY;
      btn.style.right  = (origRight  + dx) + 'px';
      btn.style.bottom = (origBottom + dy) + 'px';
      iframe.style.right  = btn.style.right;
      iframe.style.bottom = (parseInt(btn.style.bottom) + 66) + 'px';
    });
    document.addEventListener('mouseup', function () { dragging = false; });
  }

  document.body.appendChild(iframe);
  document.body.appendChild(btn);
})();
