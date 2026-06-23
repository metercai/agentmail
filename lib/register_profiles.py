#!/usr/bin/env python3
"""Register existing Hermes profiles as amail addresses in the current system."""
import sys, os, json, urllib.request, urllib.error

def load_gateway_config():
    path = os.path.expanduser("~/.hermes/amail_gateway.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)

def register_emails():
    config = load_gateway_config()
    if not config or not config.get("admin_key"):
        print("no_config")
        return

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tools"))
    from amail_tools import _auto_register_email

    gw = config.get("gateway_url", "")
    system_id = config.get("system_id", "")
    home = os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))
    profiles_dir = os.path.expanduser(os.environ.get("HERMES_PROFILES_DIR", os.path.join(home, "profiles")))

    count = 0

    # Default profile (root ~/.hermes/)
    default_candidates = [
        os.path.join(home, "amail.json"),
        os.path.join(home, "hermes-agent", "amail.json"),
    ]
    for amail_json in default_candidates:
        if os.path.exists(amail_json):
            try:
                with open(amail_json) as f:
                    pf = json.load(f)
                if pf.get("system_id") == system_id:
                    break  # already registered, skip
            except:
                break
    else:
        # No default amail.json or system_id changed — register
        try:
            _auto_register_email("default", home, config)
            count += 1
        except Exception as e:
            print(f"failed:default:{e}")

    # Named profiles
    if os.path.isdir(profiles_dir):
        for name in sorted(os.listdir(profiles_dir)):
            profile_dir = os.path.join(profiles_dir, name)
            if not os.path.isdir(profile_dir):
                continue
            amail_json = os.path.join(profile_dir, "amail.json")
            if os.path.exists(amail_json):
                try:
                    with open(amail_json) as f:
                        pf = json.load(f)
                    if pf.get("system_id") == system_id:
                        continue  # same system, skip
                    print(f"  Re-registering {name} (system changed)", file=sys.stderr)
                except:
                    continue
            try:
                _auto_register_email(name, profile_dir, config)
                count += 1
            except Exception as e:
                print(f"failed:{name}:{e}")

    print(f"registered:{count}")

if __name__ == "__main__":
    register_emails()
