/* Quill audio. Standalone. Injects its own UI. Never touches the host app. */
(function(){
'use strict';

const MIC_WORKLET_SRC = `
class MicProcessor extends AudioWorkletProcessor {
  constructor() { super(); this._buf = new Float32Array(2048); this._n = 0; }
  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    const f32 = input[0];
    for (let i = 0; i < f32.length; i++) {
      this._buf[this._n++] = f32[i];
      if (this._n >= this._buf.length) { this._flush(); this._n = 0; }
    }
    return true;
  }
  _flush() {
    const i16 = new Int16Array(this._n);
    for (let i = 0; i < this._n; i++) {
      let s = Math.max(-1, Math.min(1, this._buf[i]));
      i16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    this.port.postMessage(i16.buffer, [i16.buffer]);
  }
}
registerProcessor("mic-processor", MicProcessor);
`;

const rec = {
  ws: null, ctx: null, stream: null, node: null, source: null,
  active: false, lastVoiceAt: 0, hasVoiced: false,
  silenceMs: 1600, rmsThreshold: 0.012,
  lastPartial: "",
  fallbackTimer: null, teardownTimer: null,
};

function dbg(){ console.log.apply(console, ["[audio]"].concat(Array.prototype.slice.call(arguments))); }
function byId(id){ return document.getElementById(id); }

function micLevelFromI16(buffer){
  const i16 = new Int16Array(buffer);
  let sum = 0;
  for (let i = 0; i < i16.length; i++){
    const v = i16[i] / 32768;
    sum += v * v;
  }
  return Math.sqrt(sum / i16.length);
}

function setMicUI(active, level){
  const btn = byId("btn-mic");
  if (btn){
    if (active) btn.classList.add("recording");
    else btn.classList.remove("recording");
  }
  const meter = byId("mic-meter");
  if (meter){
    if (active){
      meter.style.display = "block";
      const pct = Math.min(100, Math.round((level || 0) * 400));
      meter.firstElementChild.style.width = pct + "%";
    } else {
      meter.style.display = "none";
      meter.firstElementChild.style.width = "0%";
    }
  }
  const live = byId("mic-live");
  if (live && !active){ live.style.display = "none"; live.textContent = ""; }
}

function cancelFallback(){
  if (rec.fallbackTimer){ clearTimeout(rec.fallbackTimer); rec.fallbackTimer = null; }
}

function teardown(){
  cancelFallback();
  if (rec.teardownTimer){ clearTimeout(rec.teardownTimer); rec.teardownTimer = null; }
  try { if (rec.ws) rec.ws.close(); } catch(_){}
  rec.ws = null;
  try { if (rec.node) rec.node.disconnect(); } catch(_){}
  rec.node = null;
  try { if (rec.source) rec.source.disconnect(); } catch(_){}
  rec.source = null;
  try { if (rec.stream) rec.stream.getTracks().forEach(function(t){ t.stop(); }); } catch(_){}
  rec.stream = null;
  try { if (rec.ctx) rec.ctx.close(); } catch(_){}
  rec.ctx = null;
  rec.active = false;
  rec.lastPartial = "";
  setMicUI(false, 0);
}

function insertTranscript(text){
  const clean = (text || "").trim();
  if (!clean) return;
  const ta = byId("input");
  if (!ta){ console.warn("[audio] no #input"); return; }
  const sep = (ta.value && !ta.value.endsWith(" ")) ? " " : "";
  ta.value = ta.value + sep + clean;
  ta.dispatchEvent(new Event("input", { bubbles: true }));
}

async function start(){
  if (rec.active) return;
  if (rec.ws || rec.teardownTimer) teardown();
  try {
    rec.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true }
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
  const url = proto + "//" + host + "/ws/audio";

  let ws;
  try { ws = new WebSocket(url); ws.binaryType = "arraybuffer"; }
  catch(e){ alert("WebSocket failed: " + e.message); teardown(); return; }
  rec.ws = ws;

  ws.onopen = function(){
    dbg("ws open");
    try { ws.send(JSON.stringify({ type: "start", sample_rate: sampleRate, format: "pcm16" })); } catch(_){}
  };
  ws.onerror = function(){ dbg("ws error"); };
  ws.onclose = function(ev){ dbg("ws close", ev.code); };

  ws.onmessage = function(ev){
    let d; try { d = JSON.parse(ev.data); } catch(_){ return; }
    if (d.type === "partial" && d.text){
      rec.lastPartial = d.text;
      const live = byId("mic-live");
      if (live){ live.style.display = "block"; live.textContent = d.text; }
    } else if (d.type === "final"){
      cancelFallback();
      const text = (d.text || "").trim() || rec.lastPartial;
      insertTranscript(text);
      teardown();
    } else if (d.type === "error"){
      if (rec.lastPartial) insertTranscript(rec.lastPartial);
      alert("Audio error: " + (d.message || "unknown"));
      teardown();
    } else if (d.type === "cancelled"){
      teardown();
    }
  };

  const blob = new Blob([MIC_WORKLET_SRC], { type: "application/javascript" });
  const objUrl = URL.createObjectURL(blob);
  try { await ctx.audioWorklet.addModule(objUrl); }
  catch(e){ alert("AudioWorklet failed: " + e.message); URL.revokeObjectURL(objUrl); teardown(); return; }
  URL.revokeObjectURL(objUrl);

  const source = ctx.createMediaStreamSource(rec.stream);
  const node = new AudioWorkletNode(ctx, "mic-processor");
  rec.source = source;
  rec.node = node;

  node.port.onmessage = function(ev){
    if (!rec.active) return;
    const buf = ev.data;
    if (ws.readyState === WebSocket.OPEN){ try { ws.send(buf); } catch(_){} }
    const level = micLevelFromI16(buf);
    const meter = byId("mic-meter");
    if (meter){
      const pct = Math.min(100, Math.round(level * 400));
      meter.firstElementChild.style.width = pct + "%";
    }
    const now = performance.now();
    if (level > rec.rmsThreshold){
      rec.lastVoiceAt = now;
      rec.hasVoiced = true;
    } else if (rec.hasVoiced && now - rec.lastVoiceAt > rec.silenceMs){
      stop(false);
    }
  };

  source.connect(node);
  rec.active = true;
  rec.hasVoiced = false;
  rec.lastPartial = "";
  rec.lastVoiceAt = performance.now();
  setMicUI(true, 0);
  dbg("live");
}

function stop(cancel){
  if (!rec.active && !rec.ws) return;
  const ws = rec.ws;
  rec.active = false;
  if (!ws || ws.readyState !== WebSocket.OPEN){ teardown(); return; }
  if (cancel){
    try { ws.send(JSON.stringify({ type: "cancel" })); } catch(_){}
    rec.teardownTimer = setTimeout(teardown, 500);
    return;
  }
  try { ws.send(JSON.stringify({ type: "end" })); }
  catch(e){ if (rec.lastPartial) insertTranscript(rec.lastPartial); teardown(); return; }
  rec.fallbackTimer = setTimeout(function(){
    if (rec.lastPartial) insertTranscript(rec.lastPartial);
    teardown();
  }, 4000);
}

function toggle(){ if (rec.active) stop(false); else start(); }

async function speak(text){
  if (!text) return;
  try {
    const r = await fetch("/audio/speak", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ text: text })
    });
    if (!r.ok){ const d = await r.json().catch(function(){ return {}; }); alert("Speak failed: " + (d.error || r.status)); return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.onended = function(){ URL.revokeObjectURL(url); };
    audio.play();
  } catch(e){ alert("Speak failed: " + e.message); }
}

