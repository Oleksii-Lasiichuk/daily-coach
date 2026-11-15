// Interactive daily charts (uPlot). Each .chartbox picks one or two metrics; cursors are synced,
// drag zooms, double-click resets, click pins a day and links to its page.
window.initCharts = function (opts) {
  const D = opts.data, GOAL_W = opts.goalW, LANG = opts.lang, L = opts.labels;
  const META = Object.fromEntries(D.meta.map(m => [m.key, m]));
  const first = document.querySelector(".chartbox .m1");
  const LABEL = first ? Object.fromEntries([...first.options].map(o => [o.value, o.textContent])) : {};
  const xs = D.dates.map(d => Date.parse(d + "T12:00:00Z") / 1000);
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const avg7 = (a) => a.map((_, i) => { const w = a.slice(Math.max(0, i - 6), i + 1).filter(v => v != null); return w.length ? w.reduce((s, v) => s + v, 0) / w.length : null; });
  const fmt = (k, v) => v == null ? "–" : (+v).toFixed(META[k].dec) + (META[k].unit ? " " + META[k].unit : "");
  const mark = opts.markDay ? Date.parse(opts.markDay + "T12:00:00Z") / 1000 : null;
  const plots = []; let range = opts.range ?? 90, pinned = null;
  function rangeX() {
    if (mark) return [mark - 21 * 86400, Math.min(mark + 8 * 86400, xs[xs.length - 1] + 43200)];
    const max = xs[xs.length - 1] + 43200; return range ? [max - range * 86400, max] : [xs[0] - 43200, max];
  }
  function build(box) {
    const k1 = box.querySelector(".m1").value, k2 = box.querySelector(".m2")?.value, smooth = box.querySelector(".avg")?.checked;
    const keys = [k1, k2].filter(k => k && D.series[k]), colors = [css("--accent"), css("--recover")];
    const data = [xs], series = [{}], axes = [{ stroke: css("--muted"), grid: { stroke: css("--line-2") }, ticks: { stroke: css("--line") } }];
    keys.forEach((k, i) => {
      const raw = D.series[k], bars = k === "load" || k === "km";
      data.push(smooth ? avg7(raw) : raw);
      series.push({ label: LABEL[k], scale: k, stroke: colors[i], width: 1.6, spanGaps: !bars,
                    fill: bars ? colors[i] + "55" : undefined, paths: bars ? uPlot.paths.bars({ size: [0.7, 8] }) : undefined,
                    points: { show: !bars && !smooth && (mark || (range && range <= 90)), size: 4 } });
      axes.push({ scale: k, side: i ? 1 : 3, stroke: colors[i], grid: { show: i === 0, stroke: css("--line-2") }, ticks: { stroke: css("--line") },
                  size: 46, label: META[k].unit || "", labelSize: META[k].unit ? 16 : 0, labelGap: 0,
                  values: (u, v) => v.map(x => (+x).toFixed(META[k].dec)) });
    });
    const plot = box.querySelector(".plot"); plot.innerHTML = "";
    const line = (u, x, color, dash) => { const c = u.ctx, px = u.valToPos(x, "x", true); c.save(); c.setLineDash(dash); c.strokeStyle = color; c.beginPath(); c.moveTo(px, u.bbox.top); c.lineTo(px, u.bbox.top + u.bbox.height); c.stroke(); c.restore(); };
    const u = new uPlot({ width: plot.clientWidth, height: opts.height || (innerWidth < 700 ? 200 : 260), series, axes, legend: { show: false },
      scales: { x: { time: true, range: () => rangeX() } },
      cursor: { sync: { key: "dc" }, drag: { x: true, y: false }, focus: { prox: 30 } },
      hooks: { setCursor: [u => readout(box, u.cursor.idx, keys, data)],
               draw: [u => {
                 if (GOAL_W && keys.includes("weight_kg")) { const y = u.valToPos(GOAL_W, "weight_kg", true), c = u.ctx; c.save(); c.setLineDash([5, 4]); c.strokeStyle = css("--good"); c.beginPath(); c.moveTo(u.bbox.left, y); c.lineTo(u.bbox.left + u.bbox.width, y); c.stroke(); c.restore(); }
                 if (mark) line(u, mark, css("--ink-2"), [3, 3]);
               }] } }, data, plot);
    u.over.addEventListener("click", () => { if (u.select.width < 2 && u.cursor.idx != null) { pinned = u.cursor.idx; plots.forEach(p => readout(p.box, pinned, p.keys, p.data, true)); } });
    u.over.addEventListener("dblclick", () => u.setScale("x", { min: rangeX()[0], max: rangeX()[1] }));
    plot.onmouseleave = () => { if (pinned != null) readout(box, pinned, keys, data, true); };
    Object.assign(u, { box, keys, data });
    if (mark) readout(box, D.dates.indexOf(opts.markDay), keys, data, false);
    return u;
  }
  function readout(box, i, keys, data, pin) {
    if (i == null || i < 0) return;
    const out = box.querySelector(".readout"), d = new Date(D.dates[i] + "T12:00:00Z");
    const date = d.toLocaleDateString(LANG === "uk" ? "uk-UA" : "en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
    out.innerHTML = `<b>${date}</b>` + keys.map((k, j) => `<span class="rv"><i class="dot${j + 1}"></i>${LABEL[k]} <b>${fmt(k, data[j + 1][i])}</b></span>`).join("")
      + (pin && D.dates[i] !== opts.markDay ? ` <a href="/day/${D.dates[i]}">${L.open} →</a>` : "");
  }
  function renderAll() { plots.splice(0).forEach(p => p.destroy()); document.querySelectorAll(".chartbox").forEach(b => plots.push(build(b))); }
  document.querySelectorAll(".chartbox").forEach(b => {
    const m1 = b.querySelector(".m1"), m2 = b.querySelector(".m2"), avg = b.querySelector(".avg"), key = "chart" + (opts.storeKey || "") + b.dataset.n;
    if (META[b.dataset.m1]) m1.value = b.dataset.m1; else m1.selectedIndex = Math.min(+b.dataset.n * 2, m1.options.length - 1);
    if (m2) m2.value = META[b.dataset.m2] ? b.dataset.m2 : "";
    try { const s = JSON.parse(localStorage.getItem(key) || "null"); if (s && META[s[0]]) { m1.value = s[0]; if (m2) m2.value = META[s[1]] ? s[1] : ""; if (avg) avg.checked = !!s[2]; } } catch (e) {}
    b.querySelectorAll("select, .avg").forEach(el => el.onchange = () => {
      try { localStorage.setItem(key, JSON.stringify([m1.value, m2 ? m2.value : "", avg ? avg.checked : false])); } catch (e) {}
      renderAll(); });
  });
  document.querySelectorAll("#range button").forEach(b => b.onclick = () => {
    document.querySelectorAll("#range button").forEach(x => x.removeAttribute("aria-current")); b.setAttribute("aria-current", "true");
    range = +b.dataset.days; renderAll(); });
  window.showMetric = (k) => { const b = document.querySelector(".chartbox"); b.querySelector(".m1").value = k; const m2 = b.querySelector(".m2"); if (m2) m2.value = ""; renderAll(); b.scrollIntoView({ behavior: "smooth", block: "center" }); };
  let t; addEventListener("resize", () => { clearTimeout(t); t = setTimeout(renderAll, 150); });
  document.addEventListener("themechange", renderAll);
  renderAll();
};
