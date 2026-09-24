#!/usr/bin/env python3
"""
Patch the bundled Quill Cowork frontend so its DC script talks to the
local FastAPI backend instead of window.claude.complete.

Usage:
    python rebuild_frontend.py "Quill Cowork (1).html" backend/static/index.html
"""
import json
import re
import sys
from pathlib import Path


NEW_DC_SCRIPT = r'''const VERBS = { run_command: 'run a command', edit_file: 'edit a file', read_file: 'read a file', open_url: 'open a website', create_file: 'create a file', delete_file: 'delete a file', use_connector: 'use a connector', send_message: 'send a message', write_file: 'write a file', list_directory: 'list a folder', search_files: 'search files', fetch_page: 'fetch a page', list_notifications: 'list notifications', list_repos: 'list repositories', create_issue: 'create an issue', comment_on_issue: 'comment on an issue', list_issues: 'list issues', list_pull_requests: 'list pull requests', list_commits: 'list commits', mark_all_notifications_read: 'mark notifications read', get_notification_details: 'get notification details' };
const DONE = { run_command: 'Ran', edit_file: 'Edited', read_file: 'Read', open_url: 'Opened', create_file: 'Created', delete_file: 'Deleted', use_connector: 'Searched', send_message: 'Sent', write_file: 'Wrote', list_directory: 'Listed', search_files: 'Searched', fetch_page: 'Fetched', list_notifications: 'Listed', list_repos: 'Listed', create_issue: 'Created', comment_on_issue: 'Commented', list_issues: 'Listed', list_pull_requests: 'Listed', list_commits: 'Listed', mark_all_notifications_read: 'Marked', get_notification_details: 'Read' };
const SPEEDS = { Instant: 100000, Natural: 4, Slow: 1 };

function toBlocks(text) {
  const out = [];
  text.split(/```/).forEach((part, i) => {
    if (i % 2 === 1) {
      const nl = part.indexOf('\n');
      const body = nl >= 0 && /^[\w+-]*$/.test(part.slice(0, nl).trim()) ? part.slice(nl + 1) : part;
      out.push({ isCode: true, text: body.replace(/\n$/, '') });
      return;
    }
    let para = [];
    const flush = () => { if (para.length) { out.push({ isP: true, text: para.join('\n') }); para = []; } };
    part.split('\n').forEach(raw => {
      const line = raw.replace(/\*\*(.+?)\*\*/g, '$1').replace(/`([^`]+)`/g, '$1');
      let m;
      if (!line.trim()) return flush();
      if ((m = line.match(/^\s*#{1,6}\s+(.*)/))) { flush(); out.push({ isH: true, text: m[1] }); }
      else if ((m = line.match(/^\s*[-*•]\s+(.*)/))) { flush(); out.push({ isLi: true, marker: '•', text: m[1] }); }
      else if ((m = line.match(/^\s*(\d+)[.)]\s+(.*)/))) { flush(); out.push({ isLi: true, marker: m[1] + '.', text: m[2] }); }
      else para.push(line);
    });
    flush();
  });
  return out;
}

function humanArgs(args) {
  if (!args) return '';
  if (args.path) return String(args.path);
  if (args.url) return String(args.url);
  if (args.pattern) return String(args.pattern);
  if (args.query) return String(args.query);
  if (args.owner && args.repo) return args.owner + '/' + args.repo;
  try { return JSON.stringify(args); } catch (e) { return String(args); }
}

function newChatId() {
  return 'chat-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
}

class Component extends DCLogic {
  state = {
    chats: [{ id: newChatId(), title: 'New task', msgs: [] }],
    activeId: null,
    draft: '',
    attachments: [],
    phase: 'idle',
    runChat: null,
    mode: null,
    always: [],
    copiedId: null,
    model: 'balanced',
    modelMenu: false,
    connectors: [],
    models: [],
    sidebar: true,
    query: '',
    wsOnline: false,
  };
  taRef = React.createRef();
  fileRef = React.createRef();
  scrollRef = React.createRef();
  uid = 1;
  runId = 0;
  ws = null;
  wsReconnect = null;

  constructor(props) {
    super(props);
    this.state.activeId = this.state.chats[0].id;
  }

  get mode() { return this.state.mode || (this.props.defaultMode === 'Auto-approve' ? 'auto' : 'ask'); }
  get msgs() { const c = this.state.chats.find(c => c.id === this.state.activeId); return c ? c.msgs : []; }

  componentDidMount() {
    const s = this.scrollRef.current; if (s) s.scrollTop = s.scrollHeight;
    this.connectWS();
    this.loadConnectors();
    this.loadSlots();
  }
  componentDidUpdate(pp, ps) {
    const ta = this.taRef.current;
    if (ta) { ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 220) + 'px'; }
    const s = this.scrollRef.current;
    if (s && (ps.activeId !== this.state.activeId || s.scrollHeight - s.scrollTop - s.clientHeight < 160)) s.scrollTop = s.scrollHeight;
  }
  componentWillUnmount() {
    clearInterval(this.timer);
    if (this.wsReconnect) clearTimeout(this.wsReconnect);
    if (this.ws) { try { this.ws.close(); } catch (e) {} }
  }

  connectWS() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
    const host = location.host || 'localhost:8000';
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    try { this.ws = new WebSocket(proto + '//' + host + '/ws'); }
    catch (e) { this.scheduleReconnect(); return; }
    this.ws.onopen = () => this.setState({ wsOnline: true });
    this.ws.onmessage = (ev) => {
      let data; try { data = JSON.parse(ev.data); } catch (e) { return; }
      const chatId = this.state.runChat;
      if (chatId == null) return;
      if (data.type === 'thinking') {
        this.setState({ phase: 'thinking' });
      } else if (data.type === 'confirm_request') {
        this.setState({ phase: 'awaiting' });
        this.push(chatId, {
          role: 'perm',
          tool: data.tool,
          target: humanArgs(data.arguments),
          reason: 'Quill needs your approval to continue.',
          callId: data.call_id,
        });
      } else if (data.type === 'reply') {
        const calls = data.tool_calls || [];
        const self = this;
        calls.forEach(function (c) {
          self.push(chatId, {
            role: 'step',
            ok: true,
            label: (DONE[c.tool] || 'Ran') + ' · ' + c.tool,
            target: humanArgs(c.arguments),
          });
        });
        this.stream(chatId, data.reply || '(empty response)', ++this.runId);
      } else if (data.type === 'error') {
        this.stream(chatId, 'Error: ' + (data.message || 'unknown'), ++this.runId);
      }
    };
    this.ws.onclose = () => { this.ws = null; this.setState({ wsOnline: false }); this.scheduleReconnect(); };
    this.ws.onerror = () => {};
  }
  scheduleReconnect() {
    if (this.wsReconnect) return;
    this.wsReconnect = setTimeout(() => { this.wsReconnect = null; this.connectWS(); }, 2500);
  }

  async loadConnectors() {
    try {
      const r = await fetch('/connectors');
      const d = await r.json();
      const list = (d.connectors || []).map(c => {
        const name = c.name || c.id;
        const mono = name.replace(/[^A-Za-z]/g, '').slice(0, 2) || c.id.slice(0, 2);
        return { id: c.id, name: name, mono: mono, on: true };
      });
      this.setState({ connectors: list });
    } catch (e) {}
  }

  async loadSlots() {
    try {
      const r = await fetch('/models/slots');
      const d = await r.json();
      const slots = d.slots || {};
      const models = Object.keys(slots).map(function (id) {
        const raw = slots[id];
        return {
          id: id,
          name: 'Quill ' + id.charAt(0).toUpperCase() + id.slice(1),
          short: id.charAt(0).toUpperCase() + id.slice(1),
          desc: raw,
          raw: raw,
        };
      });
      this.setState({ models: models, model: d.current_slot || 'balanced' });
    } catch (e) {}
  }

  editChat(chatId, fn) { this.setState(s => ({ chats: s.chats.map(c => c.id === chatId ? Object.assign({}, c, { msgs: fn(c.msgs) }) : c) })); }
  push(chatId, m) { const msg = Object.assign({ id: this.uid++ }, m); this.editChat(chatId, ms => ms.concat([msg])); return msg.id; }
  patch(chatId, id, p) { this.editChat(chatId, ms => ms.map(m => m.id === id ? Object.assign({}, m, p) : m)); }

  stream(chatId, full, my) {
    const id = this.push(chatId, { role: 'assistant', text: '', streaming: true });
    this.setState({ phase: 'streaming' });
    const step = SPEEDS[this.props.streamSpeed] || 4;
    let i = 0;
    clearInterval(this.timer);
    this.timer = setInterval(() => {
      if (my !== this.runId) { clearInterval(this.timer); return; }
      i = Math.min(full.length, i + step);
      const done = i >= full.length;
      this.patch(chatId, id, { text: full.slice(0, i), streaming: !done });
      if (done) { clearInterval(this.timer); this.setState({ phase: 'idle', runChat: null }); }
    }, 16);
  }

  send = () => {
    const text = this.state.draft.trim();
    if (!text || this.state.phase !== 'idle') return;
    const chatId = this.state.activeId;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.push(chatId, { role: 'assistant', text: 'Backend offline. Start the Python server and refresh.' });
      return;
    }
    const files = this.state.attachments.map(f => f.name);
    const msg = { id: this.uid++, role: 'user', text: text, files: files };
    this.setState(s => ({
      draft: '',
      attachments: [],
      modelMenu: false,
      runChat: chatId,
      phase: 'thinking',
      chats: s.chats.map(c => c.id === chatId
        ? Object.assign({}, c, { msgs: c.msgs.concat([msg]), title: c.msgs.length ? c.title : text.slice(0, 48) })
        : c),
    }));
    try { this.ws.send(JSON.stringify({ message: text, session_id: chatId })); }
    catch (e) { this.stream(chatId, 'Failed to send: ' + e.message, ++this.runId); }
  };

  stop = () => {
    this.runId++;
    clearInterval(this.timer);
    const chatId = this.state.runChat;
    if (chatId != null) this.editChat(chatId, ms => ms.map(m => m.role === 'perm' && !m.resolved
      ? Object.assign({}, m, { role: 'step', bad: true, label: 'Cancelled' })
      : (m.streaming ? Object.assign({}, m, { streaming: false }) : m)));
    this.setState({ phase: 'idle', runChat: null });
  };

  retry = () => {
    const chatId = this.state.activeId;
    const msgs = this.msgs;
    let cut = msgs.length;
    while (cut > 0 && msgs[cut - 1].role !== 'user') cut--;
    if (cut === 0) return;
    const lastUser = msgs[cut - 1];
    const kept = msgs.slice(0, cut - 1);
    this.editChat(chatId, () => kept.concat([{ id: this.uid++, role: 'user', text: lastUser.text, files: lastUser.files || [] }]));
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.setState({ runChat: chatId, phase: 'thinking' });
    try { this.ws.send(JSON.stringify({ message: lastUser.text, session_id: chatId })); } catch (e) {}
  };

  decide(chatId, id, kind) {
    const c = this.state.chats.find(c => c.id === chatId);
    const m = c && c.msgs.find(x => x.id === id);
    if (!m) return;
    const label = kind === 'deny' ? 'Denied' : (DONE[m.tool] || 'Done') + (kind === 'always' ? ' · always allowed' : '');
    this.patch(chatId, id, { role: 'step', ok: kind !== 'deny', bad: kind === 'deny', label: label, resolved: true });
    if (kind === 'always') this.setState(s => ({ always: s.always.concat([m.tool]) }));
    if (this.ws && this.ws.readyState === WebSocket.OPEN && m.callId) {
      try { this.ws.send(JSON.stringify({ type: 'confirm_response', call_id: m.callId, approved: kind !== 'deny' })); } catch (e) {}
    }
  }

  newChat = () => {
    const empty = this.state.chats.find(c => c.msgs.length === 0 && c.title === 'New task');
    if (empty) return this.setState({ activeId: empty.id, draft: '' });
    const id = newChatId();
    this.setState(s => ({ chats: [{ id: id, title: 'New task', msgs: [] }].concat(s.chats), activeId: id, draft: '', attachments: [] }));
  };

  renderVals() {
    const { phase, draft, attachments, copiedId, chats, activeId, runChat, query, connectors, model, models } = this.state;
    const msgs = this.msgs;
    const active = chats.find(c => c.id === activeId);
    const lastAsst = msgs.slice().reverse().find(m => m.role === 'assistant');
    const idle = phase === 'idle';
    const items = msgs.map(m => Object.assign({}, m, {
      isUser: m.role === 'user',
      hasFiles: !!(m.files && m.files.length),
      isAssistant: m.role === 'assistant',
      blocks: m.role === 'assistant' ? toBlocks(m.text) : [],
      showActions: m.role === 'assistant' && !m.streaming && idle,
      isLast: lastAsst && lastAsst.id === m.id,
      copyLabel: copiedId === m.id ? 'Copied' : 'Copy',
      onCopy: () => { if (navigator.clipboard) navigator.clipboard.writeText(m.text); this.setState({ copiedId: m.id }); setTimeout(() => this.setState(s => s.copiedId === m.id ? { copiedId: null } : null), 1400); },
      isPermPending: m.role === 'perm' && !m.resolved,
      verb: VERBS[m.tool] || 'use a tool',
      onAllow: () => this.decide(activeId, m.id, 'once'),
      onAlways: () => this.decide(activeId, m.id, 'always'),
      onDeny: () => this.decide(activeId, m.id, 'deny'),
      isStep: m.role === 'step' && this.props.showToolSteps !== false,
      dotBg: m.bad ? '#B4574A' : '#4F7A5A',
    }));
    const q = query.trim().toLowerCase();
    const chatList = chats.filter(c => !q || c.title.toLowerCase().indexOf(q) >= 0).map(c => ({
      title: c.title,
      running: !idle && runChat === c.id,
      bg: c.id === activeId ? '#E6E1D8' : 'transparent',
      onOpen: () => this.setState({ activeId: c.id, modelMenu: false }),
    }));
    const cur = models.find(m => m.id === model) || { name: 'Quill', short: 'Quill' };
    const cantSend = !draft.trim();
    return {
      sidebarOpen: this.state.sidebar, sidebarClosed: !this.state.sidebar,
      toggleSidebar: () => this.setState(s => ({ sidebar: !s.sidebar })),
      query: query, onQuery: e => this.setState({ query: e.target.value }),
      chatList: chatList, noResults: chatList.length === 0,
      connectors: connectors.map(k => Object.assign({}, k, {
        justify: k.on ? 'flex-end' : 'flex-start',
        track: k.on ? '#23211D' : '#D6D1C7',
        toggleTitle: k.on ? 'Disconnect' : 'Connect',
        onToggle: () => this.setState(s => ({ connectors: s.connectors.map(x => x.id === k.id ? Object.assign({}, x, { on: !x.on }) : x) })),
      })),
      connectedCount: connectors.filter(k => k.on).length,
      activeTitle: active ? active.title : '',
      items: items,
      isEmpty: msgs.length === 0,
      newChat: this.newChat,
      isThinking: phase === 'thinking' && runChat === activeId,
      thinkingEl: React.createElement('div', { style: { display: 'flex', gap: 5, padding: '6px 0' } },
        [0, 1, 2].map(i => React.createElement('span', { key: i, style: { width: 6, height: 6, borderRadius: '50%', background: '#7A756B', animation: 'qc-pulse 1.2s ' + (i * 0.15) + 's infinite ease-in-out' } }))),
      scrollRef: this.scrollRef, taRef: this.taRef, fileRef: this.fileRef,
      draft: draft,
      placeholder: phase === 'awaiting' ? 'Waiting for your permission…' : (msgs.length ? 'Reply to Quill…' : 'Ask Quill to do something…'),
      onDraft: e => this.setState({ draft: e.target.value }),
      onKey: e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); this.send(); } },
      hasAttachments: attachments.length > 0,
      attachments: attachments.map((f, i) => ({ name: f.name, onRemove: () => this.setState(s => ({ attachments: s.attachments.filter((_, j) => j !== i) })) })),
      pickFiles: () => this.fileRef.current && this.fileRef.current.click(),
      onFiles: e => { const fs = Array.from(e.target.files || []); e.target.value = ''; this.setState(s => ({ attachments: s.attachments.concat(fs) })); },
      modeLabel: this.mode === 'ask' ? 'Ask first' : 'Auto-approve',
      modeDot: this.mode === 'ask' ? '#4F7A5A' : '#C98A2B',
      toggleMode: () => this.setState({ mode: this.mode === 'ask' ? 'auto' : 'ask' }),
      modelName: cur.short || cur.name,
      modelShort: cur.short || cur.name,
      modelMenuOpen: this.state.modelMenu,
      toggleModelMenu: () => this.setState(s => ({ modelMenu: !s.modelMenu })),
      models: models.map(m => Object.assign({}, m, {
        selected: m.id === model,
        bg: m.id === model ? '#F6F3ED' : 'transparent',
        onPick: () => {
          this.setState({ model: m.id, modelMenu: false });
          fetch('/models/slots/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ slot: m.id }),
          }).catch(() => {});
        },
      })),
      busy: !idle, notBusy: idle,
      send: this.send, stop: this.stop, retry: this.retry,
      cantSend: cantSend, sendBg: cantSend ? '#CFCAC0' : '#23211D',
    };
  }
}
'''


