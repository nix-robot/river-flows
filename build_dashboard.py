#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""Fetch USGS flow data for California river stations and build a static HTML dashboard."""

import httpx
import json
from datetime import datetime, timezone

RIVERS = {
    "Kern River": {
        "stations": {
            "11189500": "SF Kern River nr Onyx",
            "11186000": "Kern River nr Kernville",
            "11194152": "Kern River at Bakersfield",
        },
        "color": "#2563eb",
    },
    "American River": {
        "stations": {
            "11427000": "NF American River at North Fork Dam",
            "11446500": "American River at Fair Oaks",
        },
        "color": "#059669",
    },
}

USGS_IV_URL = "https://waterservices.usgs.gov/nwis/iv/"
USGS_DV_URL = "https://waterservices.usgs.gov/nwis/dv/"


def all_site_ids() -> list[str]:
    ids = []
    for river in RIVERS.values():
        ids.extend(river["stations"].keys())
    return ids


def fetch_instantaneous(site_ids: list[str], period: str = "P7D") -> dict:
    resp = httpx.get(
        USGS_IV_URL,
        params={
            "format": "json",
            "sites": ",".join(site_ids),
            "parameterCd": "00060",
            "period": period,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_daily(site_ids: list[str], period: str = "P365D") -> dict:
    resp = httpx.get(
        USGS_DV_URL,
        params={
            "format": "json",
            "sites": ",".join(site_ids),
            "parameterCd": "00060",
            "period": period,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def extract_series(raw: dict) -> dict[str, dict]:
    result = {}
    for ts in raw["value"]["timeSeries"]:
        site = ts["sourceInfo"]["siteCode"][0]["value"]
        name = ts["sourceInfo"]["siteName"]
        values = [
            {"t": v["dateTime"], "v": float(v["value"]) if v["value"] != "" else None}
            for v in ts["values"][0]["value"]
            if v["value"] not in ("", "-999999")
        ]
        result[site] = {"name": name, "values": values}
    return result


def compute_stats(values: list[dict]) -> dict:
    nums = [v["v"] for v in values if v["v"] is not None]
    if not nums:
        return {"min": None, "max": None, "avg": None, "current": None, "trend": None}
    current = nums[-1]
    avg = sum(nums) / len(nums)
    # trend: compare last value to avg of first quarter
    quarter = max(1, len(nums) // 4)
    early_avg = sum(nums[:quarter]) / quarter
    if early_avg > 0:
        pct = ((current - early_avg) / early_avg) * 100
    else:
        pct = 0
    return {
        "min": min(nums),
        "max": max(nums),
        "avg": avg,
        "current": current,
        "trend": pct,
    }


def build_html(iv_data: dict, dv_data: dict) -> str:
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    river_sections = ""
    all_chart_data = {}

    station_colors_by_river = {
        "Kern River": ["#4a90a4", "#6bb5a0", "#c4956a"],
        "American River": ["#b07d4b", "#7a9e7e"],
    }
    fallback_colors = ["#4a90a4", "#6bb5a0", "#c4956a", "#b07d4b", "#7a9e7e"]

    river_idx = 0
    for river_name, river_info in RIVERS.items():
        cards = ""
        iv_datasets = []
        dv_datasets = []
        palette = station_colors_by_river.get(river_name, fallback_colors)

        for si, (site_id, label) in enumerate(river_info["stations"].items()):
            iv = iv_data.get(site_id, {"name": label, "values": []})
            dv = dv_data.get(site_id, {"name": label, "values": []})
            name = iv.get("name") or dv.get("name") or label
            color = palette[si % len(palette)]

            iv_stats = compute_stats(iv["values"])
            dv_stats = compute_stats(dv["values"])
            stats = iv_stats if iv_stats["current"] is not None else dv_stats

            current = f'{stats["current"]:,.0f}' if stats["current"] is not None else "---"
            has_data = stats["current"] is not None
            status_class = "active" if has_data else "inactive"

            trend_html = ""
            if stats["trend"] is not None and has_data:
                if stats["trend"] > 5:
                    arrow, trend_class = "&#8599;", "rising"
                elif stats["trend"] < -5:
                    arrow, trend_class = "&#8600;", "falling"
                else:
                    arrow, trend_class = "&#8594;", "steady"
                trend_html = f'<span class="gauge-trend {trend_class}">{arrow} {abs(stats["trend"]):.0f}%</span>'

            stats_row = ""
            if has_data:
                s = iv_stats if iv_stats["current"] is not None else dv_stats
                stats_row = f"""
                <div class="gauge-range">
                  <div class="range-bar">
                    <div class="range-fill" style="--min:{s['min']};--max:{s['max']};--cur:{s['current']};--color:{color}"></div>
                    <div class="range-marker" style="--min:{s['min']};--max:{s['max']};--cur:{s['current']}"></div>
                  </div>
                  <div class="range-labels">
                    <span>{s['min']:,.0f}</span>
                    <span class="range-avg">avg {s['avg']:,.0f}</span>
                    <span>{s['max']:,.0f}</span>
                  </div>
                </div>"""

            cards += f"""
            <div class="gauge {'off' if not has_data else ''}" style="--accent:{color};animation-delay:{river_idx * 200 + si * 100}ms">
              <div class="gauge-stripe" style="background:{color}"></div>
              <div class="gauge-body">
                <div class="gauge-header">
                  <span class="gauge-id">{site_id}</span>
                  <span class="gauge-status {'pulse' if has_data else ''}"></span>
                </div>
                <div class="gauge-name">{name}</div>
                <div class="gauge-reading">
                  <span class="reading-val">{current}</span>
                  <span class="reading-unit">ft&sup3;/s</span>
                  {trend_html}
                </div>
                {stats_row}
              </div>
            </div>"""

            if iv["values"]:
                iv_datasets.append({
                    "label": name,
                    "data": [{"x": v["t"], "y": v["v"]} for v in iv["values"] if v["v"] is not None],
                    "borderColor": color,
                    "backgroundColor": color + "15",
                    "fill": True,
                    "tension": 0.4,
                    "pointRadius": 0,
                    "pointHitRadius": 8,
                    "borderWidth": 2.5,
                })

            if dv["values"]:
                dv_datasets.append({
                    "label": name,
                    "data": [{"x": v["t"], "y": v["v"]} for v in dv["values"] if v["v"] is not None],
                    "borderColor": color,
                    "backgroundColor": color + "15",
                    "fill": True,
                    "tension": 0.4,
                    "pointRadius": 0,
                    "pointHitRadius": 8,
                    "borderWidth": 2.5,
                })

        river_id = river_name.replace(" ", "").lower()
        all_chart_data[river_id] = {"iv": iv_datasets, "dv": dv_datasets}

        river_sections += f"""
        <section class="river" id="sec-{river_id}">
          <div class="river-header">
            <svg class="river-icon" viewBox="0 0 32 32" fill="none"><path d="M4 16c4-6 8 6 12 0s8 6 12 0" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/><path d="M4 22c4-6 8 6 12 0s8 6 12 0" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" opacity="0.4"/></svg>
            <h2>{river_name}</h2>
            <span class="river-count">{len(river_info['stations'])} gauges</span>
          </div>
          <div class="gauges">{cards}</div>
          <div class="hydro">
            <div class="hydro-toolbar">
              <div class="hydro-tabs">
                <button class="htab active" onclick="showTab('{river_id}','7d')">7d</button>
                <button class="htab" onclick="showTab('{river_id}','365d')">1yr</button>
              </div>
              <span class="hydro-label">Discharge Hydrograph</span>
            </div>
            <div class="hydro-chart">
              <canvas id="{river_id}-7d"></canvas>
              <canvas id="{river_id}-365d" style="display:none"></canvas>
            </div>
          </div>
        </section>"""
        river_idx += 1

    chart_data_json = json.dumps(all_chart_data)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>California River Flows</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3"></script>
<style>
  :root {{
    --bg: #1a1f16;
    --bg2: #222819;
    --bg3: #2a3120;
    --sand: #d4c5a0;
    --sand-dim: #9c9070;
    --sand-bright: #e8dcc0;
    --cream: #f0e8d4;
    --water: #4a90a4;
    --water-glow: #5cb8d4;
    --bark: #8b7355;
    --moss: #5a6b42;
    --contour: #2a3120;
    --danger: #c4654a;
    --safe: #6bb5a0;
  }}

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    font-family: 'IBM Plex Sans', sans-serif;
    background: var(--bg);
    color: var(--sand);
    line-height: 1.5;
    min-height: 100vh;
    position: relative;
  }}

  body::before {{
    content: '';
    position: fixed; inset: 0; z-index: 0; pointer-events: none;
    background:
      repeating-linear-gradient(0deg, transparent, transparent 39px, var(--contour) 39px, var(--contour) 40px),
      repeating-linear-gradient(90deg, transparent, transparent 39px, var(--contour) 39px, var(--contour) 40px);
    opacity: 0.3;
  }}

  body::after {{
    content: '';
    position: fixed; inset: 0; z-index: 0; pointer-events: none;
    background: url("data:image/svg+xml,%3Csvg width='400' height='400' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
    opacity: 0.6;
  }}

  .page {{ position: relative; z-index: 1; max-width: 1100px; margin: 0 auto; padding: 0 1.5rem 3rem; }}

  /* === HEADER === */
  header {{
    padding: 3rem 0 2rem;
    border-bottom: 1px solid var(--contour);
    margin-bottom: 2.5rem;
    position: relative;
  }}
  header::after {{
    content: '';
    position: absolute; bottom: -1px; left: 0;
    width: 120px; height: 3px;
    background: var(--water);
  }}

  .header-eyebrow {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.2em;
    color: var(--sand-dim);
    margin-bottom: 0.75rem;
  }}

  h1 {{
    font-family: 'Playfair Display', serif;
    font-weight: 900;
    font-size: clamp(2rem, 5vw, 3.2rem);
    color: var(--cream);
    line-height: 1.1;
    letter-spacing: -0.02em;
  }}
  h1 span {{
    color: var(--water);
  }}

  .header-meta {{
    display: flex; align-items: center; gap: 1.5rem;
    margin-top: 1rem;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    color: var(--sand-dim);
  }}
  .header-meta .dot {{ width: 6px; height: 6px; border-radius: 50%; background: var(--safe); animation: blink 2s infinite; }}
  @keyframes blink {{ 0%,100% {{ opacity: 1 }} 50% {{ opacity: 0.3 }} }}

  /* === RIVER SECTIONS === */
  .river {{ margin-bottom: 3rem; }}
  .river-header {{
    display: flex; align-items: center; gap: 0.75rem;
    margin-bottom: 1.25rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px dashed var(--contour);
  }}
  .river-icon {{ width: 28px; height: 28px; color: var(--water); flex-shrink: 0; }}
  .river-header h2 {{
    font-family: 'Playfair Display', serif;
    font-weight: 700;
    font-size: 1.4rem;
    color: var(--cream);
    letter-spacing: -0.01em;
  }}
  .river-count {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    color: var(--sand-dim);
    background: var(--bg2);
    padding: 0.2rem 0.6rem;
    border-radius: 3px;
    border: 1px solid var(--contour);
    margin-left: auto;
  }}

  /* === GAUGE CARDS === */
  .gauges {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 0.75rem;
    margin-bottom: 1.25rem;
  }}

  .gauge {{
    background: var(--bg2);
    border: 1px solid var(--contour);
    border-radius: 2px;
    display: flex;
    overflow: hidden;
    animation: slideUp 0.5s ease both;
    transition: border-color 0.2s, box-shadow 0.2s;
  }}
  .gauge:hover {{
    border-color: var(--bark);
    box-shadow: 0 2px 20px rgba(0,0,0,0.3);
  }}
  .gauge.off {{ opacity: 0.45; }}

  @keyframes slideUp {{
    from {{ opacity: 0; transform: translateY(12px); }}
    to {{ opacity: 1; transform: translateY(0); }}
  }}

  .gauge-stripe {{ width: 4px; flex-shrink: 0; }}
  .gauge-body {{ padding: 0.9rem 1rem; flex: 1; min-width: 0; }}

  .gauge-header {{
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 0.4rem;
  }}
  .gauge-id {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    color: var(--sand-dim);
    letter-spacing: 0.05em;
  }}
  .gauge-status {{
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--sand-dim);
  }}
  .gauge-status.pulse {{
    background: var(--safe);
    box-shadow: 0 0 6px var(--safe);
    animation: blink 2s infinite;
  }}

  .gauge-name {{
    font-size: 0.78rem;
    font-weight: 500;
    color: var(--sand);
    margin-bottom: 0.6rem;
    line-height: 1.3;
  }}

  .gauge-reading {{
    display: flex; align-items: baseline; gap: 0.3rem;
    margin-bottom: 0.6rem;
  }}
  .reading-val {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.8rem;
    font-weight: 600;
    color: var(--cream);
    letter-spacing: -0.03em;
    line-height: 1;
  }}
  .reading-unit {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.7rem;
    color: var(--sand-dim);
  }}
  .gauge-trend {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    font-weight: 500;
    margin-left: auto;
    padding: 0.15rem 0.5rem;
    border-radius: 2px;
  }}
  .gauge-trend.rising {{ color: var(--safe); background: rgba(107,181,160,0.1); }}
  .gauge-trend.falling {{ color: var(--danger); background: rgba(196,101,74,0.1); }}
  .gauge-trend.steady {{ color: var(--sand-dim); background: rgba(156,144,112,0.1); }}

  /* Range bar */
  .gauge-range {{ margin-top: 0.25rem; }}
  .range-bar {{
    height: 4px; border-radius: 2px;
    background: var(--bg);
    position: relative;
    overflow: hidden;
  }}
  .range-fill {{
    position: absolute; inset: 0;
    background: var(--color, var(--water));
    opacity: 0.3;
    border-radius: 2px;
  }}
  .range-marker {{
    position: absolute; top: -2px;
    width: 2px; height: 8px;
    background: var(--cream);
    border-radius: 1px;
    left: calc((var(--cur) - var(--min)) / (var(--max) - var(--min) + 0.001) * 100%);
  }}
  .range-labels {{
    display: flex; justify-content: space-between;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6rem;
    color: var(--sand-dim);
    margin-top: 0.3rem;
  }}
  .range-avg {{ color: var(--bark); }}

  /* === HYDROGRAPH === */
  .hydro {{
    background: var(--bg2);
    border: 1px solid var(--contour);
    border-radius: 2px;
    overflow: hidden;
  }}
  .hydro-toolbar {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 0.6rem 1rem;
    border-bottom: 1px solid var(--contour);
  }}
  .hydro-tabs {{ display: flex; gap: 2px; }}
  .htab {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.7rem; font-weight: 500;
    padding: 0.3rem 0.8rem;
    background: transparent; border: 1px solid var(--contour);
    color: var(--sand-dim); cursor: pointer;
    transition: all 0.15s;
  }}
  .htab:first-child {{ border-radius: 2px 0 0 2px; }}
  .htab:last-child {{ border-radius: 0 2px 2px 0; }}
  .htab:hover {{ color: var(--sand); }}
  .htab.active {{
    background: var(--water);
    border-color: var(--water);
    color: var(--bg);
  }}
  .hydro-label {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    color: var(--sand-dim);
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }}
  .hydro-chart {{
    position: relative;
    height: 300px;
    padding: 1rem;
  }}
  .hydro-chart canvas {{
    position: absolute;
    inset: 0.75rem;
  }}

  /* === FOOTER === */
  footer {{
    border-top: 1px solid var(--contour);
    padding: 1.5rem 0 0;
    display: flex; justify-content: space-between; align-items: center;
    flex-wrap: wrap; gap: 0.5rem;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    color: var(--sand-dim);
  }}
  footer a {{
    color: var(--water);
    text-decoration: none;
    border-bottom: 1px solid transparent;
    transition: border-color 0.15s;
  }}
  footer a:hover {{ border-color: var(--water); }}

  /* === TOPO DECORATION === */
  .topo-lines {{
    position: absolute;
    top: 0; right: 0;
    width: 300px; height: 300px;
    opacity: 0.08;
    pointer-events: none;
  }}

  @media (max-width: 640px) {{
    .page {{ padding: 0 1rem 2rem; }}
    header {{ padding: 2rem 0 1.5rem; }}
    .gauges {{ grid-template-columns: 1fr; }}
    .reading-val {{ font-size: 1.5rem; }}
    .hydro-chart {{ height: 220px; }}
    .hydro-label {{ display: none; }}
    footer {{ flex-direction: column; align-items: flex-start; }}
  }}
