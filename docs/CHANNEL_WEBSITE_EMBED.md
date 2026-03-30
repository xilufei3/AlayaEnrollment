# 招办网站嵌入接入指南

旧系统（Flowise）自带悬浮气泡嵌入功能。当前系统需要完成三件事才能实现相同效果。

---

## 步骤概览

| 步骤 | 做什么 | 为什么必须做 |
|------|--------|------------|
| 1 | 修改 Nginx 安全头 | 当前配置禁止任何页面将本系统嵌入 iframe |
| 2 | 创建 `embed.js` 脚本 | 当前系统没有内置悬浮气泡脚本，需自行编写 |
| 3 | 招办网站引入脚本 | 完成接入 |

---

## 步骤一：修改 Nginx，允许 iframe 嵌入

**文件：** `infra/nginx/alaya-enrollment.conf`

**原因：** Nginx 默认写了 `X-Frame-Options: DENY` 响应头。浏览器收到该响应头后，无论是招办网站还是其他任何页面，都无法将本系统嵌入 `<iframe>` 中渲染——这是浏览器强制执行的安全策略，与网络连通性无关。

**修改方式（二选一）：**

① 仅允许招办网站嵌入（推荐）：

```nginx
# 改前
add_header X-Frame-Options "DENY" always;

# 改后（将域名/IP 替换为招办网站的实际地址）
add_header X-Frame-Options "ALLOW-FROM http://招办网站IP或域名" always;
```

② 内网场景，允许所有来源嵌入（简单但范围更宽）：

```nginx
# 删除这一整行
# add_header X-Frame-Options "DENY" always;
```

**改完后重新加载 Nginx：**

```bash
docker compose exec nginx nginx -s reload
```

---

## 步骤二：创建 `embed.js` 悬浮气泡脚本

**文件：** `web/public/embed.js`

**原因：** 旧系统使用的是 Flowise 内置的 `iframe.js`，会自动在页面右下角创建悬浮聊天按钮。当前系统是完整的 Next.js 聊天界面，不附带嵌入脚本，需自行编写。

脚本放在 `web/public/` 目录后，Next.js 会将其作为静态文件对外提供，访问路径自动变为：

```
http://<HOST>:8082/zs-ai/embed.js
```

**`web/public/embed.js` 内容：**

```js
(function () {
  var script = document.currentScript ||
    document.querySelector('script[data-bot-src]');
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
```

同时将聊天气泡图标放到 `web/public/ai-chat.png`，它会以
`http://<HOST>:8082/zs-ai/ai-chat.png` 对外提供。

---

## 步骤三：招办网站引入脚本

在招办网站需要显示聊天入口的 HTML 页面中加入以下代码（与旧系统写法几乎相同，替换 HOST 即可）：

```html
<script
  src="http://<HOST>:8082/zs-ai/embed.js"
  data-bot-src="http://<HOST>:8082/zs-ai/"
  data-open-icon="http://<HOST>:8082/zs-ai/ai-chat.png"
  data-close-icon="http://<HOST>:8082/zs-ai/ai-chat.png"
  data-drag="true"
  defer
></script>
```

将 `<HOST>` 替换为部署机的内网 IP（例如 `10.16.18.60`）。

---

## 与旧系统对照

| 项目 | 旧系统（Flowise） | 当前系统 |
|------|-----------------|---------|
| 嵌入脚本地址 | `http://10.16.18.60:3001/iframe.js` | `http://<HOST>:8082/zs-ai/embed.js` |
| 聊天页面地址 | `http://10.16.18.60:3001/chat/flow/xxx` | `http://<HOST>:8082/zs-ai/` |
| `X-Frame-Options` | 允许嵌入 | 默认 DENY，**需步骤一修改** |
| API 鉴权 | 无 | BFF 自动注入，前端无感知 |
| 嵌入脚本来源 | Flowise 内置 | **需步骤二自行创建** |
