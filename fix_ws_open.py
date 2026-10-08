"""Fix the onopen race in startStreaming. Idempotent."""
import re
from pathlib import Path

p = Path("backend/static/index.html")
src = p.read_text(encoding="utf-8")

if "handlers registered before any await" in src:
    print("SKIP: already patched")
    raise SystemExit(0)

pat = re.compile(r"async function startStreaming\(\)\{.*?\n\}\n", re.DOTALL)
m = pat.search(src)
if not m:
    print("FAIL: could not locate startStreaming")
    raise SystemExit(1)

new = r'''async function startStreaming(){
  if (rec.active) return;
  try {
    rec.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      }
    });
  } catch(e){
    alert("Mic access denied: " + e.message);
    return;
  }

  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  rec.ctx = ctx;
  const sampleRate = ctx.sampleRate;

  const host = location.host || "localhost:8000";
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  let ws;
  try {
    ws = new WebSocket(proto + "//" + host + "/ws/audio");
    ws.binaryType = "arraybuffer";
  } catch(e){
    alert("WebSocket failed: " + e.message);
    try { rec.stream.getTracks().forEach(function(t){ t.stop(); }); } catch(_){}
    rec.stream = null;
    try { ctx.close(); } catch(_){}
    rec.ctx = null;
    return;
  }
  rec.ws = ws;

  // handlers registered before any await - otherwise onopen can fire
  // during audioWorklet.addModule and be missed entirely.
  const ready = new Promise(function(resolve, reject){
    const timer = setTimeout(function(){
      if (ws.readyState !== WebSocket.OPEN){
        reject(new Error("ws timeout (readyState=" + ws.readyState + ")"));
      }
    }, 8000);
    function onOpen(){
      clearTimeout(timer);
      try {
        ws.send(JSON.stringify({
          type: "start", sample_rate: sampleRate, format: "pcm16"
        }));
        resolve();
      } catch(e){ reject(e); }
    }
    function onErr(){
      clearTimeout(timer);
      reject(new Error("ws error"));
    }
    if (ws.readyState === WebSocket.OPEN){
      onOpen();
    } else if (ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING){
      onErr();
    } else {
      ws.addEventListener("open", onOpen, { once: true });
      ws.addEventListener("error", onErr, { once: true });
    }
  });

  ws.onmessage = function(ev){
    let d; try { d = JSON.parse(ev.data); } catch(_){ return; }
    if (d.type === "partial" && d.text){
      const live = el("mic-live");
      if (live){ live.style.display = "block"; live.textContent = d.text; }
    } else if (d.type === "final"){
      const text = (d.text || "").trim();
      if (text){
        const ta = el("input");
        ta.value = (ta.value ? ta.value + " " : "") + text;
        state.draft = ta.value;
        autoResize();
        el("btn-send").disabled = !state.draft.trim();
      }
      setMicUI(false, 0);
    } else if (d.type === "error"){
      alert("Audio error: " + (d.message || "unknown"));
      setMicUI(false, 0);
    } else if (d.type === "cancelled"){
      setMicUI(false, 0);
    }
  };

  const blob = new Blob([MIC_WORKLET_SRC], { type: "application/javascript" });
  const url = URL.createObjectURL(blob);
  try {
    await ctx.audioWorklet.addModule(url);
  } catch(e){
    alert("AudioWorklet failed: " + e.message);
    URL.revokeObjectURL(url);
    try { ws.close(); } catch(_){}
    rec.ws = null;
    try { ctx.close(); } catch(_){}
    rec.ctx = null;
    try { rec.stream.getTracks().forEach(function(t){ t.stop(); }); } catch(_){}
    rec.stream = null;
    return;
  }
  URL.revokeObjectURL(url);

  const source = ctx.createMediaStreamSource(rec.stream);
  const node = new AudioWorkletNode(ctx, "mic-processor");
  rec.source = source;
  rec.node = node;

  node.port.onmessage = function(ev){
    if (!rec.active) return;
    const buf = ev.data;
    if (ws.readyState === WebSocket.OPEN){
      try { ws.send(buf); } catch(_){}
    }
    const level = micLevelFromI16(buf);
    const meter = el("mic-meter");
    if (meter){
      const pct = Math.min(100, Math.round(level * 400));
      meter.firstElementChild.style.width = pct + "%";
    }
    const now = performance.now();
    if (level > rec.rmsThreshold){
      rec.lastVoiceAt = now;
      rec.hasVoiced = true;
    } else if (rec.hasVoiced && now - rec.lastVoiceAt > rec.silenceMs){
      stopStreaming(false);
    }
  };

  source.connect(node);
  rec.active = true;
  rec.hasVoiced = false;
  rec.lastVoiceAt = performance.now();
  setMicUI(true, 0);

  try {
    await ready;
  } catch(e){
    alert("Audio start failed: " + e.message);
    stopStreaming(true);
  }
}
'''

src = src[:m.start()] + new + src[m.end():]
p.write_text(src, encoding="utf-8")
print("OK: startStreaming replaced")