</style>
</head>
<body>
<div class="page">
  <header>
    <svg class="topo-lines" viewBox="0 0 300 300" fill="none">
      <ellipse cx="200" cy="120" rx="140" ry="80" stroke="var(--sand)" stroke-width="0.5"/>
      <ellipse cx="200" cy="120" rx="115" ry="65" stroke="var(--sand)" stroke-width="0.5"/>
      <ellipse cx="200" cy="120" rx="90" ry="50" stroke="var(--sand)" stroke-width="0.5"/>
      <ellipse cx="200" cy="120" rx="65" ry="35" stroke="var(--sand)" stroke-width="0.5"/>
      <ellipse cx="200" cy="120" rx="40" ry="20" stroke="var(--sand)" stroke-width="0.5"/>
      <ellipse cx="80" cy="220" rx="100" ry="60" stroke="var(--sand)" stroke-width="0.5"/>
      <ellipse cx="80" cy="220" rx="75" ry="45" stroke="var(--sand)" stroke-width="0.5"/>
      <ellipse cx="80" cy="220" rx="50" ry="30" stroke="var(--sand)" stroke-width="0.5"/>
    </svg>
    <div class="header-eyebrow">USGS National Water Information System</div>
    <h1>California<br><span>River Flows</span></h1>
    <div class="header-meta">
      <span class="dot"></span>
      <span>Live gauges</span>
      <span>&middot;</span>
      <span>{updated}</span>
    </div>
  </header>

  {river_sections}

  <footer>
    <span>Data sourced from USGS NWIS waterservices</span>
    <a href="transcript/">Build transcript</a>
  </footer>
