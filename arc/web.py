"""ARC live dashboard - a zero-dependency web UI for demonstrations.

Run the engine and a small HTTP server together:

    python3 -m arc web --contracts contracts/examples/full_suite.yaml --port 8777

Then open http://localhost:8777 - gauges, contract states, managed processes
and the event feed all update live. Everything is inline (no CDN, no build
step), so it works offline on Linux, WSL, macOS and Windows.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .platform_compat import capabilities

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ARC - Adaptive Resource Contract Engine</title>
<style>
  :root {
    --bg:#0f172a; --panel:#1e293b; --panel2:#273449; --text:#e2e8f0; --muted:#94a3b8;
    --accent:#60a5fa; --ok:#34d399; --warn:#fbbf24; --bad:#f87171; --idle:#64748b;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
  header { padding:18px 28px; background:linear-gradient(90deg,#1e3a8a,#0f172a);
           display:flex; align-items:baseline; gap:16px; }
  header h1 { margin:0; font-size:22px; letter-spacing:.5px; }
  header .sub { color:#bfdbfe; font-size:13px; }
  .live { margin-left:auto; display:flex; align-items:center; gap:8px; font-size:12px; color:var(--ok); }
  .dot { width:9px; height:9px; border-radius:50%; background:var(--ok); animation:pulse 1.6s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.25} }
  main { padding:22px 28px 40px; display:grid; gap:18px;
         grid-template-columns:repeat(4,1fr); grid-auto-rows:min-content; }
  .card { background:var(--panel); border:1px solid #334155; border-radius:14px; padding:16px 18px; }
  .card h2 { margin:0 0 10px; font-size:12px; text-transform:uppercase; letter-spacing:1.2px; color:var(--muted); }
  .span2 { grid-column:span 2; } .span4 { grid-column:span 4; }
  .gauge { text-align:center; }
  .gauge .val { font-size:30px; font-weight:700; }
  .gauge .lbl { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:1px; }
  svg.g { width:120px; height:70px; display:block; margin:0 auto 4px; }
  .contract { border-left:4px solid var(--idle); }
  .contract.IDLE { border-left-color:var(--idle); }
  .contract.PENDING { border-left-color:var(--warn); }
  .contract.ACTIVE { border-left-color:var(--ok); }
  .contract.RESTORING { border-left-color:var(--accent); }
  .badge { display:inline-block; padding:2px 10px; border-radius:999px; font-size:11px; font-weight:700; letter-spacing:.8px; }
  .b-IDLE { background:#334155; color:#cbd5e1; }
  .b-PENDING { background:#78350f; color:#fde68a; }
  .b-ACTIVE { background:#064e3b; color:#6ee7b7; }
  .b-RESTORING { background:#1e3a8a; color:#93c5fd; }
  .contract .desc { color:var(--muted); font-size:12px; margin:8px 0 4px; min-height:30px; }
  .contract .meta { font-size:11px; color:var(--muted); display:flex; gap:14px; }
  table { width:100%; border-collapse:collapse; font-size:12.5px; }
  th { text-align:left; color:var(--muted); font-weight:600; padding:6px 8px; border-bottom:1px solid #334155; }
  td { padding:6px 8px; border-bottom:1px solid #24324a; font-family:ui-monospace,Menlo,monospace; }
  .chg { color:var(--ok); } .old { color:var(--muted); text-decoration:line-through; }
  .feed { max-height:340px; overflow-y:auto; font-family:ui-monospace,Menlo,monospace; font-size:12px; }
  .feed .row { padding:5px 6px; border-bottom:1px solid #24324a; display:flex; gap:10px; }
  .feed .t { color:var(--muted); } .feed .e { font-weight:700; min-width:135px; }
  .e-TRIGGER_ON { color:var(--warn); } .e-ACTIONS_APPLIED { color:var(--accent); }
  .e-RESTORED { color:var(--ok); } .e-WARN { color:var(--bad); }
  .e-ACTION_SKIPPED { color:#c084fc; } .e-ENGINE_START,.e-ENGINE_STOP { color:var(--muted); }
  .flash { animation:flash .9s; }
  @keyframes flash { from{background:#1e3a5d} to{background:transparent} }
  footer { grid-column:span 4; color:var(--muted); font-size:11px; text-align:center; padding-top:6px; }
</style>
</head>
<body>
<header>
  <h1>ARC</h1>
  <div class="sub">Adaptive Resource Contract Engine &mdash; live policy view</div>
  <div class="live"><span class="dot"></span><span id="ts">connecting...</span></div>
</header>
<main>
  <div class="card gauge" id="g-cpu"></div>
  <div class="card gauge" id="g-mem"></div>
  <div class="card gauge" id="g-bat"></div>
  <div class="card gauge" id="g-load"></div>

  <div class="card span2">
    <h2>Contracts</h2>
    <div id="contracts" style="display:grid; gap:12px; grid-template-columns:1fr;"></div>
  </div>

  <div class="card span2">
    <h2>Event feed</h2>
    <div class="feed" id="feed"></div>
  </div>

  <div class="card span4">
    <h2>Managed processes &mdash; enforced state (new) vs original state (old)</h2>
    <table>
      <thead><tr><th>contract</th><th>action</th><th>pid</th><th>process</th><th>state</th></tr></thead>
      <tbody id="procs"><tr><td colspan="5" style="color:var(--muted)">no contracts active</td></tr></tbody>
    </table>
  </div>

  <footer id="caps"></footer>
</main>
<script>
function gauge(el, label, pct, color, extra) {
  pct = Math.max(0, Math.min(100, pct));
  const r=52, c=Math.PI*r, off=c*(1-pct/100);
  el.innerHTML = `
    <svg class="g" viewBox="0 0 120 70">
      <path d="M10,60 A ${r} ${r} 0 0 1 110,60" fill="none" stroke="#334155" stroke-width="11" stroke-linecap="round"/>
      <path d="M10,60 A ${r} ${r} 0 0 1 110,60" fill="none" stroke="${color}" stroke-width="11"
            stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${off}"/>
    </svg>
    <div class="val" style="color:${color}">${extra !== undefined ? extra : pct.toFixed(1)+'%'}</div>
    <div class="lbl">${label}</div>`;
}
function fmtChg(prev, neu) {
  const keys = new Set([...Object.keys(prev||{}), ...Object.keys(neu||{})]);
  const parts = [];
  keys.forEach(k => {
    const o = prev ? prev[k] : undefined, n = neu ? neu[k] : undefined;
    if (JSON.stringify(o) === JSON.stringify(n)) return;
    parts.push(`${k}: <span class="old">${JSON.stringify(o)}</span> &rarr; <span class="chg">${JSON.stringify(n)}</span>`);
  });
  return parts.join("<br>") || "applied";
}
async function tick() {
  try {
    const s = await (await fetch("/api/state")).json();
    document.getElementById("ts").textContent = "live - " + new Date().toLocaleTimeString();
    const m = s.metrics;
    gauge(document.getElementById("g-cpu"), "CPU utilization", m.cpu_percent, "#60a5fa");
    gauge(document.getElementById("g-mem"), "Memory usage", m.mem_percent, "#f472b6");
    const b = m.battery;
    gauge(document.getElementById("g-bat"), b.percent === null ? "Power" : (b.plugged ? "Battery (charging)" : "Battery"),
          b.percent === null ? 100 : b.percent, b.percent === null ? "#64748b" : (b.plugged ? "#34d399" : "#fbbf24"),
          b.percent === null ? "AC" : b.percent.toFixed(0)+'%');
    gauge(document.getElementById("g-load"), "Load average (1m)", Math.min(100, (m.load1||0)/s.caps.cpu_count*100), "#a78bfa",
          m.load1 === null ? "n/a" : m.load1.toFixed(2));

    document.getElementById("contracts").innerHTML = s.contracts.map(c => `
      <div class="card contract ${c.state}" style="padding:12px 14px">
        <div style="display:flex; align-items:center; gap:10px">
          <strong>${c.name}</strong>
          <span class="badge b-${c.state}">${c.state}</span>
          <span style="margin-left:auto; font-size:11px; color:var(--muted)">trigger: ${c.trigger}
          &nbsp;|&nbsp; activations: ${c.activations} &nbsp;|&nbsp; restorations: ${c.restorations}</span>
        </div>
        <div class="desc">${c.desc}</div>
      </div>`).join("");

    const rows = [];
    s.contracts.forEach(c => (c.applied || []).forEach(a => rows.push(`
      <tr><td>${c.name}</td><td>${a.action}</td><td>${a.pid}</td>
          <td>${s.proc_names[a.pid] || "?"}</td><td>${fmtChg(a.prev, a.new)}</td></tr>`)));
    document.getElementById("procs").innerHTML =
      rows.length ? rows.join("") : `<tr><td colspan="5" style="color:var(--muted)">no contracts active</td></tr>`;

    document.getElementById("feed").innerHTML = s.events.slice().reverse().map(e => `
      <div class="row flash"><span class="t">${e.wall}</span>
        <span class="e e-${e.event}">${e.event}</span>
        <span>${e.contract}</span>
        <span style="color:var(--muted)">${Object.keys(e).filter(k=>!["ts","wall","event","contract"].includes(k)).map(k=>k+"="+JSON.stringify(e[k])).join(" ").slice(0,110)}</span>
      </div>`).join("");

    document.getElementById("caps").textContent =
      `platform ${s.caps.platform} | cpus ${s.caps.cpu_count} | affinity ${s.caps.affinity} | ` +
      `suspend/resume ${s.caps.suspend_resume} | cgroups ${s.caps.cgroups} | ` +
      `raise priority ${s.caps.raise_priority} | samples ${s.samples}`;
  } catch (e) { document.getElementById("ts").textContent = "engine not reachable"; }
}
tick(); setInterval(tick, 1000);
</script>
</body>
</html>
"""


