"""
Convert .secrets/bilibili.cookie (semicolon-delimited text) to cookie.json (bilitool JSON format).

Usage: python sync_cookie.py
"""
import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
SECRETS_COOKIE = PROJECT_DIR / ".secrets" / "bilibili.cookie"
OUTPUT_COOKIE = PROJECT_DIR / "cookie.json"
CONFIG_JSON = PROJECT_DIR / "src" / "upload" / "bilitool" / "bilitool" / "model" / "config.json"

def parse_text_cookie(path: Path) -> dict[str, str]:
    """Parse 'KEY=VALUE; KEY=VALUE' format cookie file."""
    text = path.read_text(encoding="utf-8").strip()
    cookies = {}
    for item in text.split(";"):
        item = item.strip()
        if "=" in item:
            key, _, value = item.partition("=")
            cookies[key.strip()] = value.strip()
    return cookies

def build_cookie_json(cookies: dict[str, str]) -> dict:
    """Build the bilitool-compatible JSON structure."""
    # Map from text cookie keys to the order expected by get_cookie_file_login()
    key_order = ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"]
    cookie_list = []
    for key in key_order:
        if key in cookies:
            cookie_list.append({"name": key, "value": cookies[key]})
        else:
            print(f"[WARN] Missing cookie key: {key}")
    
    return {
        "data": {
            "access_token": cookies.get("access_token", ""),
            "cookie_info": {
                "cookies": cookie_list
            }
        }
    }

def update_config_json(cookies: dict[str, str]):
    """Directly update the bilitool config.json cookies section."""
    if not CONFIG_JSON.exists():
        print(f"[WARN] config.json not found at {CONFIG_JSON}")
        return
    
    config = json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
    config["cookies"]["SESSDATA"] = cookies.get("SESSDATA", "")
    config["cookies"]["bili_jct"] = cookies.get("bili_jct", "")
    config["cookies"]["DedeUserID"] = cookies.get("DedeUserID", "")
    config["cookies"]["DedeUserID__ckMd5"] = cookies.get("DedeUserID__ckMd5", "")
    config["cookies"]["sid"] = cookies.get("sid", "")
    CONFIG_JSON.write_text(json.dumps(config, indent=4, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Updated {CONFIG_JSON}")

def main():
    if not SECRETS_COOKIE.exists():
        print(f"[ERROR] Cookie file not found: {SECRETS_COOKIE}")
        sys.exit(1)
    
    cookies = parse_text_cookie(SECRETS_COOKIE)
    print(f"[INFO] Parsed {len(cookies)} cookies from {SECRETS_COOKIE}")
    
    # 1. Generate cookie.json for bilitool
    cookie_json = build_cookie_json(cookies)
    OUTPUT_COOKIE.write_text(json.dumps(cookie_json, indent=4, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Generated {OUTPUT_COOKIE}")
    
    # 2. Update bilitool config.json directly
    update_config_json(cookies)
    
    # 3. Explain compatibility scope
    print()
    print("[NOTE] 自动上传直接读取 .secrets/bilibili.cookie。")
    print("  cookie.json 和 bilitool config.json 仅供旧命令兼容。")

if __name__ == "__main__":
    main()