</div>

<script>
const CD = {chart_data_json};
const charts = {{}};

const gridColor = 'rgba(42,49,32,0.6)';
const tickColor = '#9c9070';
const tooltipBg = '#222819';
const tooltipBorder = '#2a3120';

function makeChart(id, datasets, unit) {{
  const el = document.getElementById(id);
  if (!el) return;
  charts[id] = new Chart(el, {{
    type: 'line',
    data: {{ datasets }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{
          position: 'top',
          align: 'end',
          labels: {{
            color: tickColor,
            usePointStyle: true,
            pointStyle: 'rectRounded',
            boxWidth: 8,
            padding: 20,
            font: {{ family: "'IBM Plex Mono', monospace", size: 10 }}
          }}
        }},
        tooltip: {{
          backgroundColor: tooltipBg,
          titleColor: '#e8dcc0',
          bodyColor: '#d4c5a0',
          borderColor: tooltipBorder,
          borderWidth: 1,
          padding: 12,
          cornerRadius: 2,
          titleFont: {{ family: "'IBM Plex Mono', monospace", size: 11 }},
          bodyFont: {{ family: "'IBM Plex Mono', monospace", size: 11 }},
          callbacks: {{
            label: c => '  ' + c.dataset.label + ': ' + (c.parsed.y?.toLocaleString() ?? '---') + ' cfs'
          }}
        }}
      }},
      scales: {{
        x: {{
          type: 'time',
          time: {{ unit }},
          ticks: {{ color: tickColor, maxTicksLimit: 8, font: {{ family: "'IBM Plex Mono', monospace", size: 10 }} }},
          grid: {{ color: gridColor, lineWidth: 0.5 }},
          border: {{ color: gridColor }}
        }},
        y: {{
          title: {{ display: true, text: 'DISCHARGE (CFS)', color: tickColor, font: {{ family: "'IBM Plex Mono', monospace", size: 9 }}, padding: 8 }},
          ticks: {{ color: tickColor, font: {{ family: "'IBM Plex Mono', monospace", size: 10 }}, callback: v => v.toLocaleString() }},
          grid: {{ color: gridColor, lineWidth: 0.5 }},
          border: {{ color: gridColor }},
          beginAtZero: true
        }}
      }}
    }}
  }});
}}

