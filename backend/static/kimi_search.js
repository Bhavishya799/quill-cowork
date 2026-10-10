/* Kimi-style search UI. Loads BEFORE the main inline script.
 * Intercepts window.WebSocket to see search progress events. */
(function(){
'use strict';

const CHEVRON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="width:11px;height:11px"><path d="M6 9l6 6 6-6"></path></svg>';
const GLOBE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:13px;height:13px"><circle cx="12" cy="12" r="9"></circle><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"></path></svg>';
const CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L19 7"></path></svg>';
const XMARK = '<svg viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="3.5" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"></path></svg>';

const state = {
  enabled: true,
  configured: false,
  cards: {},   // call_id -> {el, query, results, open}
};


// ============================================================
// 1. WebSocket constructor override - runs synchronously, before
//    the main inline script creates its WebSocket.
// ============================================================
(function installWSHook(){
  const OrigWS = window.WebSocket;
  if (!OrigWS || OrigWS._quillPatched) return;

  function dispatch(ev){
    let d;
    try { d = JSON.parse(ev.data); } catch(_){ return; }
    if (!d || typeof d !== 'object') return;
    if (d.type === 'search_start')   { try { onSearchStart(d); }   catch(e){ console.warn('[search]', e); } }
    else if (d.type === 'search_results') { try { onSearchResults(d); } catch(e){ console.warn('[search]', e); } }
  }

  function Wrapped(url, protocols){
    const inst = new OrigWS(url, protocols);

    let _onmessage = null;
    Object.defineProperty(inst, 'onmessage', {
      configurable: true,
      get(){ return _onmessage; },
      set(fn){
        if (typeof fn !== 'function'){ _onmessage = fn; return; }
        _onmessage = function(ev){
          try { dispatch(ev); } catch(e){}
          return fn.call(this, ev);
        };
      },
    });

    const _add = inst.addEventListener.bind(inst);
    inst.addEventListener = function(type, listener, opts){
      if (type === 'message' && typeof listener === 'function'){
        const wrapped = function(ev){
          try { dispatch(ev); } catch(e){}
          return listener.call(this, ev);
        };
        return _add(type, wrapped, opts);
      }
      return _add(type, listener, opts);
    };

    return inst;
  }

  Wrapped.prototype = OrigWS.prototype;
  Wrapped.CONNECTING = OrigWS.CONNECTING;
  Wrapped.OPEN = OrigWS.OPEN;
  Wrapped.CLOSING = OrigWS.CLOSING;
  Wrapped.CLOSED = OrigWS.CLOSED;
  Wrapped._quillPatched = true;

  window.WebSocket = Wrapped;
  console.log('[search] WebSocket intercepted');
})();


// ============================================================
// 2. Styles
// ============================================================
function ensureStyles(){
  if (document.getElementById('kimi-search-css')) return;
  const s = document.createElement('style');
  s.id = 'kimi-search-css';
  s.textContent = `
.search-activity-host{width:100%;max-width:720px;margin:0 auto;padding:0 24px 8px;display:flex;flex-direction:column;gap:10px}
.search-card{border:1px solid #E6E1D7;background:#FCFBF8;border-radius:12px;
  padding:0;overflow:hidden;font:400 13px Geist,sans-serif;
  animation:qc-in .2s ease-out}
.search-head{display:flex;align-items:center;gap:8px;padding:10px 12px;cursor:pointer;user-select:none}
.search-head:hover{background:#F6F3ED}
.search-spinner{width:13px;height:13px;border:2px solid #DED9CE;border-top-color:#2C6B47;
  border-radius:50%;animation:search-spin .8s linear infinite;flex:none}
@keyframes search-spin{to{transform:rotate(360deg)}}
.search-check{width:14px;height:14px;border-radius:50%;background:#4F7A5A;
  display:flex;align-items:center;justify-content:center;flex:none}
.search-check svg{width:8px;height:8px}
.search-q{flex:1;color:#23211D;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;font-weight:500}
.search-count{color:#8F8A80;font:400 11.5px 'Geist Mono',monospace;flex:none}
.search-chev{color:#8F8A80;flex:none;transition:transform .15s}
.search-card.open .search-chev{transform:rotate(180deg)}
.search-body{display:none;border-top:1px solid #ECE8E0;padding:10px 12px;background:#FFFFFF}
.search-card.open .search-body{display:block}
.search-loading{font:400 12px Geist,sans-serif;color:#8F8A80;padding:4px 0}
.search-source{display:flex;gap:8px;padding:8px 0;border-bottom:1px solid #F6F3ED}
.search-source:last-child{border-bottom:none}
.search-favicon{width:18px;height:18px;flex:none;border-radius:4px;
  background:#F2EFE8;display:flex;align-items:center;justify-content:center;
  font:600 8px Geist,sans-serif;color:#6A655C}
.search-src-body{flex:1;min-width:0}
.search-src-title{font:500 12.5px Geist,sans-serif;color:#2E4A78;
  text-decoration:none;display:block;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-bottom:2px}
.search-src-title:hover{text-decoration:underline}
.search-src-snippet{font:400 11.5px/1.4 Geist,sans-serif;color:#6A655C;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.search-src-domain{font:400 10.5px 'Geist Mono',monospace;color:#9C978D;margin-top:2px}
`;
  document.head.appendChild(s);
}


// ============================================================
// 3. Card host - appended to #stream so renderStream() never wipes it
// ============================================================
function getHost(){
  let host = document.getElementById('search-activity');
  if (host) return host;
  const stream = document.getElementById('stream');
  if (!stream) return null;
  host = document.createElement('div');
  host.id = 'search-activity';
  host.className = 'search-activity-host';
  stream.appendChild(host);
  return host;
}


// ============================================================
// 4. Card rendering
// ============================================================
function esc(s){
  return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
}

function domainOf(url){
  try { return new URL(url).hostname.replace(/^www\./, ''); }
  catch(_){ return url || ''; }
}

function onSearchStart(d){
  console.log('[search] search_start', d.query);
  ensureStyles();
  const host = getHost();
  if (!host) return;
  const cid = d.call_id;
  if (document.getElementById('sc-' + cid)) return;

  const el = document.createElement('div');
  el.className = 'search-card open';
  el.id = 'sc-' + cid;
  el.innerHTML =
    '<div class="search-head">' +
      '<span class="search-spinner"></span>' +
      '<span class="search-q">Searching: ' + esc(d.query) + '</span>' +
      '<span class="search-count" id="cc-' + cid + '"></span>' +
      '<span class="search-chev">' + CHEVRON + '</span>' +
    '</div>' +
    '<div class="search-body" id="cb-' + cid + '">' +
      '<div class="search-loading">Loading results\u2026</div>' +
    '</div>';

  host.appendChild(el);
  el.querySelector('.search-head').addEventListener('click', function(){
    el.classList.toggle('open');
  });

  state.cards[cid] = { el: el, query: d.query, results: [] };
  console.log('[search] card created', cid, d.query);
}

function onSearchResults(d){
  console.log('[search] search_results', d.call_id, (d.results || []).length);
  const c = state.cards[d.call_id];
  if (!c || !c.el) return;
  const el = c.el;

  // Spinner -> checkmark or X
  const head = el.querySelector('.search-head');
  const sp = head.querySelector('.search-spinner');
  if (sp){
    const ok = d.ok !== false;
    const mark = document.createElement('span');
    mark.className = 'search-check';
    mark.style.background = ok ? '#4F7A5A' : '#B4574A';
    mark.innerHTML = ok ? CHECK : XMARK;
    sp.replaceWith(mark);
  }

  const count = el.querySelector('.search-count');
  const body = el.querySelector('.search-body');
  if (!body) return;

  if (d.ok === false){
    count.textContent = 'error';
    body.innerHTML = '<div class="search-loading" style="color:#8A2D22">' +
      esc(d.error || 'Search failed') + '</div>';
    return;
  }

  const list = (d.results || []).slice(0, 5);
  if (list.length === 0){
    count.textContent = '0 results';
    body.innerHTML = '<div class="search-loading">No results returned.</div>';
    return;
  }

  count.textContent = list.length + ' source' + (list.length === 1 ? '' : 's');
  body.innerHTML = list.map(function(r){
    const dom = domainOf(r.url);
    return '<div class="search-source">' +
      '<span class="search-favicon">' + esc((dom.slice(0, 2) || '??').toUpperCase()) + '</span>' +
      '<div class="search-src-body">' +
        '<a class="search-src-title" href="' + esc(r.url) + '" target="_blank" rel="noopener">' + esc(r.title || dom) + '</a>' +
        '<div class="search-src-snippet">' + esc(r.snippet || '') + '</div>' +
        '<div class="search-src-domain">' + esc(dom) + '</div>' +
      '</div>' +
    '</div>';
  }).join('');
  console.log('[search] card updated', d.call_id, list.length, d.backend || '');
}


// ============================================================
// 5. Toggle pill in composer
// ============================================================
function injectToggle(){
  const modeBtn = document.getElementById('btn-mode');
  if (!modeBtn || !modeBtn.parentNode) return false;
  if (document.getElementById('btn-search')) return true;

  const btn = document.createElement('button');
  btn.id = 'btn-search';
  btn.className = 'composer-btn wide';
  btn.title = 'Toggle web search';
  btn.innerHTML = GLOBE + '<span id="search-label">Search on</span>';
  modeBtn.parentNode.insertBefore(btn, modeBtn.nextSibling);

  btn.addEventListener('click', async function(){
    const next = !state.enabled;
    try {
      const r = await fetch('/search/toggle', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ enabled: next })
      });
      const d = await r.json();
      state.enabled = !!d.enabled;
      renderToggle();
    } catch(e){
      console.warn('[search] toggle failed', e);
    }
  });

  renderToggle();
  return true;
}