DC_PROPS = (
    '{&quot;defaultMode&quot;:{&quot;editor&quot;:&quot;enum&quot;,'
    '&quot;options&quot;:[&quot;Ask first&quot;,&quot;Auto-approve&quot;],'
    '&quot;default&quot;:&quot;Ask first&quot;,&quot;tsType&quot;:&quot;string&quot;},'
    '&quot;streamSpeed&quot;:{&quot;editor&quot;:&quot;enum&quot;,'
    '&quot;options&quot;:[&quot;Instant&quot;,&quot;Natural&quot;,&quot;Slow&quot;],'
    '&quot;default&quot;:&quot;Natural&quot;,&quot;tsType&quot;:&quot;string&quot;},'
    '&quot;showToolSteps&quot;:{&quot;editor&quot;:&quot;boolean&quot;,'
    '&quot;default&quot;:true,&quot;tsType&quot;:&quot;boolean&quot;}}'
)

DC_RE = re.compile(
    r'<script type="text/x-dc" data-dc-script=""[^>]*>.*?</script>',
    re.DOTALL,
)


def main():
    if len(sys.argv) < 2:
        sys.exit('usage: python rebuild_frontend.py <bundled.html> [output.html]')
    src_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('backend/static/index.html')

    html = src_path.read_text(encoding='utf-8')

    m = re.search(
        r'<script type="__bundler/template">\s*(.*?)\s*</script>',
        html,
        re.DOTALL,
    )
    if not m:
        sys.exit('error: could not find <script type="__bundler/template">')
    template = json.loads(m.group(1))

    replacement = (
        '<script type="text/x-dc" data-dc-script="" data-props="' + DC_PROPS + '">'
        + NEW_DC_SCRIPT
        + '</script>'
    )
    new_template, n = DC_RE.subn(lambda _m: replacement, template, count=1)
    if n == 0:
        sys.exit('error: could not find <script type="text/x-dc"> inside template')

      new_json = json.dumps(new_template).replace('</', '<\\u002F')
    html = html[:m.start(1)] + new_json + html[m.end(1):]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding='utf-8')
    print('wrote ' + str(out_path) + ' (' + str(len(html)) + ' bytes)')


if __name__ == '__main__':
    main()