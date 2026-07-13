#!/usr/bin/env python3
"""Register existing Hermes profiles as amail addresses in the current system."""
import sys, os, json, urllib.request, urllib.error

def load_gateway_config():
    # Use SYSTEM_ID env var to locate config directly
    sid = os.environ.get("SYSTEM_ID", "")
    if sid:
        sub = os.path.join(os.path.expanduser("~/.agentmail"), sid, "agentmail_gateway.json")
        if os.path.isfile(sub):
            try:
                with open(sub) as f:
                    return json.load(f)
            except Exception:
                pass
    return None

def register_emails():
    config = load_gateway_config()
    if not config or not config.get("admin_key"):
        print("no_config")
        return

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "tools"))
    from agentmail_base import _agentmail_system_dir, _auto_register_email

    gw = config.get("gateway_url", "")
    system_id = config.get("system_id", "")
    home = os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))
    profiles_dir = os.path.expanduser(os.environ.get("HERMES_PROFILES_DIR", os.path.join(home, "profiles")))

    count = 0

    # Default profile (root ~/.hermes/)
    # Use centralized ~/.agentmail/{system_id}/agentmail.json as registration marker
    default_central = str(_agentmail_system_dir(system_id) / "agentmail.json") if system_id else ""
    if default_central and os.path.exists(default_central):
        try:
            with open(default_central) as f:
                pf = json.load(f)
            if pf.get("system_id") == system_id:
                pass  # already registered, skip
        except:
            pass
    else:
        # Register default profile
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
            # Use centralized path as registration marker
            named_central = str(_agentmail_system_dir(system_id) / "profiles" / name / "agentmail.json") if system_id else ""
            if named_central and os.path.exists(named_central):
                try:
                    with open(named_central) as f:
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