Object.entries(CD).forEach(([id, d]) => {{
  makeChart(id + '-7d', d.iv, 'day');
  makeChart(id + '-365d', d.dv, 'month');
}});

function showTab(rid, period) {{
  const wrap = document.getElementById(rid + '-7d')?.closest('.hydro');
  if (!wrap) return;
  wrap.querySelectorAll('canvas').forEach(c => c.style.display = 'none');
  wrap.querySelectorAll('.htab').forEach(t => t.classList.remove('active'));
  const cv = document.getElementById(rid + '-' + period);
  if (cv) cv.style.display = 'block';
  wrap.querySelectorAll('.htab').forEach(t => {{
    if ((period === '7d' && t.textContent === '7d') || (period === '365d' && t.textContent === '1yr'))
      t.classList.add('active');
  }});
  const k = rid + '-' + period;
  if (charts[k]) charts[k].resize();
}}
</script>
</body>
</html>"""


def main():
    site_ids = all_site_ids()
    print("Fetching instantaneous values (7 days)...")
    iv_raw = fetch_instantaneous(site_ids)
    iv_data = extract_series(iv_raw)

    print("Fetching daily values (365 days)...")
    dv_raw = fetch_daily(site_ids)
    dv_data = extract_series(dv_raw)

    print("Building dashboard...")
    html = build_html(iv_data, dv_data)

    with open("index.html", "w") as f:
        f.write(html)
    print("Wrote index.html")


if __name__ == "__main__":
    main()
