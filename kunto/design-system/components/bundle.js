/* Kunto design system: the shared Calm Admin engine (window.CalmAdmin) plus the Kunto namespace (window.Kunto). One classic script, no dependencies. */
/* Calm Admin: behaviour and charts. One classic script, no dependencies; assigns window.CalmAdmin.
   Charts:     CalmAdmin.lineChart(el, opts) · CalmAdmin.stackedBarChart(el, opts) · CalmAdmin.barChart(el, opts)
               each returns { el, update(opts), destroy() }.
   Behaviour:  CalmAdmin.init(root) wires tabs, segmented controls, menus, the date-range picker, table selection
               and sorting, the nav drawer and rail, form error states and dialog buttons. It runs once on load;
               call it again for markup you add later.
   Helpers:    CalmAdmin.toast(opts) · CalmAdmin.setTheme('light' | 'dark' | 'system') · CalmAdmin.getTheme() */
(function () {
  'use strict';
  var CA = window.CalmAdmin = window.CalmAdmin || {};
  var SVG = 'http://www.w3.org/2000/svg';
  var uid = 0;

  /* ================================================================ helpers */
  function s(tag, attrs, parent) {
    var n = document.createElementNS(SVG, tag);
    for (var k in attrs) if (attrs[k] != null) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function h(tag, cls, text, parent) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    if (parent) parent.appendChild(n);
    return n;
  }
  function $$(root, sel) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  function once(el, key) { if (el['_ca' + key]) return false; el['_ca' + key] = true; return true; }
  function emit(el, name, detail) { el.dispatchEvent(new CustomEvent(name, { bubbles: true, detail: detail })); }
  function icon(name) {
    var paths = ICONS[name] || '';
    return '<svg class="ca-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths + '</svg>';
  }
  var ICONS = { 'circle-check': "<circle cx=\"12\" cy=\"12\" r=\"10\"/> <path d=\"m9 12 2 2 4-4\"/>", 'triangle-alert': "<path d=\"m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3\"/> <path d=\"M12 9v4\"/> <path d=\"M12 17h.01\"/>", 'info': "<circle cx=\"12\" cy=\"12\" r=\"10\"/> <path d=\"M12 16v-4\"/> <path d=\"M12 8h.01\"/>", 'x': "<path d=\"M18 6 6 18\"/> <path d=\"m6 6 12 12\"/>" };

  var live;
  function announce(text) {
    if (!live) { live = h('div', 'ca-sr', null, document.body); live.setAttribute('aria-live', 'polite'); }
    live.textContent = '';
    setTimeout(function () { live.textContent = text; }, 30);
  }

  /* ================================================================ number formats */
  function fmtFull(locale) {
    return function (v) {
      if (!isNum(v)) return '–';
      return Math.abs(v) < 1 && v !== 0 ? v.toLocaleString(locale || 'en-US', { maximumSignificantDigits: 3 }) : v.toLocaleString(locale || 'en-US', { maximumFractionDigits: 2 });
    };
  }
  /* Axis ticks: compact (6.5K, 1.2M) with only as many decimals as the step needs. */
  function tickFormat(step, maxAbs, locale) {
    var div = 1, suf = '';
    if (maxAbs >= 1e9) { div = 1e9; suf = 'B'; } else if (maxAbs >= 1e6) { div = 1e6; suf = 'M'; } else if (maxAbs >= 1e4 || (maxAbs >= 1e3 && step >= 100)) { div = 1e3; suf = 'K'; }
    var st = step / div, dec = st >= 1 ? 0 : clamp(Math.ceil(-Math.log10(st) - 1e-9), 0, 12);
    return function (v) { return (v / div).toLocaleString(locale || 'en-US', { maximumFractionDigits: dec, minimumFractionDigits: 0 }) + (v === 0 ? '' : suf); };
  }
  function niceTicks(lo, hi, count) {
    if (!isNum(lo) || !isNum(hi)) { lo = 0; hi = 1; }
    if (lo === hi) { if (lo === 0) { hi = 1; } else { var pad = Math.abs(lo) * 0.1; lo -= pad; hi += pad; } }
    var raw = (hi - lo) / Math.max(1, count), p = Math.pow(10, Math.floor(Math.log10(raw))), e = raw / p;
    var step = (e >= 7.5 ? 10 : e >= 3.5 ? 5 : e >= 1.5 ? 2 : 1) * p;
    var a = Math.floor(lo / step + 1e-9) * step, b = Math.ceil(hi / step - 1e-9) * step, out = [];
    for (var v = a; v <= b + step / 2; v += step) out.push(Math.round(v / step) * step);
    return { ticks: out, step: step };
  }
  function scaleY(values, o, count) {
    var lo = Math.min.apply(null, values), hi = Math.max.apply(null, values);
    if (o.zero) { lo = Math.min(0, lo); hi = Math.max(0, hi); }
    if (o.yTicks && o.yTicks.length > 1) {
      var t = o.yTicks.slice().sort(function (a, b) { return a - b; });
      if (lo >= t[0] && hi <= t[t.length - 1]) return { ticks: t, step: t[1] - t[0] };
      lo = Math.min(lo, t[0]); hi = Math.max(hi, t[t.length - 1]);
    }
    return niceTicks(lo, hi, count || 4);
  }
  function autoXTicks(n, room) {
    var k = Math.max(1, Math.ceil(n / Math.max(1, room))), out = [];
    for (var i = n - 1; i >= 0; i -= k) out.unshift(i);
    return out;
  }
  function textWidth(str) { return String(str).length * 6.6 + 4; }

  /* ================================================================ chart frame */
  function mount(target, opts, draw) {
    var el = typeof target === 'string' ? document.querySelector(target) : target;
    if (!el) return null;
    if (el._caChart) el._caChart.destroy();
    var state = { opts: opts || {}, ro: null };
    el.classList.add('ca-chart');
    function render() {
      el.textContent = '';
      var plot = h('div', 'ca-chart__plot', null, el), tip = h('div', 'ca-tip', null, plot);
      tip.hidden = true;
      draw({ el: el, plot: plot, tip: tip, width: Math.max(200, el.clientWidth || 600), locale: state.opts.locale }, state.opts);
    }
    render();
    if (window.ResizeObserver) {
      var last = el.clientWidth;
      state.ro = new ResizeObserver(function () { if (Math.abs(el.clientWidth - last) > 1) { last = el.clientWidth; render(); } });
      state.ro.observe(el);
    }
    var handle = {
      el: el,
      update: function (next) { state.opts = next || state.opts; render(); return handle; },
      destroy: function () { if (state.ro) state.ro.disconnect(); el.textContent = ''; el.classList.remove('ca-chart'); el._caChart = null; }
    };
    el._caChart = handle;
    return handle;
  }
  function emptyChart(f, o) {
    var d = h('div', 'ca-chart__empty', o.emptyText || 'No data for this period', f.plot);
    d.style.height = (o.height || 220) + 'px';
  }
  function legend(el, items) {
    if (!items.length) return;
    var ul = h('ul', 'ca-legend', null, el);
    items.forEach(function (it) {
      var li = h('li', null, null, ul);
      h('span', 'ca-legend__key ca-legend__key--' + it.shape + ' ' + (it.cls || ''), null, li).setAttribute('aria-hidden', 'true');
      li.appendChild(document.createTextNode(it.label));
    });
  }
  function srTable(el, caption, head, rows) {
    var t = h('table', null, null, h('div', 'ca-sr', null, el));
    h('caption', null, caption, t);
    var tr = h('tr', null, null, h('thead', null, null, t));
    head.forEach(function (c) { h('th', null, c, tr).setAttribute('scope', 'col'); });
    var tb = h('tbody', null, null, t);
    rows.forEach(function (r) { var row = h('tr', null, null, tb); r.forEach(function (c, i) { h(i ? 'td' : 'th', null, c, row); }); });
  }
  function tipRow(tip, value, label, keyCls, shape) {
    var row = h('div', 'ca-tip__row', null, tip);
    if (keyCls) h('span', 'ca-tip__key ca-tip__key--' + (shape || 'line') + ' ' + keyCls, null, row);
    h('b', null, value, row);
    if (label) h('span', null, label, row);
  }
  function placeTip(tip, x, width) {
    tip.hidden = false;
    var w = tip.offsetWidth || 140, left = x + 14;
    if (left + w > width) left = x - 14 - w;
    tip.style.left = clamp(left, 0, Math.max(0, width - w)) + 'px';
  }
  function clip(svg, x, y, w, hgt) {
    var id = 'ca-clip-' + (++uid), cp = s('clipPath', { id: id }, s('defs', {}, svg));
    s('rect', { x: x, y: y, width: Math.max(0, w), height: Math.max(0, hgt) }, cp);
    return 'url(#' + id + ')';
  }
  function keyNav(svg, n, show, hide, describe) {
    var cur = n - 1;
    svg.setAttribute('tabindex', '0');
    svg.addEventListener('focus', function () { show(cur); });
    svg.addEventListener('blur', hide);
    svg.addEventListener('keydown', function (e) {
      var k = e.key, next = k === 'ArrowLeft' || k === 'ArrowUp' ? cur - 1 : k === 'ArrowRight' || k === 'ArrowDown' ? cur + 1 : k === 'Home' ? 0 : k === 'End' ? n - 1 : null;
      if (next === null) return;
      e.preventDefault();
      cur = clamp(next, 0, n - 1);
      show(cur);
      announce(describe(cur));
    });
    return function (i) { cur = i; };
  }

  /* ================================================================ line chart */
  function drawLine(f, o) {
    var labels = o.labels || [], vals = (o.values || []).map(function (v) { return isNum(v) ? v : null; }), n = vals.length;
    var tips = o.tipLabels || labels;
    var cmp = o.compare && o.compare.values ? o.compare.values.map(function (v) { return isNum(v) ? v : null; }) : null;
    var present = vals.filter(isNum);
    if (!n || !present.length) return emptyChart(f, o);
    var band = o.band || null, unit = o.unit ? ' ' + o.unit : '', full = o.formatValue || fmtFull(f.locale);
    var domainVals = present.concat(cmp ? cmp.filter(isNum) : [], band ? [band.from, band.to] : []);
    var sc = scaleY(domainVals, o), ticks = sc.ticks, y0 = ticks[0], y1 = ticks[ticks.length - 1];
    var fmt = o.format || tickFormat(sc.step, Math.max(Math.abs(y0), Math.abs(y1)), f.locale);
    var W = f.width, H = o.height || 220, padT = 10, padB = 28, padR = 12;
    var padL = Math.ceil(Math.max.apply(null, ticks.map(function (t) { return textWidth(fmt(t)); }))) + 10;
    var iw = W - padL - padR, ih = H - padT - padB;
    var X = function (i) { return n === 1 ? padL + iw / 2 : padL + i * iw / (n - 1); };
    var Y = function (v) { return padT + (1 - (v - y0) / (y1 - y0)) * ih; };
    var mode = o.flag === false ? null : (o.flag || (band ? 'outside' : null));
    var isFlag = function (v) { return band && mode && isNum(v) && ((mode !== 'above' && v < band.from) || (mode !== 'below' && v > band.to)); };
    var svg = s('svg', { width: W, height: H, viewBox: '0 0 ' + W + ' ' + H, role: 'group', 'aria-roledescription': 'chart',
      'aria-label': o.summary || o.title || o.name || 'Line chart' }, f.plot);
    var clipUrl = clip(svg, padL, padT - 6, iw + 6, ih + 12);

    ticks.forEach(function (t) {
      s('line', { x1: padL, x2: W - padR, y1: Y(t), y2: Y(t), 'class': 'ca-chart__grid' }, svg);
      s('text', { x: padL - 8, y: Y(t) + 4, 'text-anchor': 'end', 'class': 'ca-chart__tick', 'aria-hidden': 'true' }, svg).textContent = fmt(t);
    });
    if (band) {
      var bt = Y(clamp(band.to, y0, y1)), bb = Y(clamp(band.from, y0, y1));
      s('rect', { x: padL, y: bt, width: iw, height: Math.max(0, bb - bt), 'class': 'ca-chart__band' }, svg);
      s('line', { x1: padL, x2: W - padR, y1: bt, y2: bt, 'class': 'ca-chart__band-edge' }, svg);
      s('line', { x1: padL, x2: W - padR, y1: bb, y2: bb, 'class': 'ca-chart__band-edge' }, svg);
    }
    function runs(arr) {
      var out = [], cur = null;
      arr.forEach(function (v, i) { if (isNum(v)) { if (!cur) out.push(cur = []); cur.push(i); } else cur = null; });
      return out;
    }
    function pathOf(arr, r) { return r.map(function (i, k) { return (k ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(arr[i]).toFixed(1); }).join(''); }
    var g = s('g', { 'clip-path': clipUrl }, svg);
    if (cmp) runs(cmp).forEach(function (r) { s('path', { d: r.length > 1 ? pathOf(cmp, r) : '', 'class': 'ca-chart__compare' }, g); });
    var base = Y(clamp(0, y0, y1));
    runs(vals).forEach(function (r) {
      if (o.area && r.length > 1) s('path', { d: pathOf(vals, r) + 'L' + X(r[r.length - 1]) + ',' + base + 'L' + X(r[0]) + ',' + base + 'Z', 'class': 'ca-chart__area' }, g);
      if (r.length > 1) s('path', { d: pathOf(vals, r), 'class': 'ca-chart__line' }, g);
      else s('circle', { cx: X(r[0]), cy: Y(vals[r[0]]), r: 2.5, 'class': 'ca-chart__end' }, g);
    });
    var lastI = -1;
    vals.forEach(function (v, i) { if (isNum(v)) lastI = i; });
    var flagged = 0;
    vals.forEach(function (v, i) { if (isFlag(v)) { flagged++; if (i !== lastI) s('circle', { cx: X(i), cy: Y(v), r: 4, 'class': 'ca-chart__flag' }, g); } });
    s('circle', { cx: X(lastI), cy: Y(vals[lastI]), r: 4, 'class': isFlag(vals[lastI]) ? 'ca-chart__flag' : 'ca-chart__end' }, g);

    (o.xTicks || autoXTicks(n, Math.floor(iw / 72))).forEach(function (i) {
      if (i < 0 || i >= n) return;
      var anchor = n === 1 ? 'middle' : i === n - 1 ? 'end' : i === 0 ? 'start' : 'middle';
      s('text', { x: X(i), y: H - 8, 'text-anchor': anchor, 'class': 'ca-chart__tick', 'aria-hidden': 'true' }, svg).textContent = labels[i] == null ? '' : labels[i];
    });

    var cross = s('line', { y1: padT, y2: padT + ih, 'class': 'ca-chart__cross', visibility: 'hidden' }, svg);
    var dot = s('circle', { r: 5, 'class': 'ca-chart__hover', visibility: 'hidden' }, svg);
    var hit = s('rect', { x: padL, y: 0, width: iw, height: H, 'class': 'ca-chart__hit' }, svg);
    function describe(i) {
      var t = (tips[i] || '') + ': ' + (isNum(vals[i]) ? full(vals[i]) + unit : 'no data');
      if (cmp) t += ', ' + (o.compare.label || 'previous') + ' ' + (isNum(cmp[i]) ? full(cmp[i]) + unit : 'no data');
      return t;
    }
    function show(i) {
      var x = X(i), v = vals[i];
      cross.setAttribute('x1', x); cross.setAttribute('x2', x); cross.setAttribute('visibility', 'visible');
      if (isNum(v)) { dot.setAttribute('cx', x); dot.setAttribute('cy', Y(v)); dot.setAttribute('visibility', 'visible'); } else dot.setAttribute('visibility', 'hidden');
      f.tip.textContent = '';
      h('div', 'ca-tip__head', tips[i], f.tip);
      tipRow(f.tip, isNum(v) ? full(v) + unit : 'No data', o.name || 'Value', 'ca-chart__k-line');
      if (cmp) tipRow(f.tip, isNum(cmp[i]) ? full(cmp[i]) + unit : 'No data', o.compare.label || 'Previous period', 'ca-chart__k-compare');
      if (band && isNum(v)) {
        var where = v < band.from ? 'Below ' : v > band.to ? 'Above ' : 'Within ';
        tipRow(f.tip, full(band.from) + '–' + full(band.to), where + (band.label || 'range').toLowerCase(), 'ca-chart__k-band', 'box');
      }
      placeTip(f.tip, x, W);
    }
    function hide() { cross.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); f.tip.hidden = true; }
    var setCur = keyNav(svg, n, show, hide, describe);
    hit.addEventListener('pointermove', function (e) {
      var r = svg.getBoundingClientRect(), px = (e.clientX - r.left) * (W / r.width);
      var i = n === 1 ? 0 : clamp(Math.round((px - padL) / (iw / (n - 1))), 0, n - 1);
      setCur(i); show(i);
    });
    hit.addEventListener('pointerleave', hide);

    if (o.legend !== false && (cmp || band || flagged)) {
      var items = [{ shape: 'line', cls: 'ca-chart__k-line', label: o.name || 'Value' }];
      if (cmp) items.push({ shape: 'line', cls: 'ca-chart__k-compare', label: o.compare.label || 'Previous period' });
      if (band) items.push({ shape: 'box', cls: 'ca-chart__k-band', label: (band.label || 'Range') + ' ' + full(band.from) + '–' + full(band.to) + unit });
      if (flagged) items.push({ shape: 'dot', cls: 'ca-chart__k-flag', label: o.flagLabel || (mode === 'below' ? 'Below range' : mode === 'above' ? 'Above range' : 'Outside range') });
      legend(f.el, items);
    }
    var head = [o.labelName || 'Label', o.name || 'Value'].concat(cmp ? [o.compare.label || 'Previous period'] : []);
    srTable(f.el, o.title || o.name || 'Chart data', head, vals.map(function (v, i) {
      return [tips[i], isNum(v) ? full(v) + unit : 'No data'].concat(cmp ? [isNum(cmp[i]) ? full(cmp[i]) + unit : 'No data'] : []);
    }));
  }

  /* ================================================================ stacked bars (ordered buckets) */
  var warned = {};
  function warnOnce(key, msg) { if (!warned[key]) { warned[key] = true; if (window.console) console.warn('[CalmAdmin] ' + msg); } }
  function drawStacked(f, o) {
    var labels = o.labels || [], n = labels.length, series = (o.series || []).slice();
    if (!n || !series.length) return emptyChart(f, o);
    var toned = 0;
    series = series.map(function (sr) {
      var tone = sr.tone || (toned < 3 ? String(++toned) : 'neutral');
      if (!sr.tone && tone === 'neutral') warnOnce('tones', 'stackedBarChart supports three toned buckets; extra series are drawn neutral.');
      var raw = labels.map(function (_, i) { return sr.values && isNum(sr.values[i]) ? sr.values[i] : null; });
      return { name: sr.name, tone: tone, raw: raw, values: raw.map(function (v) { if (isNum(v) && v < 0) { warnOnce('neg', 'stackedBarChart ignores negative values.'); return 0; } return isNum(v) ? v : 0; }) };
    });
    var full = o.formatValue || fmtFull(f.locale), unit = o.unit ? ' ' + o.unit : '';
    var tips = o.tipLabels || labels, totalLabel = o.totalLabel || 'Total';
    var totals = labels.map(function (_, i) { return series.reduce(function (a, sr) { return a + sr.values[i]; }, 0); });
    /* What the tooltip, table and announcements call the total: every bucket, or only the toned ones (totalOf: 'toned'). */
    var shown = labels.map(function (_, i) { return series.reduce(function (a, sr) { return a + (o.totalOf === 'toned' && sr.tone === 'neutral' ? 0 : sr.values[i]); }, 0); });
    var hasData = labels.map(function (_, i) { return series.some(function (sr) { return isNum(sr.raw[i]); }); });
    var val = function (v) { return isNum(v) ? full(v) + unit : 'No data'; };
    var tot = function (i) { return hasData[i] ? full(shown[i]) + unit : 'No data'; };
    var sc = scaleY(totals.concat([0]), o), ticks = sc.ticks, y1 = ticks[ticks.length - 1];
    var fmt = o.format || tickFormat(sc.step, y1, f.locale);
    var W = f.width, H = o.height || 220, padT = 10, padB = 28, padR = 8;
    var padL = Math.ceil(Math.max.apply(null, ticks.map(function (t) { return textWidth(fmt(t)); }))) + 10;
    var iw = W - padL - padR, ih = H - padT - padB, slot = iw / n, bw = Math.max(2, Math.min(24, slot * 0.6, slot - 2));
    var Y = function (v) { return padT + (1 - v / y1) * ih; };
    var current = o.current == null ? n - 1 : o.current;
    var svg = s('svg', { width: W, height: H, viewBox: '0 0 ' + W + ' ' + H, role: 'group', 'aria-roledescription': 'chart',
      'aria-label': o.summary || o.title || 'Stacked bar chart' }, f.plot);
    ticks.forEach(function (t) {
      s('line', { x1: padL, x2: W - padR, y1: Y(t), y2: Y(t), 'class': 'ca-chart__grid' }, svg);
      s('text', { x: padL - 8, y: Y(t) + 4, 'text-anchor': 'end', 'class': 'ca-chart__tick', 'aria-hidden': 'true' }, svg).textContent = fmt(t);
    });
    var bars = [], xs = [], shownTicks = o.xTicks || autoXTicks(n, Math.floor(iw / 64));
    if (shownTicks.indexOf(current) < 0 && current >= 0 && current < n && iw / n >= 30) shownTicks.push(current);
    var g0 = s('g', { 'clip-path': clip(svg, padL, padT - 1, iw, ih + 1) }, svg);
    labels.forEach(function (lab, i) {
      var g = s('g', { 'class': 'ca-chart__bar' + (o.highlight != null && o.highlight !== i ? ' ca-chart__bar--muted' : '') }, g0), x = padL + slot * i + (slot - bw) / 2, cum = 0, top = -1;
      xs.push(x + bw / 2);
      series.forEach(function (sr, j) { if (sr.values[i] > 0) top = j; });
      series.forEach(function (sr, j) {
        var v = sr.values[i];
        if (v <= 0) return;
        var yTop = Y(cum + v), yBot = Y(cum) - (cum > 0 ? 2 : 0), hgt = Math.max(0, yBot - yTop), cls = 'ca-chart__seg ca-chart__s-' + sr.tone;
        if (j === top) s('path', { d: roundedTop(x, yTop, bw, hgt, Math.min(4, bw / 2)), 'class': cls }, g);
        else s('rect', { x: x, y: yTop, width: bw, height: hgt, 'class': cls }, g);
        cum += v;
      });
      var hitR = s('rect', { x: padL + slot * i, y: padT, width: slot, height: ih, 'class': 'ca-chart__hit' }, g);
      hitR.addEventListener('pointerenter', function () { setCur(i); show(i); });
      hitR.addEventListener('pointerleave', hide);
      bars.push(g);
    });
    shownTicks.forEach(function (i) {
      var edge = n > 1 && i === n - 1 ? 'end' : n > 1 && i === 0 ? 'start' : 'middle', tx = edge === 'end' ? xs[i] + bw / 2 : edge === 'start' ? xs[i] - bw / 2 : xs[i];
      s('text', { x: tx, y: H - 8, 'text-anchor': edge, 'class': 'ca-chart__tick' + (i === current ? ' ca-chart__tick--current' : ''), 'aria-hidden': 'true' }, svg).textContent = labels[i];
    });
    var order = series.slice().reverse();
    function describe(i) { return tips[i] + ': ' + (hasData[i] ? order.map(function (sr) { return sr.name + ' ' + val(sr.raw[i]); }).join(', ') + ', ' + totalLabel.toLowerCase() + ' ' + tot(i) : 'no data'); }
    function show(i) {
      bars.forEach(function (b, k) { b.classList.toggle('is-dim', k !== i); b.classList.toggle('is-active', k === i && document.activeElement === svg); });
      f.tip.textContent = '';
      h('div', 'ca-tip__head', tips[i], f.tip);
      order.forEach(function (sr) { tipRow(f.tip, val(sr.raw[i]), sr.name, 'ca-chart__s-' + sr.tone, 'box'); });
      tipRow(f.tip, tot(i), totalLabel);
      placeTip(f.tip, xs[i] + bw / 2, W);
    }
    function hide() { bars.forEach(function (b) { b.classList.remove('is-dim', 'is-active'); }); f.tip.hidden = true; }
    var setCur = keyNav(svg, n, show, hide, describe);
    if (o.legend !== false) legend(f.el, order.map(function (sr) { return { shape: 'box', cls: 'ca-chart__s-' + sr.tone, label: sr.name }; }));
    srTable(f.el, o.title || 'Chart data', [o.labelName || 'Label'].concat(order.map(function (sr) { return sr.name; }), [totalLabel]),
      labels.map(function (lab, i) { return [tips[i]].concat(order.map(function (sr) { return val(sr.raw[i]); }), [tot(i)]); }));
  }
  function roundedTop(x, y, w, hgt, r) {
    r = Math.max(0, Math.min(r, w / 2, hgt));
    return 'M' + x + ',' + (y + hgt) + 'V' + (y + r) + 'A' + r + ',' + r + ' 0 0 1 ' + (x + r) + ',' + y + 'H' + (x + w - r) + 'A' + r + ',' + r + ' 0 0 1 ' + (x + w) + ',' + (y + r) + 'V' + (y + hgt) + 'Z';
  }
  function roundedEnd(x0, x1, y, hgt, r) {
    var right = x1 >= x0, len = Math.abs(x1 - x0);
    r = Math.max(0, Math.min(r, hgt / 2, len));
    if (right) return 'M' + x0 + ',' + y + 'H' + (x1 - r) + 'A' + r + ',' + r + ' 0 0 1 ' + x1 + ',' + (y + r) + 'V' + (y + hgt - r) + 'A' + r + ',' + r + ' 0 0 1 ' + (x1 - r) + ',' + (y + hgt) + 'H' + x0 + 'Z';
    return 'M' + x0 + ',' + y + 'H' + (x1 + r) + 'A' + r + ',' + r + ' 0 0 0 ' + x1 + ',' + (y + r) + 'V' + (y + hgt - r) + 'A' + r + ',' + r + ' 0 0 0 ' + (x1 + r) + ',' + (y + hgt) + 'H' + x0 + 'Z';
  }

  /* ================================================================ horizontal bar chart (unordered categories) */
  function drawBar(f, o) {
    var rows = (o.labels || []).map(function (l, i) { return { label: l, value: isNum((o.values || [])[i]) ? o.values[i] : null, i: i }; });
    if (!rows.length || !rows.some(function (r) { return isNum(r.value); })) return emptyChart(f, o);
    if (o.sort === 'desc' || o.sort === 'asc') rows.sort(function (a, b) { var d = (a.value || 0) - (b.value || 0); return o.sort === 'desc' ? -d : d; });
    var full = o.formatValue || fmtFull(f.locale), unit = o.unit ? ' ' + o.unit : '', valFmt = o.format || full;
    var vals = rows.map(function (r) { return r.value || 0; }), lo = Math.min(0, Math.min.apply(null, vals)), hi = Math.max(0, Math.max.apply(null, vals));
    var W = f.width, rowH = 32, thick = 16, padT = 4;
    var labelW = Math.min(W * 0.38, Math.max.apply(null, rows.map(function (r) { return textWidth(r.label) * 1.05; })) + 8);
    var valueW = Math.max.apply(null, rows.map(function (r) { return textWidth(isNum(r.value) ? valFmt(r.value) + unit : '–'); })) + 8;
    var maxChars = Math.max(4, Math.floor((labelW - 6) / 6.6)), short = function (t) { t = String(t); return t.length > maxChars ? t.slice(0, maxChars - 1) + '…' : t; };
    var x0 = labelW + 8 + (lo < 0 ? valueW : 0), iw = Math.max(20, W - x0 - (hi > 0 ? valueW : 8)), H = padT * 2 + rows.length * rowH;
    var X = function (v) { return x0 + (v - lo) / ((hi - lo) || 1) * iw; };
    var svg = s('svg', { width: W, height: H, viewBox: '0 0 ' + W + ' ' + H, role: 'group', 'aria-roledescription': 'chart', 'aria-label': o.summary || o.title || 'Bar chart' }, f.plot);
    if (lo < 0) s('line', { x1: X(0), x2: X(0), y1: 0, y2: H, 'class': 'ca-chart__axis' }, svg);
    var bars = [];
    rows.forEach(function (r, k) {
      var y = padT + k * rowH, g = s('g', { 'class': 'ca-chart__bar' }, svg), cy = y + rowH / 2;
      var lt = s('text', { x: labelW, y: cy + 4, 'text-anchor': 'end', 'class': 'ca-chart__label' }, g);
      lt.textContent = short(r.label);
      if (short(r.label) !== String(r.label)) s('title', {}, lt).textContent = r.label;
      if (isNum(r.value) && r.value !== 0) {
        var muted = o.highlight != null && o.highlight !== r.i;
        s('path', { d: roundedEnd(X(0), X(r.value), cy - thick / 2, thick, 4), 'class': 'ca-chart__hbar' + (muted ? ' ca-chart__hbar--muted' : '') }, g);
      }
      var tipX = isNum(r.value) ? X(r.value) : X(0);
      s('text', { x: (r.value || 0) < 0 ? tipX - 6 : tipX + 6, y: cy + 4, 'text-anchor': (r.value || 0) < 0 ? 'end' : 'start', 'class': 'ca-chart__value' }, g).textContent = isNum(r.value) ? valFmt(r.value) + unit : '–';
      var hitR = s('rect', { x: 0, y: y, width: W, height: rowH, 'class': 'ca-chart__hit' }, g);
      hitR.addEventListener('pointerenter', function () { setCur(k); show(k); });
      hitR.addEventListener('pointerleave', hide);
      bars.push(g);
    });
    function describe(k) { return rows[k].label + ': ' + (isNum(rows[k].value) ? full(rows[k].value) + unit : 'no data'); }
    function show(k) {
      bars.forEach(function (b, j) { b.classList.toggle('is-dim', j !== k); b.classList.toggle('is-active', j === k && document.activeElement === svg); });
      f.tip.textContent = '';
      h('div', 'ca-tip__head', rows[k].label, f.tip);
      tipRow(f.tip, isNum(rows[k].value) ? full(rows[k].value) + unit : 'No data', o.name || '', 'ca-chart__k-bar', 'box');
      placeTip(f.tip, Math.min(W - 150, X(Math.max(0, rows[k].value || 0))), W);
      f.tip.style.top = (padT + k * rowH + rowH) + 'px';
    }
    function hide() { bars.forEach(function (b) { b.classList.remove('is-dim', 'is-active'); }); f.tip.hidden = true; }
    var setCur = keyNav(svg, rows.length, show, hide, describe);
    srTable(f.el, o.title || o.name || 'Chart data', [o.labelName || 'Label', o.name || 'Value'], rows.map(function (r) { return [r.label, isNum(r.value) ? full(r.value) + unit : 'No data']; }));
  }

  CA.lineChart = function (el, o) { return mount(el, o, drawLine); };
  CA.stackedBarChart = function (el, o) { return mount(el, o, drawStacked); };
  CA.barChart = function (el, o) { return mount(el, o, drawBar); };
  CA.format = { full: function (v, locale) { return fmtFull(locale)(v); } };

  /* ================================================================ theme */
  var THEME_KEY = 'ca-theme', mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  function stored() { try { return localStorage.getItem(THEME_KEY); } catch (e) { return null; } }
  CA.getTheme = function () { return stored() || 'system'; };
  CA.setTheme = function (mode, opts) {
    mode = mode === 'light' || mode === 'dark' ? mode : 'system';
    if (!opts || opts.persist !== false) { try { if (mode === 'system') localStorage.removeItem(THEME_KEY); else localStorage.setItem(THEME_KEY, mode); } catch (e) { /* private mode */ } }
    var resolved = mode === 'system' ? (mq && mq.matches ? 'dark' : 'light') : mode;
    document.documentElement.setAttribute('data-theme', resolved);
    emit(document.documentElement, 'ca:themechange', { mode: mode, theme: resolved });
    return resolved;
  };
  if (mq && mq.addEventListener) mq.addEventListener('change', function () {
    if (document.documentElement.hasAttribute('data-ca-theme-auto') && CA.getTheme() === 'system') CA.setTheme('system', { persist: false });
  });
  if (document.documentElement.hasAttribute('data-ca-theme-auto')) CA.setTheme(CA.getTheme(), { persist: false });

  /* ================================================================ radio groups and tabs (roving focus) */
  function roving(group, itemSel, selAttr, opts) {
    var items = function () { return $$(group, itemSel).filter(function (b) { return !b.disabled; }); };
    function sync() { var list = items(), sel = list.filter(function (b) { return b.getAttribute(selAttr) === 'true'; })[0] || list[0]; list.forEach(function (b) { b.tabIndex = b === sel ? 0 : -1; }); }
    function choose(btn) {
      items().forEach(function (b) { b.setAttribute(selAttr, b === btn ? 'true' : 'false'); });
      sync();
      if (opts.onChoose) opts.onChoose(btn);
      emit(group, 'ca:change', { value: btn.getAttribute('data-value') || btn.textContent.trim(), item: btn });
    }
    group.addEventListener('click', function (e) { var b = e.target.closest(itemSel); if (b && group.contains(b) && !b.disabled) choose(b); });
    group.addEventListener('keydown', function (e) {
      var list = items(), i = list.indexOf(document.activeElement);
      if (i < 0) return;
      var horiz = opts.vertical ? ['ArrowUp', 'ArrowDown'] : ['ArrowLeft', 'ArrowRight'], also = opts.vertical ? [] : ['ArrowUp', 'ArrowDown'];
      var k = e.key, j = null;
      if (k === horiz[0] || k === also[0]) j = (i - 1 + list.length) % list.length;
      else if (k === horiz[1] || k === also[1]) j = (i + 1) % list.length;
      else if (k === 'Home') j = 0;
      else if (k === 'End') j = list.length - 1;
      else if ((k === ' ' || k === 'Enter') && opts.manual) { e.preventDefault(); choose(list[i]); return; }
      if (j === null) return;
      e.preventDefault();
      list.forEach(function (b, x) { b.tabIndex = x === j ? 0 : -1; });
      list[j].focus();
      if (!opts.manual) choose(list[j]);
    });
    sync();
  }
  function bindTabs(root) {
    $$(root, '[role="tablist"]').forEach(function (tl) {
      if (!once(tl, 'tabs')) return;
      roving(tl, '[role="tab"]', 'aria-selected', { onChoose: function (tab) {
        $$(tl, '[role="tab"]').forEach(function (t) { var p = t.getAttribute('aria-controls') && document.getElementById(t.getAttribute('aria-controls')); if (p) p.hidden = t !== tab; });
      } });
    });
  }
  function bindRadios(root) {
    $$(root, '[role="radiogroup"]').forEach(function (rg) {
      if (!once(rg, 'radios')) return;
      roving(rg, '[role="radio"]', 'aria-checked', { manual: rg.hasAttribute('data-ca-manual'), vertical: rg.hasAttribute('data-ca-vertical') });
      if (rg.hasAttribute('data-ca-theme-toggle')) {
        var html = document.documentElement, mode = html.hasAttribute('data-ca-theme-auto') ? CA.getTheme() : (html.getAttribute('data-theme') || 'system');
        $$(rg, '[role="radio"]').forEach(function (b) { b.setAttribute('aria-checked', String(b.getAttribute('data-value') === mode)); b.tabIndex = b.getAttribute('data-value') === mode ? 0 : -1; });
        rg.addEventListener('ca:change', function (e) { CA.setTheme(e.detail.value); });
      }
    });
  }

  /* ================================================================ popovers: placement, menus, range picker */
  var lastInvoker = {}, invokedAt = 0;
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[popovertarget], [commandfor]');
    if (!b) return;
    var id = b.getAttribute('popovertarget') || b.getAttribute('commandfor');
    lastInvoker[id] = b; invokedAt = Date.now();
  }, true);
  function invokerOf(pop) { return lastInvoker[pop.id] || document.querySelector('[popovertarget="' + pop.id + '"], [commandfor="' + pop.id + '"]'); }
  function place(pop) {
    var inv = invokerOf(pop);
    if (!inv || !pop.matches(':popover-open')) return;
    var r = inv.getBoundingClientRect(), pw = pop.offsetWidth, ph = pop.offsetHeight, vw = document.documentElement.clientWidth, vh = window.innerHeight, gap = 6;
    var alignEnd = pop.getAttribute('data-ca-align') === 'end';
    var left = alignEnd ? r.right - pw : r.left, top = r.bottom + gap;
    if (top + ph > vh - 8 && r.top - gap - ph > 8) top = r.top - gap - ph;
    pop.style.left = clamp(left, 8, Math.max(8, vw - pw - 8)) + 'px';
    pop.style.top = clamp(top, 8, Math.max(8, vh - ph - 8)) + 'px';
    pop.style.visibility = '';
  }
  function bindPopover(pop) {
    if (!once(pop, 'pop')) return;
    var reflow = function () { place(pop); };
    pop.addEventListener('toggle', function (e) {
      var inv = invokerOf(pop);
      if (e.newState === 'open') {
        place(pop);
        window.addEventListener('resize', reflow); window.addEventListener('scroll', reflow, true);
        if (inv) inv.setAttribute('aria-expanded', 'true');
        if (Date.now() - invokedAt < 800) {
          var first = pop.querySelector('[role="menuitem"]:not([disabled]), [role="radio"][aria-checked="true"], [role="radio"], input, button:not([disabled])');
          if (first) first.focus();
        }
      } else {
        window.removeEventListener('resize', reflow); window.removeEventListener('scroll', reflow, true);
        if (inv) inv.setAttribute('aria-expanded', 'false');
        if (inv && (pop.contains(document.activeElement) || document.activeElement === document.body)) inv.focus();
      }
    });
  }
  function bindMenus(root) {
    $$(root, '.ca-pop[popover], .ca-topbar__tools[popover]').forEach(bindPopover);
    $$(root, '.ca-menu[popover]').forEach(function (menu) {
      if (!once(menu, 'menu')) return;
      menu.addEventListener('keydown', function (e) {
        var items = $$(menu, '[role="menuitem"]:not([disabled])'), i = items.indexOf(document.activeElement), j = null;
        if (e.key === 'ArrowDown') j = (i + 1) % items.length;
        else if (e.key === 'ArrowUp') j = (i - 1 + items.length) % items.length;
        else if (e.key === 'Home') j = 0;
        else if (e.key === 'End') j = items.length - 1;
        else if (e.key === 'Tab') { menu.hidePopover(); return; }
        if (j === null) return;
        e.preventDefault();
        items[j].focus();
      });
      menu.addEventListener('click', function (e) {
        var item = e.target.closest('[role="menuitem"]');
        if (!item || item.disabled) return;
        var inv = invokerOf(menu);
        if (!item.hasAttribute('data-ca-keep-open')) { menu.hidePopover(); if (inv) inv.focus(); }
        emit(menu, 'ca:select', { value: item.getAttribute('data-value') || item.textContent.trim(), item: item, invoker: inv });
      });
    });
    $$(root, '.ca-range[popover]').forEach(function (pop) {
      if (!once(pop, 'range')) return;
      var setLabel = function (text) { $$(document, '[popovertarget="' + pop.id + '"] .ca-btn__label').forEach(function (l) { l.textContent = text; }); };
      var presets = pop.querySelector('.ca-range__presets');
      if (presets) presets.addEventListener('ca:change', function (e) {
        e.stopPropagation();
        setLabel(e.detail.item.querySelector('span') ? e.detail.item.querySelector('span').textContent : e.detail.value);
        pop.hidePopover();
        emit(pop, 'ca:rangechange', { value: e.detail.value, label: e.detail.item.textContent.trim() });
      });
      var form = pop.querySelector('.ca-range__custom');
      if (form) form.addEventListener('submit', function (e) {
        e.preventDefault();
        var d = $$(form, 'input[type="date"]'), from = d[0] && d[0].value, to = d[1] && d[1].value;
        if (!from || !to || from > to) { d.forEach(function (x) { x.setAttribute('aria-invalid', String(!x.value || x === d[1])); }); (d[!from ? 0 : 1]).focus(); return; }
        d.forEach(function (x) { x.removeAttribute('aria-invalid'); });
        var f = function (iso) { return new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }); };
        $$(pop, '.ca-range__opt').forEach(function (o) { o.setAttribute('aria-checked', 'false'); });
        setLabel(f(from) + ' – ' + f(to));
        pop.hidePopover();
        emit(pop, 'ca:rangechange', { value: 'custom', from: from, to: to, label: f(from) + ' – ' + f(to) });
      });
    });
  }

  /* ================================================================ table selection and sorting */
  function bindSelect(root) {
    $$(root, 'table[data-ca-select]').forEach(function (table) {
      if (!once(table, 'select')) return;
      var all = table.querySelector('thead input[type="checkbox"]'), card = table.closest('.ca-tablecard'), bar = card && card.querySelector('.ca-bulkbar');
      var rows = function () { return $$(table, 'tbody input[type="checkbox"]'); };
      function sync() {
        var list = rows(), on = list.filter(function (c) { return c.checked; });
        list.forEach(function (c) { var tr = c.closest('tr'); if (tr) tr.setAttribute('aria-selected', String(c.checked)); });
        if (all) { all.checked = on.length > 0 && on.length === list.length; all.indeterminate = on.length > 0 && on.length < list.length; }
        if (bar) { bar.hidden = on.length === 0; var cnt = bar.querySelector('.ca-bulkbar__count'); if (cnt) cnt.textContent = on.length + ' selected'; }
        emit(table, 'ca:selectionchange', { count: on.length, rows: on.map(function (c) { return c.closest('tr'); }) });
      }
      table.addEventListener('change', function (e) {
        if (e.target === all) rows().forEach(function (c) { c.checked = all.checked; });
        if (e.target.type === 'checkbox') sync();
      });
      if (bar) bar.addEventListener('click', function (e) {
        if (e.target.closest('[data-ca-select-clear]')) { rows().forEach(function (c) { c.checked = false; }); sync(); if (all) all.focus(); }
      });
      sync();
    });
  }
  function sortKey(cell) {
    if (!cell) return '';
    var raw = cell.getAttribute('data-sort-value') != null ? cell.getAttribute('data-sort-value') : cell.textContent.trim();
    var num = raw.replace(/[^0-9.\-]/g, '');
    return num !== '' && !isNaN(+num) && /\d/.test(raw) && !/[a-z]{3,}/i.test(raw.replace(/[KMB%$€£]|AM|PM/gi, '')) ? +num : raw.toLowerCase();
  }
  function bindSort(root) {
    $$(root, 'table[data-ca-sort]').forEach(function (table) {
      if (!once(table, 'sort')) return;
      table.addEventListener('click', function (e) {
        var btn = e.target.closest('.ca-sort');
        if (!btn) return;
        var th = btn.closest('th'), col = th.cellIndex, dir = th.getAttribute('aria-sort') === 'ascending' ? 'descending' : 'ascending';
        $$(table, 'th[aria-sort]').forEach(function (o) { if (o !== th) o.removeAttribute('aria-sort'); });
        th.setAttribute('aria-sort', dir);
        $$(table, 'tbody').forEach(function (tb) {
          var segs = [[]], rowsAll = $$(tb, ':scope > tr');
          rowsAll.forEach(function (tr) { if (tr.classList.contains('ca-table__group')) segs.push([tr]); else segs[segs.length - 1].push(tr); });
          segs.forEach(function (seg) {
            var head = seg[0] && seg[0].classList.contains('ca-table__group') ? seg.shift() : null;
            seg.sort(function (a, b) { var x = sortKey(a.cells[col]), y = sortKey(b.cells[col]); var c = x < y ? -1 : x > y ? 1 : 0; return dir === 'ascending' ? c : -c; });
            if (head) tb.appendChild(head);
            seg.forEach(function (tr) { tb.appendChild(tr); });
          });
        });
        announce('Sorted by ' + btn.textContent.trim() + ', ' + dir);
        emit(table, 'ca:sort', { column: col, direction: dir });
      });
    });
  }

  /* ================================================================ nav drawer (narrow) and rail (wide) */
  var narrow = window.matchMedia ? window.matchMedia('(max-width: 860px)') : { matches: false };
  function frameOf(btn) { return btn.closest('.ca-frame') || document.querySelector('.ca-frame'); }
  function setRailTitles(frame, on) {
    $$(frame, '.ca-nav__item').forEach(function (a) { var t = a.querySelector('.ca-nav__text'); if (on && t) a.title = t.textContent; else a.removeAttribute('title'); });
  }
  function syncToggles(frame) {
    var drawer = narrow.matches, open = frame.classList.contains('is-nav-open'), rail = frame.classList.contains('ca-frame--rail');
    $$(frame, '[data-ca-toggle="nav"]').forEach(function (b) {
      var inMenu = b.classList.contains('ca-topbar__menu');
      b.setAttribute('aria-expanded', String(drawer ? open : !rail));
      b.setAttribute('aria-label', drawer ? (inMenu ? 'Open menu' : 'Close menu') : (rail ? 'Expand sidebar' : 'Collapse sidebar'));
    });
  }
  function closeDrawer(frame, focusBack) {
    frame.classList.remove('is-nav-open');
    var main = frame.querySelector('.ca-main'); if (main) main.inert = false;
    syncToggles(frame);
    if (focusBack) { var m = frame.querySelector('.ca-topbar__menu'); if (m) m.focus(); }
  }
  function openDrawer(frame) {
    if (!frame.querySelector(':scope > .ca-scrim')) { var sc = h('div', 'ca-scrim', null, frame); sc.addEventListener('click', function () { closeDrawer(frame, true); }); }
    frame.classList.add('is-nav-open');
    var main = frame.querySelector('.ca-main'); if (main) main.inert = true;
    syncToggles(frame);
    var first = frame.querySelector('.ca-sidebar a, .ca-sidebar button');
    setTimeout(function () { if (first) first.focus(); }, 60);
  }
  function bindNav(root) {
    $$(root, '.ca-frame').forEach(function (frame) {
      if (!once(frame, 'nav')) return;
      if (frame.hasAttribute('data-ca-persist')) { try { if (localStorage.getItem('ca-rail') === '1') frame.classList.add('ca-frame--rail'); } catch (e) { /* ignore */ } }
      setRailTitles(frame, frame.classList.contains('ca-frame--rail'));
      syncToggles(frame);
    });
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-ca-toggle="nav"]');
    if (!b) return;
    var frame = frameOf(b); if (!frame) return;
    if (narrow.matches) { if (frame.classList.contains('is-nav-open')) closeDrawer(frame, true); else openDrawer(frame); return; }
    var rail = frame.classList.toggle('ca-frame--rail');
    setRailTitles(frame, rail);
    if (frame.hasAttribute('data-ca-persist')) { try { localStorage.setItem('ca-rail', rail ? '1' : '0'); } catch (err) { /* ignore */ } }
    syncToggles(frame);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    $$(document, '.ca-frame.is-nav-open').forEach(function (f) { closeDrawer(f, true); });
  });
  if (narrow.addEventListener) narrow.addEventListener('change', function () {
    $$(document, '.ca-frame').forEach(function (f) { if (!narrow.matches && f.classList.contains('is-nav-open')) closeDrawer(f, false); syncToggles(f); });
    $$(document, '.ca-topbar__tools:popover-open').forEach(function (p) { p.hidePopover(); });
  });

  /* ================================================================ dialogs: invoker-command fallback and light dismiss */
  if (!('commandForElement' in HTMLButtonElement.prototype)) {
    document.addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('button[commandfor]');
      if (!b) return;
      var t = document.getElementById(b.getAttribute('commandfor')), cmd = b.getAttribute('command');
      if (!t) return;
      if (cmd === 'show-modal' && t.showModal && !t.open) t.showModal();
      else if ((cmd === 'close' || cmd === 'request-close') && t.close) t.close(b.value || '');
      else if (cmd === 'toggle-popover' && t.togglePopover) t.togglePopover();
      else if (cmd === 'show-popover' && t.showPopover) t.showPopover();
      else if (cmd === 'hide-popover' && t.hidePopover) t.hidePopover();
    });
  }
  if (window.HTMLDialogElement && !('closedBy' in HTMLDialogElement.prototype)) {
    document.addEventListener('click', function (e) {
      var d = e.target;
      if (d.tagName === 'DIALOG' && d.open && d.getAttribute('closedby') === 'any') {
        var r = d.getBoundingClientRect();
        if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) d.close();
      }
    });
  }

  /* ================================================================ form errors: mirror :user-invalid into aria-invalid */
  function syncInvalid(e) {
    var el = e.target;
    if (!el || !el.matches || !el.matches('.ca-input')) return;
    var bad = false;
    try { bad = el.matches(':user-invalid'); } catch (err) { bad = el.dataset.caTouched === '1' && el.validity && !el.validity.valid; }
    if (bad) el.setAttribute('aria-invalid', 'true'); else el.removeAttribute('aria-invalid');
  }
  document.addEventListener('blur', function (e) { if (e.target && e.target.dataset) e.target.dataset.caTouched = '1'; syncInvalid(e); }, true);
  document.addEventListener('input', function (e) { if (e.target && e.target.getAttribute && e.target.getAttribute('aria-invalid') === 'true') syncInvalid(e); }, true);
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form.matches || !form.matches('.ca-form') || form.noValidate === false && form.checkValidity()) return;
    var bad = $$(form, '.ca-input').filter(function (i) { return i.validity && !i.validity.valid; });
    bad.forEach(function (i) { i.setAttribute('aria-invalid', 'true'); });
    if (bad.length) { e.preventDefault(); bad[0].focus(); }
  }, true);

  /* ================================================================ toast */
  var stack;
  CA.toast = function (o) {
    o = o || {};
    if (!stack || !stack.isConnected) {
      stack = h('div', 'ca ca-toasts', null, document.body);
      if ('popover' in HTMLElement.prototype) stack.setAttribute('popover', 'manual');
    }
    var tone = o.tone === 'success' || o.tone === 'warning' || o.tone === 'critical' ? o.tone : 'neutral';
    var t = h('div', 'ca-toast ca-toast--' + tone, null, null);
    t.insertAdjacentHTML('afterbegin', icon(tone === 'success' ? 'circle-check' : tone === 'warning' || tone === 'critical' ? 'triangle-alert' : 'info'));
    var body = h('div', 'ca-toast__body', null, t);
    if (o.title) h('div', 'ca-toast__title', o.title, body);
    if (o.message) h('div', null, o.message, body);
    if (o.action && o.action.label) {
      var a = h('button', 'ca-btn ca-btn--sm ca-btn--ghost ca-toast__action', o.action.label, t);
      a.type = 'button';
      a.addEventListener('click', function () { if (o.action.onClick) o.action.onClick(); remove(); });
    }
    var x = h('button', 'ca-iconbtn', null, t);
    x.type = 'button'; x.setAttribute('aria-label', 'Dismiss'); x.insertAdjacentHTML('afterbegin', icon('x'));
    x.addEventListener('click', remove);
    stack.insertBefore(t, stack.firstChild);
    while (stack.children.length > 3) stack.removeChild(stack.lastChild);
    if (stack.hasAttribute('popover')) { if (stack.matches(':popover-open')) stack.hidePopover(); stack.showPopover(); }
    announce([o.title, o.message].filter(Boolean).join('. '));
    var ms = o.timeout === 0 ? 0 : (o.timeout || 5000), timer = ms ? setTimeout(remove, ms) : null;
    t.addEventListener('pointerenter', function () { clearTimeout(timer); });
    t.addEventListener('focusin', function () { clearTimeout(timer); });
    t.addEventListener('pointerleave', function () { if (ms) timer = setTimeout(remove, ms); });
    function remove() {
      clearTimeout(timer);
      if (t.parentNode) t.parentNode.removeChild(t);
      if (stack && !stack.children.length && stack.hasAttribute('popover') && stack.matches(':popover-open')) stack.hidePopover();
    }
    return { close: remove, el: t };
  };

  /* ================================================================ init */
  CA.init = function (root) {
    root = root || document;
    bindTabs(root); bindRadios(root); bindMenus(root); bindSelect(root); bindSort(root); bindNav(root);
    return CA;
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { CA.init(document); });
  else CA.init(document);
})();


