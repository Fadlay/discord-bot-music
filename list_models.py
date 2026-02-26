import os
from dotenv import load_dotenv
load_dotenv()
from google import genai

keys_str = os.getenv("GEMINI_API_KEYS", "") or os.getenv("GEMINI_API_KEY", "")
keys = [k.strip() for k in keys_str.split(",") if k.strip()]
if not keys:
    print("No keys found!")
    exit(1)

client = genai.Client(api_key=keys[0])

print("Available Models:")
for m in client.models.list():
    print(f"- {m.name}")