// ---- Inject UI on top of whatever the host page has ----

function injectUI(){
  const composer = byId("composer") || document.querySelector(".composer");
  if (!composer) return false;

  if (!byId("btn-mic")){
    const mic = document.createElement("button");
    mic.id = "btn-mic";
    mic.className = "composer-btn";
    mic.title = "Record voice";
    mic.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px"><rect x="9" y="3" width="6" height="12" rx="3"></rect><path d="M5 11a7 7 0 0 0 14 0"></path><path d="M12 18v3"></path></svg>';
    const attach = byId("btn-attach");
    if (attach && attach.parentNode) attach.parentNode.insertBefore(mic, attach);
    else composer.appendChild(mic);
  }

  const ta = byId("input");
  if (!byId("mic-meter") && ta){
    const meter = document.createElement("div");
    meter.id = "mic-meter";
    meter.style.cssText = "height:3px;background:#EFEBE3;border-radius:2px;overflow:hidden;margin-top:6px;display:none";
    meter.innerHTML = '<div style="height:100%;width:0%;background:#4F7A5A;transition:width .06s linear"></div>';
    if (ta.parentNode) ta.parentNode.insertBefore(meter, ta.nextSibling);
  }
  if (!byId("mic-live")){
    const live = document.createElement("div");
    live.id = "mic-live";
    live.style.cssText = "font:400 13px/1.5 Geist,sans-serif;color:#5E5A52;padding:6px 2px 0;font-style:italic;white-space:pre-wrap;border-top:1px dashed #ECE8E0;margin-top:6px;display:none";
    const m = byId("mic-meter");
    if (m && m.parentNode) m.parentNode.insertBefore(live, m.nextSibling);
  }

  if (!byId("mic-recording-style")){
    const style = document.createElement("style");
    style.id = "mic-recording-style";
    style.textContent = ".composer-btn.recording{background:#F5E0DD;border-color:#E8D5D1;color:#8A2D22}";
    document.head.appendChild(style);
  }
  return true;
}

function wire(){
  injectUI();
  const mic = byId("btn-mic");
  if (mic && !mic._wired){
    mic._wired = true;
    mic.addEventListener("click", toggle);
  }
  // Delegate speak click to the assistant message text
  if (!document._quillSpeakWired){
    document._quillSpeakWired = true;
    document.addEventListener("click", function(e){
      const t = e.target.closest && e.target.closest("[data-speak]");
      if (!t) return;
      const container = t.closest(".msg-asst");
      const blocks = container && container.querySelector(".msg-asst-blocks");
      const text = blocks ? blocks.textContent : "";
      if (text) speak(text);
    }, true);
  }
  console.log("[audio] wired");
}

function ready(fn){
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
  else fn();
}
ready(wire);

// Re-inject on DOM changes (host re-renders composer often)
setInterval(function(){
  injectUI();
  const mic = byId("btn-mic");
  if (mic && !mic._wired){ mic._wired = true; mic.addEventListener("click", toggle); }
}, 1500);

window.QuillAudio = { toggleRecording: toggle, speak: speak };
})();
