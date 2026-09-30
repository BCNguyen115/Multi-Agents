import requests
import time

csv_path = r"dataset/test_data/Most Streamed Artists on Spotify (17_07_2026) V1.1.csv"
url = "http://localhost:8000/api/analyze"

print(f"Sending POST /api/analyze with file: {csv_path}")
t0 = time.time()
with open(csv_path, "rb") as f:
    files = {"file": ("spotify_artists.csv", f, "text/csv")}
    data = {"query": "Phân tích top nghệ sĩ có lượt stream cao nhất"}
    response = requests.post(url, files=files, data=data, timeout=60)

duration = time.time() - t0
print(f"Status Code: {response.status_code} ({duration:.2f}s)")
if response.status_code == 200:
    res_data = response.json()
    print("Success! Keys in response:", list(res_data.keys()))
    spec = res_data.get("dashboard_spec", {})
    print("Dashboard title:", spec.get("dashboard_title"))
    print("KPIs count:", len(spec.get("kpis", [])))
    print("Charts count:", len(spec.get("charts", [])))
else:
    print("Error:", response.text[:300])
