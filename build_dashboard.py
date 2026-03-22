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

    # Build river sections
    river_sections = ""
    all_chart_data = {}  # river_name -> {iv: [...], dv: [...]}

    station_colors = [
        "#60a5fa", "#34d399", "#fbbf24", "#f87171", "#a78bfa",
        "#38bdf8", "#4ade80", "#facc15", "#fb923c", "#c084fc",
    ]
    color_idx = 0

    for river_name, river_info in RIVERS.items():
        river_color = river_info["color"]
        cards = ""
        iv_datasets = []
        dv_datasets = []

        for site_id, label in river_info["stations"].items():
            iv = iv_data.get(site_id, {"name": label, "values": []})
            dv = dv_data.get(site_id, {"name": label, "values": []})
            name = iv.get("name") or dv.get("name") or label
            color = station_colors[color_idx % len(station_colors)]
            color_idx += 1

            iv_stats = compute_stats(iv["values"])
            dv_stats = compute_stats(dv["values"])
            stats = iv_stats if iv_stats["current"] is not None else dv_stats

            current = f'{stats["current"]:.0f}' if stats["current"] is not None else "N/A"
            has_data = stats["current"] is not None
            status_class = "active" if has_data else "inactive"

            trend_html = ""
            if stats["trend"] is not None and has_data:
                arrow = "&#9650;" if stats["trend"] > 5 else "&#9660;" if stats["trend"] < -5 else "&#9654;"
                trend_class = "up" if stats["trend"] > 5 else "down" if stats["trend"] < -5 else "flat"
                trend_html = f'<span class="trend {trend_class}">{arrow} {abs(stats["trend"]):.0f}%</span>'

            stats_row = ""
            if has_data:
                s = iv_stats if iv_stats["current"] is not None else dv_stats
                stats_row = f"""
                <div class="stats-row">
                  <div class="stat"><span class="stat-label">Min</span><span class="stat-value">{s['min']:.0f}</span></div>
                  <div class="stat"><span class="stat-label">Avg</span><span class="stat-value">{s['avg']:.0f}</span></div>
                  <div class="stat"><span class="stat-label">Max</span><span class="stat-value">{s['max']:.0f}</span></div>
                </div>"""

            cards += f"""
            <div class="card {status_class}">
              <div class="card-dot" style="background:{color}"></div>
              <div class="card-name">{name}</div>
              <div class="card-flow">
                <span class="flow-value">{current}</span>
                <span class="flow-unit">cfs</span>
                {trend_html}
              </div>
              {stats_row}
              <div class="card-meta">Site {site_id}</div>
            </div>"""

            if iv["values"]:
                iv_datasets.append({
                    "label": name,
                    "data": [{"x": v["t"], "y": v["v"]} for v in iv["values"] if v["v"] is not None],
                    "borderColor": color,
                    "backgroundColor": color + "18",
                    "fill": True,
                    "tension": 0.3,
                    "pointRadius": 0,
                    "borderWidth": 2,
                })

            if dv["values"]:
                dv_datasets.append({
                    "label": name,
                    "data": [{"x": v["t"], "y": v["v"]} for v in dv["values"] if v["v"] is not None],
                    "borderColor": color,
                    "backgroundColor": color + "18",
                    "fill": True,
                    "tension": 0.3,
                    "pointRadius": 0,
                    "borderWidth": 2,
                })

        river_id = river_name.replace(" ", "").lower()
        all_chart_data[river_id] = {"iv": iv_datasets, "dv": dv_datasets}

        river_sections += f"""
        <section class="river-section">
          <h2 class="river-title"><span class="river-dot" style="background:{river_color}"></span>{river_name}</h2>
          <div class="cards">{cards}</div>
          <div class="chart-panel">
            <div class="chart-tabs">
              <button class="tab active" onclick="showTab('{river_id}', '7d')">7 Day</button>
              <button class="tab" onclick="showTab('{river_id}', '365d')">365 Day</button>
            </div>
            <div class="chart-wrap">
              <canvas id="{river_id}-7d"></canvas>
              <canvas id="{river_id}-365d" style="display:none"></canvas>
            </div>
          </div>
        </section>"""

    chart_data_json = json.dumps(all_chart_data)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>California River Flows</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0f172a; color: #e2e8f0; line-height: 1.5;
    padding: 1rem 1rem 2rem; max-width: 1200px; margin: 0 auto;
  }}
  header {{ margin-bottom: 2rem; }}
  h1 {{ font-size: 1.6rem; font-weight: 700; }}
  .subtitle {{ color: #94a3b8; font-size: 0.8rem; margin-top: 0.25rem; }}
  .river-section {{ margin-bottom: 2.5rem; }}
  .river-title {{
    font-size: 1.15rem; font-weight: 600; color: #f1f5f9;
    display: flex; align-items: center; gap: 0.5rem;
    margin-bottom: 1rem; padding-bottom: 0.5rem;
    border-bottom: 1px solid #1e293b;
  }}
  .river-dot {{ width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }}
  .cards {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 0.75rem; margin-bottom: 1rem;
  }}
  .card {{
    background: #1e293b; border-radius: 10px; padding: 1rem;
    border: 1px solid #334155; position: relative; overflow: hidden;
  }}
  .card.inactive {{ opacity: 0.5; }}
  .card-dot {{
    width: 8px; height: 8px; border-radius: 50%;
    position: absolute; top: 1rem; right: 1rem;
  }}
  .card-name {{ font-size: 0.78rem; color: #94a3b8; font-weight: 500; margin-bottom: 0.5rem; padding-right: 1rem; }}
  .card-flow {{ display: flex; align-items: baseline; gap: 0.35rem; margin-bottom: 0.5rem; }}
  .flow-value {{ font-size: 1.75rem; font-weight: 700; color: #f1f5f9; }}
  .flow-unit {{ font-size: 0.8rem; color: #64748b; }}
  .trend {{ font-size: 0.75rem; font-weight: 600; margin-left: 0.25rem; }}
  .trend.up {{ color: #34d399; }}
  .trend.down {{ color: #f87171; }}
  .trend.flat {{ color: #94a3b8; }}
  .stats-row {{
    display: flex; gap: 1rem; padding-top: 0.5rem;
    border-top: 1px solid #334155; margin-top: 0.25rem;
  }}
  .stat {{ display: flex; flex-direction: column; }}
  .stat-label {{ font-size: 0.65rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }}
  .stat-value {{ font-size: 0.85rem; font-weight: 600; color: #cbd5e1; }}
  .card-meta {{ font-size: 0.65rem; color: #475569; margin-top: 0.5rem; }}
  .chart-panel {{
    background: #1e293b; border-radius: 10px; padding: 1rem;
    border: 1px solid #334155;
  }}
  .chart-tabs {{ display: flex; gap: 0.5rem; margin-bottom: 0.75rem; }}
  .tab {{
    background: #0f172a; border: 1px solid #334155; color: #94a3b8;
    padding: 0.35rem 1rem; border-radius: 6px; cursor: pointer;
    font-size: 0.8rem; font-weight: 500; transition: all 0.15s;
  }}
  .tab:hover {{ color: #e2e8f0; border-color: #475569; }}
  .tab.active {{ background: #334155; color: #f1f5f9; border-color: #475569; }}
  .chart-wrap {{ position: relative; height: 280px; }}
  .chart-wrap canvas {{ position: absolute; inset: 0; }}
  footer {{ text-align: center; color: #475569; font-size: 0.7rem; padding-top: 1rem; }}
  @media (max-width: 600px) {{
    h1 {{ font-size: 1.3rem; }}
    .cards {{ grid-template-columns: 1fr; }}
    .flow-value {{ font-size: 1.5rem; }}
    .chart-wrap {{ height: 220px; }}
  }}
</style>
</head>
<body>
  <header>
    <h1>California River Flows</h1>
    <p class="subtitle">USGS real-time discharge &middot; Updated {updated}</p>
  </header>
  {river_sections}
  <footer>Data from USGS National Water Information System &middot; <a href="transcript/" style="color:#64748b">Build transcript</a></footer>

<script>
const chartData = {chart_data_json};
const charts = {{}};

function makeChart(canvasId, datasets, timeUnit) {{
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  charts[canvasId] = new Chart(ctx, {{
    type: 'line',
    data: {{ datasets }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ position: 'top', labels: {{ color: '#94a3b8', usePointStyle: true, pointStyle: 'circle', boxWidth: 6, padding: 16, font: {{ size: 11 }} }} }},
        tooltip: {{
          backgroundColor: '#1e293b', titleColor: '#f1f5f9', bodyColor: '#cbd5e1',
          borderColor: '#334155', borderWidth: 1, padding: 10,
          callbacks: {{ label: ctx => ctx.dataset.label + ': ' + (ctx.parsed.y?.toLocaleString() ?? 'N/A') + ' cfs' }}
        }}
      }},
      scales: {{
        x: {{
          type: 'time', time: {{ unit: timeUnit }},
          ticks: {{ color: '#64748b', maxTicksLimit: 8, font: {{ size: 10 }} }},
          grid: {{ color: '#1e293b' }}
        }},
        y: {{
          title: {{ display: true, text: 'cfs', color: '#64748b', font: {{ size: 10 }} }},
          ticks: {{ color: '#64748b', font: {{ size: 10 }}, callback: v => v.toLocaleString() }},
          grid: {{ color: '#1e293b44' }},
          beginAtZero: true
        }}
      }}
    }}
  }});
}}

for (const [riverId, data] of Object.entries(chartData)) {{
  makeChart(riverId + '-7d', data.iv, 'day');
  makeChart(riverId + '-365d', data.dv, 'month');
}}

function showTab(riverId, period) {{
  const section = document.getElementById(riverId + '-7d')?.closest('.chart-panel');
  if (!section) return;
  section.querySelectorAll('canvas').forEach(c => c.style.display = 'none');
  section.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  const canvas = document.getElementById(riverId + '-' + period);
  if (canvas) canvas.style.display = 'block';
  const tabs = section.querySelectorAll('.tab');
  tabs.forEach(t => {{ if (t.textContent.toLowerCase().includes(period.replace('d',''))) t.classList.add('active'); }});
  const chartKey = riverId + '-' + period;
  if (charts[chartKey]) charts[chartKey].resize();
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
