#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""Fetch USGS flow data for California river stations and build a static HTML dashboard."""

import httpx
import json
from datetime import datetime, timezone

STATIONS = {
    "11189500": "SF Kern River nr Onyx",
    "11186000": "Kern River nr Kernville",
    "11194152": "Kern River at Bakersfield",
    "11427000": "NF American River at North Fork Dam",
    "11446500": "American River at Fair Oaks",
}

USGS_IV_URL = "https://waterservices.usgs.gov/nwis/iv/"
USGS_DV_URL = "https://waterservices.usgs.gov/nwis/dv/"


def fetch_instantaneous(site_ids: list[str], period: str = "P7D") -> dict:
    """Fetch 15-minute instantaneous discharge values."""
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
    """Fetch daily mean discharge values."""
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


def extract_series(raw: dict) -> dict[str, list[dict]]:
    """Extract time series data grouped by site code."""
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


def build_html(iv_data: dict, dv_data: dict) -> str:
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Prepare station cards data
    cards_html = ""
    chart_datasets_iv = []
    chart_datasets_dv = []
    colors = ["#2563eb", "#059669", "#d97706", "#dc2626", "#8b5cf6"]

    active_stations = []
    for i, (site_id, label) in enumerate(STATIONS.items()):
        iv = iv_data.get(site_id, {"name": label, "values": []})
        dv = dv_data.get(site_id, {"name": label, "values": []})
        name = iv.get("name") or dv.get("name") or label
        color = colors[i % len(colors)]

        # Latest reading
        latest_val = "N/A"
        latest_time = ""
        if iv["values"]:
            last = iv["values"][-1]
            latest_val = f'{last["v"]:.0f} cfs' if last["v"] is not None else "N/A"
            latest_time = last["t"]
        elif dv["values"]:
            last = dv["values"][-1]
            latest_val = f'{last["v"]:.0f} cfs' if last["v"] is not None else "N/A"
            latest_time = last["t"]

        has_data = bool(iv["values"] or dv["values"])
        status = "active" if has_data else "inactive"

        cards_html += f"""
        <div class="card">
          <div class="card-header">
            <span class="dot" style="background:{color}"></span>
            <h3>{name}</h3>
          </div>
          <div class="card-body">
            <div class="big-number">{latest_val}</div>
            <div class="meta">Site {site_id} &middot; {status}</div>
          </div>
        </div>"""

        if iv["values"]:
            active_stations.append(site_id)
            chart_datasets_iv.append(
                {
                    "label": name,
                    "data": [
                        {"x": v["t"], "y": v["v"]}
                        for v in iv["values"]
                        if v["v"] is not None
                    ],
                    "borderColor": color,
                    "backgroundColor": color + "20",
                    "fill": True,
                    "tension": 0.3,
                    "pointRadius": 0,
                    "borderWidth": 2,
                }
            )

        if dv["values"]:
            if site_id not in active_stations:
                active_stations.append(site_id)
            chart_datasets_dv.append(
                {
                    "label": name,
                    "data": [
                        {"x": v["t"], "y": v["v"]}
                        for v in dv["values"]
                        if v["v"] is not None
                    ],
                    "borderColor": color,
                    "backgroundColor": color + "20",
                    "fill": True,
                    "tension": 0.3,
                    "pointRadius": 0,
                    "borderWidth": 2,
                }
            )

    iv_json = json.dumps(chart_datasets_iv)
    dv_json = json.dumps(chart_datasets_dv)

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
    padding: 1rem; max-width: 1200px; margin: 0 auto;
  }}
  h1 {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 0.25rem; }}
  .subtitle {{ color: #94a3b8; font-size: 0.85rem; margin-bottom: 1.5rem; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }}
  .card {{
    background: #1e293b; border-radius: 12px; padding: 1.25rem;
    border: 1px solid #334155;
  }}
  .card-header {{ display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; }}
  .card-header h3 {{ font-size: 0.85rem; font-weight: 600; color: #cbd5e1; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
  .big-number {{ font-size: 2rem; font-weight: 700; }}
  .meta {{ color: #64748b; font-size: 0.75rem; margin-top: 0.25rem; }}
  .chart-container {{
    background: #1e293b; border-radius: 12px; padding: 1.25rem;
    border: 1px solid #334155; margin-bottom: 1.5rem;
  }}
  .chart-container h2 {{ font-size: 1rem; font-weight: 600; margin-bottom: 1rem; color: #cbd5e1; }}
  canvas {{ width: 100% !important; }}
  footer {{ text-align: center; color: #475569; font-size: 0.75rem; padding: 1rem 0; }}
  @media (max-width: 600px) {{
    h1 {{ font-size: 1.25rem; }}
    .big-number {{ font-size: 1.5rem; }}
  }}
</style>
</head>
<body>
  <h1>California River Flows</h1>
  <p class="subtitle">USGS real-time discharge data &middot; Updated {updated}</p>
  <div class="cards">{cards_html}</div>

  <div class="chart-container">
    <h2>7-Day Flow (15-min readings)</h2>
    <canvas id="ivChart"></canvas>
  </div>

  <div class="chart-container">
    <h2>365-Day Daily Mean Flow</h2>
    <canvas id="dvChart"></canvas>
  </div>

  <footer>Data from USGS National Water Information System</footer>

<script>
const chartOpts = (unit) => ({{
  responsive: true,
  interaction: {{ mode: 'index', intersect: false }},
  plugins: {{
    legend: {{ labels: {{ color: '#94a3b8', usePointStyle: true }} }},
    tooltip: {{ callbacks: {{ label: ctx => ctx.parsed.y?.toFixed(1) + ' cfs' }} }}
  }},
  scales: {{
    x: {{
      type: 'time', time: {{ unit }},
      ticks: {{ color: '#64748b', maxTicksLimit: 8 }},
      grid: {{ color: '#1e293b' }}
    }},
    y: {{
      title: {{ display: true, text: 'Discharge (cfs)', color: '#94a3b8' }},
      ticks: {{ color: '#64748b' }},
      grid: {{ color: '#334155' }},
      beginAtZero: true
    }}
  }}
}});

new Chart(document.getElementById('ivChart'), {{
  type: 'line', data: {{ datasets: {iv_json} }}, options: chartOpts('day')
}});

new Chart(document.getElementById('dvChart'), {{
  type: 'line', data: {{ datasets: {dv_json} }}, options: chartOpts('month')
}});
</script>
</body>
</html>"""


def main():
    site_ids = list(STATIONS.keys())
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
