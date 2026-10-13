import json
import os

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "telegram_uploader")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def ensure_credentials():
    cfg = load_config()
    changed = False
    if not cfg.get("api_id"):
        cfg["api_id"] = input("API ID: ").strip()
        changed = True
    if not cfg.get("api_hash"):
        cfg["api_hash"] = input("API HASH: ").strip()
        changed = True
    if changed:
        save_config(cfg)
    return int(cfg["api_id"]), cfg["api_hash"]
