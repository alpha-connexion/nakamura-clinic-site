#!/usr/bin/env node
// Mobile evidence harness — headless Chrome over CDP, no npm dependencies (Node ≥ 22).
//   node qa/mobile-audit.mjs --out <dir> [--base http://127.0.0.1:8792] [--w 390] [--pages index,hajimete,...]
// For every page: device-emulated (mobile UA, touch, DPR 2) screen-by-screen PNGs
// (one per phone viewport, scrolled) + a JSON audit (overflow, tap targets, small
// text, phone CTAs, header/bar geometry). Chrome MCP screenshots time out on this
// machine; this is the evidence path for the Art Director / Lead Engineer.
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const arg = (k, d) => { const i = process.argv.indexOf("--" + k); return i > -1 ? process.argv[i + 1] : d; };
const OUT = arg("out", "mobile-out");
const BASE = arg("base", "http://127.0.0.1:8792");
const W = parseInt(arg("w", "390"), 10);
const H = parseInt(arg("h", "844"), 10);
const PAGES = arg("pages", "index,hajimete,seikatsushukanbyo,hataraku,shisetsu-kijun,privacy,404").split(",");
const DESKTOP = process.argv.includes("--desktop");   // no phone emulation (desktop regression captures)
const NOJS = process.argv.includes("--nojs");         // script execution off: the no-JS fallbacks
const PORT = 9333 + Math.floor(Math.random() * 200);
const CHROME = ["C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"].find(existsSync);
if (!CHROME) { console.error("chrome.exe not found"); process.exit(2); }
mkdirSync(OUT, { recursive: true });
const profile = join(OUT, ".profile");
const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
  "--remote-debugging-port=" + PORT, "--user-data-dir=" + profile, "--window-size=" + W + "," + H, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function browserWs() {
  for (let i = 0; i < 60; i++) {
    try { const r = await fetch(`http://127.0.0.1:${PORT}/json/version`); const j = await r.json(); return j.webSocketDebuggerUrl; } catch { await sleep(250); }
  }
  throw new Error("chrome did not start");
}

class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); this.events = []; ws.onmessage = (m) => this.onmsg(JSON.parse(m.data)); }
  onmsg(msg) {
    if (msg.id && this.pending.has(msg.id)) { const { res, rej } = this.pending.get(msg.id); this.pending.delete(msg.id); msg.error ? rej(new Error(JSON.stringify(msg.error))) : res(msg.result); }
    else if (msg.method) { this.events.push(msg); }
  }
  send(method, params = {}, sessionId) {
    const id = ++this.id;
    return new Promise((res, rej) => { this.pending.set(id, { res, rej }); this.ws.send(JSON.stringify({ id, method, params, sessionId })); });
  }
  async waitEvent(method, sessionId, timeout = 15000) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      const i = this.events.findIndex((e) => e.method === method && e.sessionId === sessionId);
      if (i > -1) { const e = this.events[i]; this.events.splice(i, 1); return e; }
      await sleep(30);
    }
    throw new Error("timeout waiting " + method);
  }
}

