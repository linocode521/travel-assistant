// 一体化截图（需要 full-access：浏览器的 mojo 命名管道在受限沙箱下会被拒绝）
// 用法：node _shot_full.mjs <url> <out.png> [width] [height] [waitMs]
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";

const [, , url, out, w = "1600", h = "1100", waitMs = "5000"] = process.argv;
const PORT = Number(process.env.CDP_PORT || 9555);
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const profile = path.join(os.tmpdir(), "dsh-shot-" + Date.now());
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const edge = spawn(EDGE, [
  "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
  "--no-default-browser-check", "--disable-extensions", "--mute-audio", "--no-sandbox",
  "--remote-debugging-port=" + PORT, "--user-data-dir=" + profile,
  "--window-size=" + w + "," + h, "about:blank",
], { stdio: "ignore", windowsHide: true });

async function waitCDP(timeoutMs = 25000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch("http://127.0.0.1:" + PORT + "/json/version");
      if (r.ok) return true;
    } catch (e) { /* retry */ }
    await sleep(300);
  }
  return false;
}

async function main() {
  if (!(await waitCDP())) throw new Error("Edge CDP 未就绪");
  let list = await (await fetch("http://127.0.0.1:" + PORT + "/json/list")).json();
  let page = list.find((t) => t.type === "page");
  if (!page) {
    await fetch("http://127.0.0.1:" + PORT + "/json/new?about:blank", { method: "PUT" });
    list = await (await fetch("http://127.0.0.1:" + PORT + "/json/list")).json();
    page = list.find((t) => t.type === "page");
  }
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  const logs = [];
  ws.addEventListener("message", (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
    if (m.method === "Runtime.consoleAPICalled") logs.push("[" + m.params.type + "] " + m.params.args.map((a) => a.value ?? a.description ?? "").join(" "));
    if (m.method === "Runtime.exceptionThrown") logs.push("[exception] " + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
    if (m.method === "Log.entryAdded" && m.params.entry.level !== "verbose") logs.push("[log:" + m.params.entry.level + "] " + m.params.entry.text);
  });
  await new Promise((r) => ws.addEventListener("open", r));
  const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Log.enable");
  await send("Network.enable");
  // 关掉 Edge 的防跟踪：它会拦住 OSM 瓦片，导致地图一片灰
  await send("Browser.setDownloadBehavior", { behavior: "deny" }).catch(() => {});
  await send("Emulation.setDeviceMetricsOverride", { width: +w, height: +h, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url });
  await sleep(+waitMs);

  const met = await send("Page.getLayoutMetrics");
  const full = met.result.cssContentSize;
  const shot = await send("Page.captureScreenshot", {
    format: "png", captureBeyondViewport: true,
    clip: { x: 0, y: 0, width: Math.ceil(full.width), height: Math.min(Math.ceil(full.height), 5200), scale: 1 },
  });
  if (!shot.result || !shot.result.data) throw new Error("截图失败 " + JSON.stringify(shot).slice(0, 300));
  fs.writeFileSync(out, Buffer.from(shot.result.data, "base64"));

  const dom = await send("Runtime.evaluate", {
    expression: `JSON.stringify({hero:!document.getElementById('hero').classList.contains('hidden'),days:document.querySelectorAll('.day').length,items:document.querySelectorAll('.item').length,pins:document.querySelectorAll('.leaflet-marker-icon').length,tiles:document.querySelectorAll('img.leaflet-tile').length,total:document.getElementById('bTotal').textContent,leaflet:typeof window.L!=='undefined',size:[document.documentElement.scrollWidth,document.documentElement.scrollHeight],mapH:document.getElementById('map').offsetHeight})`,
    returnByValue: true,
  });
  console.log("url:", url);
  console.log("dom:", dom.result.result.value);
  console.log("logs:", logs.length ? "\n  " + logs.slice(0, 30).join("\n  ") : "(none)");
  ws.close();
}

main()
  .catch((e) => { console.error("ERR", e.message); process.exitCode = 1; })
  .finally(async () => {
    await sleep(300);
    try { edge.kill(); } catch (e) { /* ignore */ }
    setTimeout(() => { try { fs.rmSync(profile, { recursive: true, force: true }); } catch (e) { /* ignore */ } process.exit(); }, 1000);
  });