/* ===================================================================================
   Kunto: the Kunto namespace on top of the shared engine (window.CalmAdmin).
   window.Kunto re-exports the engine's charts, toasts and theme calls, and adds the
   readiness zones, the status-word colours, the sport icons and the gauge.
   =================================================================================== */
(function () {
  'use strict';
  var CA = window.CalmAdmin || {};
  var K = window.Kunto = window.Kunto || {};
  ['init', 'lineChart', 'stackedBarChart', 'barChart', 'toast', 'setTheme', 'getTheme', 'format'].forEach(function (k) { if (CA[k]) K[k] = CA[k]; });
  var NS = 'http://www.w3.org/2000/svg';
  var num = function (v) { if (v == null || v === '') return null; var n = Number(v); return isFinite(n) ? n : null; };

  /* Readiness and body-state zones: 75+ good, 50+ ok, 25+ low, below 25 poor. */
  K.zone = function (v) { var n = num(v); return n === null ? null : n >= 75 ? 'good' : n >= 50 ? 'ok' : n >= 25 ? 'low' : 'poor'; };
  /* A five-step health level (meters): 4-5 good, 3 ok, 2 low, 1 poor, 0 or missing none. */
  K.levelZone = function (l) { var n = num(l); n = n === null ? 0 : Math.round(n); return n >= 4 ? 'good' : n === 3 ? 'ok' : n === 2 ? 'low' : n === 1 ? 'poor' : null; };

  /* Status words and their pill colours. Good things are green, the fair middle and the plan's
     own states violet, caution amber, things to act on red, quiet states grey, the unplanned outlined. */
  var WORDS = {
    'ca-badge--success': ['good', 'high', 'excellent', 'prime', 'balanced', 'optimal', 'productive', 'peaking', 'done', 'on plan', 'best yet'],
    'ca-badge--accent': ['fair', 'moderate', 'today', 'optional', 'moved', 'maintaining', 'recovery'],
    'ca-badge--warning': ['low', 'below target', 'above optimal', 'below optimal', 'over plan', 'under plan', 'unbalanced', 'unproductive', 'overreaching', 'strained'],
    'ca-badge--critical': ['poor', 'missed', 'detraining'],
    '': ['rest', 'skipped', 'tomorrow'],
    'ku-badge--ghost': ['planned', 'no data']
  };
  var LIST = [];
  Object.keys(WORDS).forEach(function (cls) { WORDS[cls].forEach(function (w) { LIST.push([w, cls]); }); });
  LIST.sort(function (a, b) { return b[0].length - a[0].length; });
  var reEsc = function (s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); };
  LIST.forEach(function (e) { e.push(new RegExp('^' + reEsc(e[0]) + '(?![a-z])'), new RegExp('(^|[^a-z])' + reEsc(e[0]) + '$')); });
  function lookup(text) {
    var w = String(text == null ? '' : text).replace(/[✓✔✗✘]/g, '').replace(/\s+/g, ' ').trim().toLowerCase(), i;
    if (!w) return null;
    for (i = 0; i < LIST.length; i++) if (LIST[i][0] === w) return LIST[i];
    for (i = 0; i < LIST.length; i++) if (LIST[i][2].test(w)) return LIST[i];
    for (i = 0; i < LIST.length; i++) if (LIST[i][3].test(w)) return LIST[i];
    return null;
  }
  /* Kunto.badgeClass(word, fallback): the pill class for a status word ("✓ Done", "Moved to Sun", "1 best yet").
     Exact words first, then a word at the start, then at the end. Unknown words get the fallback (default ''). */
  K.badgeClass = function (text, fallback) { var e = lookup(text); return e ? e[1] : (fallback == null ? '' : fallback); };
  /* Kunto.wordZone(phrase): the zone a verdict or status phrase means ("Productive" good, "Overreaching" low), or null. */
  K.wordZone = function (text) { var e = lookup(text); return e ? ({ 'ca-badge--success': 'good', 'ca-badge--accent': 'ok', 'ca-badge--warning': 'low', 'ca-badge--critical': 'poor' })[e[1]] || null : null; };

  /* Kunto's own sport icons from the original app, on Lucide's 24px grid: a runner, a barbell, a floorball.
     Anything else gets Lucide's activity line. Kunto.sportIcon(kind, extraClass) returns SVG markup. */
  var SPORT = {
    run: '<circle cx="14" cy="4.5" r="1.8"/><path d="M8 21l3-6 3 2 1 4M6 12l3-3 4 1 2 3 3 1"/>',
    lift: '<path d="M6 7v10M18 7v10M3 10v4M21 10v4M6 12h12"/>',
    ball: '<circle cx="12" cy="12" r="9"/><circle cx="9" cy="10" r="1.3"/><circle cx="15" cy="10" r="1.3"/><circle cx="12" cy="15" r="1.3"/>',
    other: '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>'
  };
  K.sportIcon = function (kind, cls) {
    var k = Object.prototype.hasOwnProperty.call(SPORT, kind) ? kind : 'other';
    return '<svg class="ca-icon' + (cls ? ' ' + String(cls).replace(/[^\w -]/g, '') : '') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + SPORT[k] + '</svg>';
  };

  function el(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(n);
    return n;
  }

  /* Kunto.gauge(target, { value, max = 100, level, zone, label })
     Draws a half-circle gauge into an <svg> (or appends one to a container).
     value: the score; level: the word under it ("POOR"); zone: 'good' | 'ok' | 'low' | 'poor' (default from value);
     label: what is measured, for the accessible name ("Training readiness"). Returns { el, update(options) }. */
  K.gauge = function (target, o) {
    var t = typeof target === 'string' ? document.querySelector(target) : target;
    if (!t) return null;
    var svg = t.tagName && t.tagName.toLowerCase() === 'svg' ? t : el('svg', {}, t);
    function draw(o) {
      o = o || {};
      var max = num(o.max) || 100, raw = num(o.value), v = Math.max(0, Math.min(max, raw || 0)), z = o.zone || K.zone(v / max * 100);
      var shown = raw === null ? '–' : String(o.value);
      var cx = 110, cy = 114, r = 90, pt = function (a) { return [cx + r * Math.cos(a), cy - r * Math.sin(a)]; };
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      svg.setAttribute('viewBox', '0 -6 220 144');
      svg.setAttribute('class', 'ku-gauge' + (raw === null ? '' : ' ku-zone--' + z));
      svg.setAttribute('role', 'img');
      svg.setAttribute('aria-label', (o.label || 'Score') + ' ' + (raw === null ? 'no data' : shown + ' of ' + max) + (o.level ? ', ' + String(o.level).toLowerCase() : ''));
      el('path', { 'class': 'ku-gauge__track', d: 'M' + (cx - r) + ' ' + cy + ' A' + r + ' ' + r + ' 0 0 1 ' + (cx + r) + ' ' + cy, 'stroke-width': 16, 'stroke-linecap': 'round' }, svg);
      var e = pt(Math.PI * (1 - v / max));
      if (v > 0) el('path', { 'class': 'ku-gauge__value', d: 'M' + (cx - r) + ' ' + cy + ' A' + r + ' ' + r + ' 0 0 1 ' + e[0].toFixed(1) + ' ' + e[1].toFixed(1), 'stroke-width': 16, 'stroke-linecap': 'round' }, svg);
      [0.25, 0.5, 0.75].forEach(function (f) {
        var a = Math.PI * (1 - f);
        el('line', { 'class': 'ku-gauge__tick', x1: (cx + (r + 11) * Math.cos(a)).toFixed(1), y1: (cy - (r + 11) * Math.sin(a)).toFixed(1), x2: (cx + (r + 16) * Math.cos(a)).toFixed(1), y2: (cy - (r + 16) * Math.sin(a)).toFixed(1), 'stroke-width': 1.5, 'stroke-linecap': 'round' }, svg);
      });
      el('text', { 'class': 'ku-gauge__num', x: cx, y: cy - 18, 'text-anchor': 'middle' }, svg).textContent = shown;
      if (o.level) el('text', { 'class': 'ku-gauge__lvl', x: cx, y: cy + 3, 'text-anchor': 'middle' }, svg).textContent = o.level;
      el('text', { 'class': 'ku-gauge__axis', x: cx - r, y: cy + 18, 'text-anchor': 'middle' }, svg).textContent = '0';
      el('text', { 'class': 'ku-gauge__axis', x: cx + r, y: cy + 18, 'text-anchor': 'middle' }, svg).textContent = String(max);
    }
    draw(o);
    return { el: svg, update: function (n) { o = n; draw(o); } };
  };
})();