class Dashboard:
    """Collects a JSON view of engine state for the web UI."""

    def __init__(self, engine):
        self.engine = engine
        self.t0 = time.time()

    def state(self) -> dict:
        eng = self.engine
        sample = eng.last_sample
        metrics = {
            "cpu_percent": sample.cpu_percent if sample else 0.0,
            "mem_percent": sample.mem_percent if sample else 0.0,
            "load1": sample.load1 if sample else None,
            "battery": {
                "percent": sample.battery.percent if sample else None,
                "plugged": sample.battery.plugged if sample else None,
            },
        }
        contracts, proc_names = [], {}
        for rt in eng.contracts:
            applied = []
            for ch in rt.applied_changes:
                applied.append({"action": ch.action_type, "pid": ch.pid,
                                "prev": ch.prev, "new": ch.new})
                proc_names[ch.pid] = getattr(ch, "proc_name", str(ch.pid))
            contracts.append({
                "name": rt.contract.name,
                "state": rt.state.value,
                "desc": rt.contract.description.strip() or rt.contract.trigger.type,
                "trigger": rt.contract.trigger.type,
                "activations": rt.activations,
                "restorations": rt.restorations,
                "applied": applied,
            })
        if sample:
            for p in sample.procs:
                proc_names.setdefault(p.pid, p.name)
        return {
            "ts": time.time(),
            "uptime": round(time.time() - self.t0, 1),
            "caps": capabilities(),
            "metrics": metrics,
            "contracts": contracts,
            "proc_names": proc_names,
            "events": eng.log.entries[-40:],
            "samples": eng.samples_seen,
        }


def make_handler(dashboard: Dashboard):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # keep the console clean; ARC has its own execution log

        def do_GET(self):
            if self.path.startswith("/api/state"):
                body = json.dumps(dashboard.state()).encode()
                ctype = "application/json"
            else:
                body = PAGE.encode()
                ctype = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def serve(engine, host: str = "0.0.0.0", port: int = 8777):
    """Start the dashboard HTTP server (non-blocking); returns the server."""
    dashboard = Dashboard(engine)
    httpd = ThreadingHTTPServer((host, port), make_handler(dashboard))
    threading.Thread(target=httpd.serve_forever, daemon=True, name="arc-web").start()
    return httpd