const AUDIT = `(() => {
  const iw = innerWidth, ih = innerHeight;
  const vis = (el) => { const cs = getComputedStyle(el); if (cs.display === "none" || cs.visibility === "hidden" || +cs.opacity === 0) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const desc = (el) => (el.tagName.toLowerCase() + (el.id ? "#" + el.id : "") + (el.className && typeof el.className === "string" ? "." + el.className.trim().split(/\\s+/).join(".") : ""));
  const txt = (el) => (el.innerText || el.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 40);
  const doc = document.documentElement;
  const out = { url: location.pathname, iw, ih, scrollW: doc.scrollWidth, scrollH: doc.scrollHeight, hOverflow: doc.scrollWidth > iw + 1 };
  // elements poking out of the viewport horizontally
  out.overflowing = [];
  for (const el of document.body.querySelectorAll("*")) { if (!vis(el)) continue; const r = el.getBoundingClientRect(); if (r.right > iw + 1 || r.left < -1) out.overflowing.push({ el: desc(el), left: Math.round(r.left), right: Math.round(r.right), text: txt(el) }); if (out.overflowing.length > 25) break; }
  // tap targets
  out.smallTargets = [];
  for (const el of document.querySelectorAll('a[href],button,[role="tab"],summary,input,select,label')) { if (!vis(el)) continue; const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); const inline = cs.display === "inline"; if (r.height < 44 || r.width < 44) out.smallTargets.push({ el: desc(el), w: Math.round(r.width), h: Math.round(r.height), inline, fs: cs.fontSize, text: txt(el) }); }
  // text sizes: unique (selector, font-size) below 14px
  const seen = new Map();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n; while ((n = walker.nextNode())) { if (!n.nodeValue.trim()) continue; const el = n.parentElement; if (!el || !vis(el)) continue; const fs = parseFloat(getComputedStyle(el).fontSize); if (fs < 14) { const k = desc(el) + "|" + fs; if (!seen.has(k)) seen.set(k, { el: desc(el), fs, text: n.nodeValue.trim().slice(0, 30) }); } }
  out.smallText = [...seen.values()].slice(0, 60);
  // phone CTAs
  out.telLinks = [...document.querySelectorAll('a[href^="tel:"]')].map((el) => { const r = el.getBoundingClientRect(); return { el: desc(el), visible: vis(el), top: Math.round(r.top + scrollY), w: Math.round(r.width), h: Math.round(r.height), text: txt(el) }; });
  // chrome geometry
  const hdr = document.querySelector("header"), bar = document.getElementById("mbar"), nav = document.querySelector("nav.main"), mnav = document.querySelector(".mnav");
  out.header = hdr ? { h: Math.round(hdr.getBoundingClientRect().height), sticky: getComputedStyle(hdr).position } : null;
  out.navMainVisible = nav ? vis(nav) : null;
  out.mnav = mnav ? { visible: vis(mnav), h: Math.round(mnav.getBoundingClientRect().height), items: [...mnav.querySelectorAll("a")].map(txt) } : null;
  out.mbar = bar ? { display: getComputedStyle(bar).display, shown: bar.classList.contains("show"), h: Math.round(bar.getBoundingClientRect().height) } : null;
  // headings + first screen inventory
  out.h1 = [...document.querySelectorAll("h1")].map((h) => ({ text: txt(h), fs: getComputedStyle(h).fontSize, lines: Math.round(h.getBoundingClientRect().height / parseFloat(getComputedStyle(h).lineHeight)) }));
  out.firstScreen = [...document.body.querySelectorAll("h1,h2,h3,a.btn-call,a.btn-ghost,a.hdr-call,.fact-strip,.notice,.mnav,.roundels,.hero-photo,.pg-plate")].filter((el) => vis(el) && el.getBoundingClientRect().top < ih).map((el) => ({ el: desc(el), top: Math.round(el.getBoundingClientRect().top), h: Math.round(el.getBoundingClientRect().height), text: txt(el) }));
  // images
  out.images = [...document.images].filter(vis).map((im) => ({ src: im.currentSrc.split("/").pop(), rendered: Math.round(im.getBoundingClientRect().width), natural: im.naturalWidth }));
  // tables
  out.tables = [...document.querySelectorAll("table")].filter(vis).map((t) => ({ el: desc(t), w: Math.round(t.getBoundingClientRect().width), parentScroll: t.parentElement.scrollWidth > t.parentElement.clientWidth }));
  return JSON.stringify(out);
})()`;

