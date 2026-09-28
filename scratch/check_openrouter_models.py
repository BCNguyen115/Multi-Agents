import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

print(f"API Key present: {bool(api_key)}")
if api_key:
    print(f"API Key preview: {api_key[:12]}...{api_key[-4:]}")

headers = {
    "Authorization": f"Bearer {api_key}",
    "HTTP-Referer": "http://localhost:3000",
    "X-Title": "Multi-Agent MVP"
}

# 1. Check account limits / credits
try:
    auth_resp = requests.get(f"{base_url}/auth/key", headers=headers, timeout=10)
    print(f"\n--- Auth / Limits Check ---")
    print(f"Status Code: {auth_resp.status_code}")
    print(f"Response: {auth_resp.text}")
except Exception as e:
    print(f"Auth check failed: {e}")

# 2. Check available models
try:
    resp = requests.get(f"{base_url}/models", headers=headers, timeout=15)
    print(f"\n--- Models List ---")
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json().get("data", [])
        print(f"Total models available: {len(data)}")
        
        claude_models = [m["id"] for m in data if "claude" in m["id"].lower()]
        gpt_models = [m["id"] for m in data if "gpt-4" in m["id"].lower()]
        
        print("\nAvailable Claude models:")
        for m in sorted(claude_models):
            print(f"  - {m}")
            
        print("\nAvailable GPT-4 models:")
        for m in sorted(gpt_models):
            print(f"  - {m}")
    else:
        print(f"Failed to fetch models: {resp.text}")
except Exception as e:
    print(f"Models check failed: {e}")

# 3. Test completions on candidate models
candidate_models = [
    "anthropic/claude-3.5-sonnet",
    "anthropic/claude-3.5-sonnet:beta",
    "anthropic/claude-3-5-sonnet-20241022",
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
]

print("\n--- Test Direct Completions ---")
for model in candidate_models:
    try:
        r = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 5
            },
            timeout=10
        )
        print(f"Model [{model}]: Status {r.status_code}")
        if r.status_code != 200:
            print(f"   Error: {r.text[:200]}")
        else:
            print(f"   Success: {r.json()['choices'][0]['message']['content'].strip()}")
    except Exception as e:
        print(f"Model [{model}]: Exception: {e}")