function renderToggle(){
  const btn = document.getElementById('btn-search');
  const label = document.getElementById('search-label');
  if (!btn || !label) return;
  if (!state.configured){
    btn.style.cssText = 'border-color:#E8D5D1;color:#8A2D22;opacity:.6';
    label.textContent = 'Search off';
    btn.title = 'Web search is not configured';
    return;
  }
  if (state.enabled){
    btn.style.cssText = 'border-color:#B8D9C6;color:#2C6B47';
    label.textContent = 'Search on';
  } else {
    btn.style.cssText = 'border-color:#E0DACE;color:#8F8A80';
    label.textContent = 'Search off';
  }
}

async function loadStatus(){
  try {
    const r = await fetch('/search/status');
    const d = await r.json();
    state.enabled = !!d.enabled;
    state.configured = !!d.configured;
    renderToggle();
    console.log('[search] status', state);
  } catch(e){
    console.warn('[search] status failed', e);
  }
}


// ============================================================
// 6. Boot
// ============================================================
function ready(fn){
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
  else fn();
}

ready(function(){
  injectToggle();
  loadStatus();
  setInterval(injectToggle, 1500);
  console.log('[search] ready');
});

window.KimiSearch = {
  isEnabled: function(){ return state.enabled; },
  getCards: function(){ return state.cards; },
};
})();
