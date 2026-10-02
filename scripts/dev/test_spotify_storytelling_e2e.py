import os
import pandas as pd
from src.agents.data_agent.agent import (
    profile_dataframe_for_storytelling,
    classify_columns_advanced,
    build_universal_archetype_charts,
    validate_and_correct_chart_specs
)
from src.orchestrator.verifier import verify_dashboard_storytelling, verify_dashboard_spec

spotify_path = "Most Streamed Artists on Spotify (17_07_2026) V1.1.csv"
if not os.path.exists(spotify_path):
    for root, dirs, files in os.walk("."):
        for f in files:
            if "spotify" in f.lower() and f.endswith(".csv"):
                spotify_path = os.path.join(root, f)
                break

print("Spotify file:", spotify_path)
df = pd.read_csv(spotify_path, encoding="utf-8-sig")
print("Columns:", df.columns.tolist())

profile = profile_dataframe_for_storytelling(df)
print("\nProfile:")
for k, v in profile.items():
    print(f"  {k}: {v}")

classification = classify_columns_advanced(df)
print("\nClassification Archetype:", classification.get("recommended_archetype"))
print("Has temporal:", classification.get("has_temporal"))

charts = build_universal_archetype_charts(df, classification)
print(f"\nGenerated {len(charts)} charts:")
for i, c in enumerate(charts):
    print(f"  Chart {i+1}: type={c.get('type')}, dim={c.get('dimension')}, meas={c.get('measure')}, title={c.get('title')}")

spec = {
    "archetype": classification.get("recommended_archetype"),
    "charts": charts,
    "kpiCards": [{"title": "Total Streams", "value": 100}]
}
corrected = validate_and_correct_chart_specs(spec, df)
print("\nCorrected charts:")
for i, c in enumerate(corrected["charts"]):
    print(f"  Chart {i+1}: type={c.get('type')}, dim={c.get('dimension')}, meas={c.get('measure')}, title={c.get('title')}")

is_valid, msg = verify_dashboard_storytelling(corrected, profile)
print(f"\nStorytelling valid: {is_valid}, msg='{msg}'")
is_spec_valid, spec_msg = verify_dashboard_spec(df, corrected)
print(f"Spec valid: {is_spec_valid}, msg='{spec_msg}'")
