"""add_theme_dock_rename.py - three UI additions.

1. Search dock: search cards move to a fixed panel that doesn't shift
   when new messages arrive. Only the latest search is shown.

2. Dark mode: black + yellow theme with a toggle in the composer.
   Persists in localStorage.

3. Rename chat: pencil icon on each chat row, inline edit, PATCH to
   /chats/{id} if the endpoint is available.

Idempotent. Run from D:\\Quill-Cowork:  python add_theme_dock_rename.py
"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).parent.resolve()
STATIC = ROOT / "backend" / "static"
HTML = STATIC / "index.html"
KIMI = STATIC / "kimi_search.js"

for p in (HTML, KIMI):
    if not p.exists():
        print(f"ERROR: {p} not found")
        sys.exit(1)

_log = []
def note(msg, kind="ok"):
    _log.append((msg, kind))
    tag = {"ok": "[OK]  ", "skip": "[SKIP]", "warn": "[WARN]"}.get(kind, "[?]   ")
    print(f"{tag} {msg}")


# =====================================================================
# 1. CSS: dark theme + search dock + rename UI
# =====================================================================
src = HTML.read_text(encoding="utf-8")

CSS_ADD = """
/* =========================================================
   Dark theme (black + yellow)
   ========================================================= */
:root[data-theme="dark"]{
  --paper:#0D0C09;
  --sidebar:#14120E;
  --border:#2A2519;
  --border-2:#221E15;
  --border-3:#332D20;
  --border-4:#2F2A1D;
  --ink:#F0E9CE;
  --ink-2:#BDB595;
  --ink-3:#9C9480;
  --ink-4:#807A6A;
  --ink-5:#65604F;
  --ink-6:#4E4A3E;
  --link:#F5C842;
  --warn:#F5B800;
  --ok:#B8D86B;
  --err:#E86A5A;
  --card:#1A1712;
  --card-2:#1F1B14;
  --card-3:#262116;
  --chip:#2A2519;
  --hover:#2E2818;
}
:root[data-theme="dark"] body{background:var(--paper);color:var(--ink)}
:root[data-theme="dark"] .sb-logo{background:#F5C842}
:root[data-theme="dark"] .sb-logo svg{stroke:#0D0C09}
:root[data-theme="dark"] .btn-new,
:root[data-theme="dark"] .composer,
:root[data-theme="dark"] .perm-card,
:root[data-theme="dark"] .model-dropdown,
:root[data-theme="dark"] .profile-modal{
  background:var(--card);border-color:var(--border-3);
}
:root[data-theme="dark"] .sb-search{background:#1E1A12}
:root[data-theme="dark"] .msg-user-bubble{background:#221E15;color:var(--ink)}
:root[data-theme="dark"] .chat-row.active{background:#2A2519}
:root[data-theme="dark"] .msg-user-file,
:root[data-theme="dark"] .attachment,
:root[data-theme="dark"] .perm-target,
:root[data-theme="dark"] .step-target{background:var(--chip);border-color:var(--border-3)}
:root[data-theme="dark"] .composer-send{background:#F5C842}
:root[data-theme="dark"] .composer-send svg{stroke:#0D0C09}
:root[data-theme="dark"] .composer-send:hover{background:#E0B53A}
:root[data-theme="dark"] .composer-send[disabled]{background:#3A342A}
:root[data-theme="dark"] .composer-btn,
:root[data-theme="dark"] .perm-btn,
:root[data-theme="dark"] .profile-btn{
  background:var(--card);border-color:var(--border-3);color:var(--ink-2);
}
:root[data-theme="dark"] .composer-btn:hover,
:root[data-theme="dark"] .perm-btn:hover,
:root[data-theme="dark"] .profile-btn:hover{background:var(--hover);color:var(--ink)}
:root[data-theme="dark"] .perm-btn.primary,
:root[data-theme="dark"] .profile-btn.primary{
  background:#F5C842;color:#0D0C09;border-color:#F5C842;
}
:root[data-theme="dark"] .perm-btn.primary:hover,
:root[data-theme="dark"] .profile-btn.primary:hover{background:#E0B53A}
:root[data-theme="dark"] a{color:var(--link)}
:root[data-theme="dark"] .blk-code{background:#16130E;color:#F0E9CE}
:root[data-theme="dark"] .search-card{background:#1A1712;border-color:#332D20}
:root[data-theme="dark"] .search-head:hover{background:#221E15}
:root[data-theme="dark"] .search-body{background:#1F1B14;border-color:#2A2519}
:root[data-theme="dark"] .search-src-title{color:#F5C842}
:root[data-theme="dark"] .search-src-snippet{color:#BDB595}
:root[data-theme="dark"] .search-src-domain{color:#807A6A}
:root[data-theme="dark"] .search-favicon{background:#2A2519;color:#BDB595}
:root[data-theme="dark"] .search-source{border-color:#221E15}
:root[data-theme="dark"] .search-q{color:#F0E9CE}
:root[data-theme="dark"] .search-count{color:#807A6A}
:root[data-theme="dark"] .search-check{background:#F5C842}
:root[data-theme="dark"] .search-check svg{stroke:#0D0C09}
:root[data-theme="dark"] .perm-dot{background:#F5C842}
:root[data-theme="dark"] .conn-badge{background:var(--card);border-color:var(--border-3);color:var(--ink-2)}
:root[data-theme="dark"] .conn-toggle.off{background:#3A342A}
:root[data-theme="dark"] .conn-toggle.on{background:#F5C842}
:root[data-theme="dark"] .conn-toggle.on .knob{background:#0D0C09}
:root[data-theme="dark"] .sb-avatar{background:#F5C842;color:#0D0C09}
:root[data-theme="dark"] .mic-live{color:var(--ink-2)}
:root[data-theme="dark"] .model-item.selected{background:#221E15}
:root[data-theme="dark"] .model-item:hover{background:#1E1A12}
:root[data-theme="dark"] input,
:root[data-theme="dark"] textarea{color:var(--ink)}
:root[data-theme="dark"] .profile-row input{background:var(--card);border-color:var(--border-3)}
:root[data-theme="dark"] ::-webkit-scrollbar-thumb{background:#3A342A}
:root[data-theme="dark"] .main-header{border-color:var(--border-2)}
:root[data-theme="dark"] .sb-brand{border-color:var(--border)}

/* =========================================================
   Search dock (fixed panel, no scroll drift)
   ========================================================= */
#search-dock{
  position:absolute;
  top:64px;
  right:20px;
  width:380px;
  max-height:calc(100vh - 240px);
  overflow-y:auto;
  overflow-x:hidden;
  display:flex;
  flex-direction:column;
  gap:8px;
  z-index:20;
  pointer-events:none;
  scrollbar-width:thin;
}
#search-dock > *{pointer-events:auto}
main{position:relative}
@media (max-width: 1000px){
  #search-dock{
    position:static;
    width:auto;
    margin:8px 16px;
    max-height:none;
  }
}

/* =========================================================
   Chat rename UI
   ========================================================= */
.chat-rename{
  width:20px;height:20px;flex:none;border:none;background:transparent;
  border-radius:4px;color:var(--ink-4);display:none;align-items:center;
  justify-content:center;padding:0;transition:background .12s,color .12s;
}
.chat-row:hover .chat-rename,
.chat-row.active .chat-rename{display:flex}
.chat-rename:hover{background:#FFFFFF;color:var(--ink)}
:root[data-theme="dark"] .chat-rename:hover{background:var(--hover)}
.chat-rename svg{width:11px;height:11px}
.chat-row-input{
  flex:1;min-width:0;border:1px solid var(--border-3);border-radius:6px;
  background:#FFFFFF;font:400 13.5px Geist,sans-serif;color:var(--ink);
  padding:3px 6px;outline:none;
}
.chat-row-input:focus{border-color:#F5C842}
:root[data-theme="dark"] .chat-row-input{background:var(--card);color:var(--ink)}

/* =========================================================
   Theme toggle button
   ========================================================= */
#btn-theme svg{width:15px;height:15px}
:root[data-theme="dark"] #btn-theme{color:#F5C842;border-color:#4A3F1A}
:root[data-theme="dark"] #btn-theme:hover{background:#2A2519}
"""

if "Dark theme (black + yellow)" not in src:
    if "</style>" not in src:
        note("index.html: no </style> anchor", "warn")
    else:
        src = src.replace("</style>", CSS_ADD + "\n</style>", 1)
        note("index.html: dark theme + dock + rename CSS")
else:
    note("index.html: CSS already present", "skip")


# =====================================================================
# 2. Add #search-dock element in main (sibling of #stream)
# =====================================================================
if 'id="search-dock"' not in src:
    anchor = '    <div id="stream">'
    if anchor in src:
        src = src.replace(
            anchor,
            '    <div id="search-dock"></div>\n' + anchor, 1,
        )
        note("index.html: <div id=\"search-dock\"> added")
    else:
        note("index.html: #stream anchor not found", "warn")
else:
    note("index.html: #search-dock already present", "skip")


# =====================================================================
# 3. Theme toggle button in composer
# =====================================================================
if 'id="btn-theme"' not in src:
    # Insert after the search toggle button (which is added by kimi_search.js
    # dynamically, so we anchor on btn-mode which is in the HTML)
    anchor = '<button class="composer-btn wide" id="btn-mode" title="Permission mode">'
    if anchor in src:
        # Find the end of the btn-mode block
        end_anchor = 'Ask first</span>\n          </button>'
        if end_anchor in src:
            insertion = (
                '\n          <button class="composer-btn" id="btn-theme" '
                'title="Toggle dark mode">\n'
                '            <svg viewBox="0 0 24 24" fill="none" '
                'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
                'stroke-linejoin="round"><circle cx="12" cy="12" r="4"></circle>'
                '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path></svg>\n'
                '          </button>'
            )
            src = src.replace(end_anchor, end_anchor + insertion, 1)
            note("index.html: theme toggle button added to composer")
        else:
            note("index.html: btn-mode end anchor not found", "warn")
    else:
        note("index.html: btn-mode anchor not found", "warn")
else:
    note("index.html: theme button already present", "skip")


# =====================================================================
# 4. Rename button in chat row rendering
# =====================================================================
old_row = """  return '<div class="chat-row' + active + '" data-chat="' + c.id + '">' +
      '<span class="chat-row-title">' + esc(c.title) + '</span>' + running +
      '<button class="chat-delete" data-chat-delete="' + c.id + '" title="Delete chat">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"></path></svg>' +
      '</button>' +
    '</div>';"""

new_row = """  return '<div class="chat-row' + active + '" data-chat="' + c.id + '">' +
      '<span class="chat-row-title" data-chat-title="' + c.id + '">' + esc(c.title) + '</span>' + running +
      '<button class="chat-rename" data-chat-rename="' + c.id + '" title="Rename chat">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg>' +
      '</button>' +
      '<button class="chat-delete" data-chat-delete="' + c.id + '" title="Delete chat">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"></path></svg>' +
      '</button>' +
    '</div>';"""

if 'data-chat-rename' not in src:
    if old_row in src:
        src = src.replace(old_row, new_row, 1)
        note("index.html: rename button in chat row")
    else:
        note("index.html: chat row markup differs; check manually", "warn")
else:
    note("index.html: rename button already present", "skip")


# =====================================================================
# 5. Rename click handler
# =====================================================================
if "function startRename" not in src:
    anchor = "/* ---------- Rendering ---------- */"
    if anchor in src:
        block = """/* ---------- Chat rename ---------- */
function startRename(chatId){
  const row = document.querySelector('[data-chat="' + chatId + '"]');
  if (!row) return;
  const span = row.querySelector('[data-chat-title]');
  if (!span) return;
  const chat = state.chats.find(function(c){ return c.id === chatId; });
  if (!chat) return;

  const input = document.createElement('input');
  input.className = 'chat-row-input';
  input.value = chat.title || 'New task';
  input.maxLength = 80;
  span.replaceWith(input);
  input.focus();
  input.select();

  let done = false;

  function commit(){
    if (done) return;
    done = true;
    const newTitle = (input.value || '').trim() || 'New task';
    chat.title = newTitle;
    const newSpan = document.createElement('span');
    newSpan.className = 'chat-row-title';
    newSpan.setAttribute('data-chat-title', chatId);
    newSpan.textContent = newTitle;
    if (input.parentNode) input.replaceWith(newSpan);
    try {
      fetch('/chats/' + encodeURIComponent(chatId), {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ title: newTitle })
      }).catch(function(){});
    } catch(e){}
    renderHeader();
    renderChatList();
  }

  function cancel(){
    if (done) return;
    done = true;
    const newSpan = document.createElement('span');
    newSpan.className = 'chat-row-title';
    newSpan.setAttribute('data-chat-title', chatId);
    newSpan.textContent = chat.title || 'New task';
    if (input.parentNode) input.replaceWith(newSpan);
    renderChatList();
  }

  input.addEventListener('keydown', function(e){
    if (e.key === 'Enter'){ e.preventDefault(); commit(); }
    else if (e.key === 'Escape'){ e.preventDefault(); cancel(); }
  });
  input.addEventListener('blur', function(){ commit(); });
  input.addEventListener('click', function(e){ e.stopPropagation(); });
}

"""
        src = src.replace(anchor, block + anchor, 1)
        note("index.html: startRename() function added")
    else:
        note("index.html: Rendering anchor not found", "warn")
else:
    note("index.html: startRename already present", "skip")


# =====================================================================
# 6. Rename click delegation
# =====================================================================
if "[data-chat-rename]" not in src:
    anchor = """  const delChat = closest('[data-chat-delete]');
  if (delChat){
    deleteChat(delChat.getAttribute('data-chat-delete'));
    return;
  }"""
    if anchor in src:
        insertion = """  const renChat = closest('[data-chat-rename]');
  if (renChat){
    startRename(renChat.getAttribute('data-chat-rename'));
    return;
  }
""" + anchor
        src = src.replace(anchor, insertion, 1)
        note("index.html: rename click handler wired")
    else:
        note("index.html: delete chat handler anchor not found", "warn")
else:
    note("index.html: rename handler already wired", "skip")


# =====================================================================
# 7. Theme toggle JS + boot hook
# =====================================================================
if "function applyTheme" not in src:
    anchor = "/* ---------- Boot ---------- */"
    if anchor in src:
        block = """/* ---------- Theme ---------- */
const THEME_KEY = 'quill.theme';

function applyTheme(theme){
  const root = document.documentElement;
  if (theme === 'dark'){
    root.setAttribute('data-theme', 'dark');
  } else {
    root.removeAttribute('data-theme');
  }
  try { localStorage.setItem(THEME_KEY, theme); } catch(e){}
  const btn = document.getElementById('btn-theme');
  if (btn){
    btn.title = theme === 'dark' ? 'Switch to light' : 'Switch to dark';
  }
}

function toggleTheme(){
  const cur = document.documentElement.getAttribute('data-theme') === 'dark'
    ? 'dark' : 'light';
  applyTheme(cur === 'dark' ? 'light' : 'dark');
}

function initTheme(){
  let saved = 'light';
  try { saved = localStorage.getItem(THEME_KEY) || 'light'; } catch(e){}
  applyTheme(saved);
  const btn = document.getElementById('btn-theme');
  if (btn && !btn._wired){
    btn._wired = true;
    btn.addEventListener('click', toggleTheme);
  }
}

"""
        src = src.replace(anchor, block + anchor, 1)
        note("index.html: theme JS added")
    else:
        note("index.html: Boot anchor not found", "warn")
else:
    note("index.html: theme JS already present", "skip")


# Call initTheme at boot
if "initTheme();" not in src:
    anchor = "loadProfile();"
    if anchor in src:
        src = src.replace(anchor, anchor + "\ninitTheme();", 1)
        note("index.html: initTheme() wired into boot")
    else:
        note("index.html: loadProfile() anchor not found", "warn")

# Persist theme across reloads by ensuring the attribute is set ASAP
if "<script>document.documentElement.setAttribute" not in src:
    anchor = "</head>"
    if anchor in src:
        inline = (
            '<script>(function(){try{var t=localStorage.getItem("quill.theme");'
            'if(t==="dark")document.documentElement.setAttribute("data-theme","dark");}'
            'catch(e){}})();</script>\n'
        )
        src = src.replace(anchor, inline + anchor, 1)
        note("index.html: anti-flash theme script added")


HTML.write_text(src, encoding="utf-8")


# =====================================================================
# 8. kimi_search.js: use #search-dock instead of #stream
# =====================================================================
ksrc = KIMI.read_text(encoding="utf-8")
orig = ksrc

old_host = """function getHost(){
  let host = document.getElementById('search-activity');
  if (host) return host;
  const stream = document.getElementById('stream');
  if (!stream) return null;
  host = document.createElement('div');
  host.id = 'search-activity';
  host.className = 'search-activity-host';
  stream.appendChild(host);
  return host;
}"""

new_host = """function getHost(){
  return document.getElementById('search-dock');
}"""

if old_host in ksrc:
    ksrc = ksrc.replace(old_host, new_host, 1)
    note("kimi_search.js: getHost returns #search-dock")
elif "getElementById('search-dock')" in ksrc:
    note("kimi_search.js: already using #search-dock", "skip")
else:
    note("kimi_search.js: getHost anchor not found; check manually", "warn")

# Clear dock on new search (show only the latest card)
old_start = """function onSearchStart(d){
  console.log('[search] search_start', d.query);
  ensureStyles();
  const host = getHost();
  if (!host) return;
  const cid = d.call_id;"""

new_start = """function onSearchStart(d){
  console.log('[search] search_start', d.query);
  ensureStyles();
  const host = getHost();
  if (!host) return;
  host.innerHTML = '';
  const cid = d.call_id;"""

if old_start in ksrc:
    ksrc = ksrc.replace(old_start, new_start, 1)
    note("kimi_search.js: dock cleared on new search")

if ksrc != orig:
    KIMI.write_text(ksrc, encoding="utf-8")


# =====================================================================
# 9. Verify
# =====================================================================
print()
print("=" * 60)
print("Verification")
print("=" * 60)

html_final = HTML.read_text(encoding="utf-8")
kimi_final = KIMI.read_text(encoding="utf-8")

checks = [
    ("index.html has dark theme CSS", "Dark theme (black + yellow)" in html_final),
    ("index.html has #search-dock element", 'id="search-dock"' in html_final),
    ("index.html has theme button", 'id="btn-theme"' in html_final),
    ("index.html has rename handler", "function startRename" in html_final),
    ("index.html has data-chat-rename", "data-chat-rename" in html_final),
    ("index.html has applyTheme", "function applyTheme" in html_final),
    ("kimi_search.js uses search-dock", "getElementById('search-dock')" in kimi_final),
]
for label, ok in checks:
    print(f"  [{'OK  ' if ok else 'MISS'}] {label}")

# JS sanity — make sure file still loads in node-ish terms
# Just check balanced braces approximately
for name, text in (("index.html", html_final), ("kimi_search.js", kimi_final)):
    opens = text.count("{")
    closes = text.count("}")
    status = "balanced" if opens == closes else f"IMBALANCE ({opens} vs {closes})"
    print(f"  [{name} braces] {status}")

print()
print("=" * 60)
print(f"Summary: {sum(1 for _, k in _log if k == 'ok')} applied, "
      f"{sum(1 for _, k in _log if k == 'skip')} skipped, "
      f"{sum(1 for _, k in _log if k == 'warn')} warnings")
print("=" * 60)
for m, k in _log:
    if k == "warn":
        print(f"  [WARN] {m}")
print()
print("Next:")
print("  1. Restart: python backend\\run.py")
print("  2. Hard-reload: Ctrl+Shift+R")
print("  3. Click the sun icon in the composer to toggle dark mode.")
print("  4. Ask a search question. The card should appear in the")
print("     top-right dock and NOT move when you send another message.")
print("  5. Hover a chat in the sidebar. Click the pencil. Edit, Enter.")
print("=" * 60)