(async () => {
  const ws = new WebSocket(await browserWs());
  await new Promise((r) => (ws.onopen = r));
  const cdp = new CDP(ws);
  const summary = [];
  for (const page of PAGES) {
    const url = BASE + (page === "index" ? "/" : "/" + page + ".html");
    const { targetId } = await cdp.send("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
    const s = (m, p) => cdp.send(m, p, sessionId);
    await s("Page.enable");
    await s("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: DESKTOP ? 1 : 2, mobile: !DESKTOP, screenWidth: W, screenHeight: H });
    if (!DESKTOP) {
      await s("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
      await s("Emulation.setUserAgentOverride", { userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1" });
    }
    if (NOJS) await s("Emulation.setScriptExecutionDisabled", { value: true });
    await s("Page.navigate", { url });
    await cdp.waitEvent("Page.loadEventFired", sessionId);
    await s("Runtime.evaluate", { expression: "document.fonts.ready.then(()=>1)", awaitPromise: true });
    await sleep(900);
    const shots = [], phones = [];
    const { result: { value: sh } } = await s("Runtime.evaluate", { expression: "document.documentElement.scrollHeight", returnByValue: true });
    for (let y = 0, i = 0; y < sh; y += H, i++) {
      await s("Runtime.evaluate", { expression: `scrollTo({top:${y},behavior:'instant'})` });
      await sleep(i === 0 ? 300 : 650);
      const { data } = await s("Page.captureScreenshot", { format: "png" });
      const file = `${page}-${W}-s${String(i).padStart(2, "0")}.png`;
      writeFileSync(join(OUT, file), Buffer.from(data, "base64"));
      shots.push(file);
      // filled phone buttons on this screen: the bar (if up) + any main .btn-call in the clear band
      const { result: { value: n } } = await s("Runtime.evaluate", { returnByValue: true, expression: `(() => {
        const top = document.querySelector('header').getBoundingClientRect().bottom, bar = document.getElementById('mbar');
        const barTop = bar ? bar.getBoundingClientRect().top : innerHeight, barUp = bar && getComputedStyle(bar).display !== 'none' && barTop < innerHeight - 1;
        let k = barUp ? 1 : 0; const floor = barUp ? barTop : innerHeight;
        for (const b of document.querySelectorAll('main .btn-call')) { const r = b.getBoundingClientRect(); if (r.bottom > top && r.top < floor) k++; }
        return k; })()` });
      phones.push(n);
    }
    // audit at top of page, then bar state after a scroll
    // the site sets scroll-behavior:smooth — force instant scrolls so the audit reads y=0, not mid-animation
    await s("Runtime.evaluate", { expression: "scrollTo({top:0,behavior:'instant'})" }); await sleep(500);
    const { result: { value: auditJson } } = await s("Runtime.evaluate", { expression: AUDIT, returnByValue: true });
    const audit = JSON.parse(auditJson);
    await s("Runtime.evaluate", { expression: "scrollTo({top:1200,behavior:'instant'})" }); await sleep(500);
    const { result: { value: barAfter } } = await s("Runtime.evaluate", { expression: "(()=>{const b=document.getElementById('mbar');return b?JSON.stringify({shown:b.classList.contains('show'),h:Math.round(b.getBoundingClientRect().height),bottom:Math.round(b.getBoundingClientRect().bottom),ih:innerHeight}):null})()", returnByValue: true });
    audit.mbarAfterScroll = barAfter ? JSON.parse(barAfter) : null;
    audit.phonesPerScreen = phones;
    // the phone menu sheet (if the page has one): open, capture, close
    const { result: { value: hasMenu } } = await s("Runtime.evaluate", { expression: "!!document.querySelector('.hdr-menu') && getComputedStyle(document.querySelector('.hdr-menu')).display !== 'none'", returnByValue: true });
    if (hasMenu) {
      // 500ms lets the bar's 0.2s slide finish; with JS off the click is a real #site-index jump under scroll-behavior:smooth
      await s("Runtime.evaluate", { expression: "scrollTo({top:0,behavior:'instant'}); document.querySelector('.hdr-menu').click()" }); await sleep(NOJS ? 1600 : 500);
      const { data } = await s("Page.captureScreenshot", { format: "png" });
      writeFileSync(join(OUT, `${page}-${W}-menu.png`), Buffer.from(data, "base64"));
      const { result: { value: menuState } } = await s("Runtime.evaluate", { returnByValue: true, expression: "(()=>{const b=document.querySelector('.hdr-menu');const rows=[...document.querySelectorAll('#gnav a')].filter(a=>a.getBoundingClientRect().height>0).map(a=>({t:a.textContent.trim(),h:Math.round(a.getBoundingClientRect().height),cur:a.hasAttribute('aria-current')}));return JSON.stringify({open:document.documentElement.classList.contains('menu-open'),expanded:b.getAttribute('aria-expanded'),label:b.innerText.trim(),btn:{w:Math.round(b.getBoundingClientRect().width),h:Math.round(b.getBoundingClientRect().height)},rows,barUp:(()=>{const m=document.getElementById('mbar');if(!m)return null;const r=m.getBoundingClientRect();return r.height>0&&r.bottom<=innerHeight+1&&r.top<innerHeight})()})})()" });
      audit.menu = JSON.parse(menuState);
      await s("Runtime.evaluate", { expression: "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))" }); await sleep(150);
    }
    audit.screens = shots.length; audit.shots = shots;
    writeFileSync(join(OUT, `${page}-${W}-audit.json`), JSON.stringify(audit, null, 1));
    summary.push({ page, width: W, scrollH: audit.scrollH, screens: shots.length, hOverflow: audit.hOverflow, overflowing: audit.overflowing.length, smallTargets: audit.smallTargets.length, smallText: audit.smallText.length, telLinks: audit.telLinks.filter((t) => t.visible).length, phones: phones.join(""), menu: audit.menu ? (audit.menu.open ? "ok" : "FAIL") : "-" });
    await cdp.send("Target.closeTarget", { targetId });
  }
  writeFileSync(join(OUT, `summary-${W}.json`), JSON.stringify(summary, null, 1));
  console.table(summary);
  ws.close(); chrome.kill();
})().catch((e) => { console.error(e); chrome.kill(); process.exit(1); });
