#!/usr/bin/env python3
"""Setup Hermes gateway + webhook for bridge communication."""
import sys, os, json, subprocess, time, urllib.request, re

def log_step(msg: str):
    print(f"[step] {msg}")

def log_ok(msg: str):
    print(f"  ✓ {msg}")

def log_warn(msg: str):
    print(f"  ⚠ {msg}")

def read_webhook_port() -> int:
    """Read webhook port from Hermes config.yaml (platforms.webhook.extra.port)."""
    config_path = os.path.expanduser("~/.hermes/config.yaml")
    try:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        wh_cfg = cfg.get("platforms", {}).get("webhook", {}) or cfg.get("webhook", {})
        return int(wh_cfg.get("extra", {}).get("port", 8644))
    except:
        return 8644

def ensure_webhook_config():
    """Ensure webhook platform section exists in config.yaml.
    Hermes uses platforms.webhook.extra (not top-level webhook.extra)."""
    config_path = os.path.expanduser("~/.hermes/config.yaml")
    if not os.path.exists(config_path):
        log_warn(f"Config not found: {config_path}")
        return False

    with open(config_path) as f:
        content = f.read()

    # Check if platform-level webhook is configured
    if "platforms:" in content and "webhook:" in content:
        idx = content.index("platforms:")
        rest = content[idx:]
        if "host:" in rest and "port:" in rest:
            return True  # already configured

    # Also check old-style top-level webhook config
    if content.count("webhook:") >= 2 or ("webhook:" in content and "enabled:" in content):
        idx = content.index("webhook:")
        rest = content[idx:content.index("\n", idx)+200]
        if "port:" in rest:
            # Old format exists but needs migration
            log_step("Migrating webhook config to platforms.webhook.extra...")

    # Add proper webhook platform config + toolsets via YAML parse
    import secrets, yaml as _yaml
    secret = secrets.token_hex(32)
    
    with open(config_path) as f:
        cfg = _yaml.safe_load(f) or {}
    
    changed = False
    
    # Ensure platforms.webhook
    platforms = cfg.setdefault("platforms", {})
    if "webhook" not in platforms:
        platforms["webhook"] = {
            "enabled": True,
            "extra": {"host": "0.0.0.0", "port": 8644, "secret": secret},
        }
        changed = True
        log_ok("Webhook platform config added to config.yaml")
    
    # Ensure platform_toolsets.webhook
    pts = cfg.setdefault("platform_toolsets", {})
    if "webhook" not in pts:
        pts["webhook"] = ["amail", "web", "file", "terminal", "search", "delegation"]
        changed = True
        log_ok("platform_toolsets.webhook added (amail + delegation + ...)")
    
    if changed:
        with open(config_path, 'w') as f:
            _yaml.safe_dump(cfg, f, default_flow_style=False, allow_unicode=True)
    
    return True

def gateway_installed() -> bool:
    """Check if Hermes gateway service is installed."""
    # Check systemd user service
    home = os.path.expanduser("~")
    service_paths = [
        os.path.join(home, ".config/systemd/user/hermes-gateway.service"),
        "/etc/systemd/system/hermes-gateway.service",
    ]
    for p in service_paths:
        if os.path.exists(p):
            return True
    # Check via hermes CLI
    try:
        r = subprocess.run(["hermes", "gateway", "status"],
            capture_output=True, text=True, timeout=5)
        return "running" in r.stdout.lower() or "active" in r.stdout.lower()
    except:
        return False

def webhook_reachable(port: int) -> bool:
    """Check if webhook is listening on the given port."""
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3)
        return r.status == 200
    except:
        return False


def kill_and_restart_gateway(port: int) -> bool:
    """Kill and restart Hermes gateway. Returns True if webhook reachable after."""
    started = False

    # Try systemd service
    if gateway_installed():
        try:
            subprocess.run(["hermes", "gateway", "stop"],
                capture_output=True, timeout=10)
            time.sleep(1)
            subprocess.run(["hermes", "gateway", "start"],
                capture_output=True, timeout=10)
            time.sleep(3)
            started = webhook_reachable(port)
        except:
            pass

    # Fall back: run gateway in background
    if not started:
        try:
            log_path = os.path.expanduser("~/.hermes/gateway.log")
            env = os.environ.copy()
            ag_home = os.path.expanduser("~/.agentmail")
            # Determine agent subdirectory from amail.json
            amail_path = os.path.expanduser("~/.hermes/amail.json")
            if os.path.exists(amail_path):
                with open(amail_path) as f:
                    acfg = json.load(f)
                email = acfg.get("email", "")
                if email:
                    ag_home = os.path.join(ag_home, email.replace("@", "_"))
            env["AGENTMAIL_HOME"] = ag_home
            log_path = os.path.expanduser("~/.hermes/gateway.log")
            with open(log_path, 'a') as lf:
                subprocess.Popen(
                    ["hermes", "gateway", "run", "--accept-hooks"],
                    stdout=lf, stderr=lf,
                    start_new_session=True,
                    env=env
                )
            time.sleep(5)
            started = webhook_reachable(port)
        except Exception as e:
            log_warn(f"Gateway run failed: {e}")

    # Verify
    for _ in range(5):
        if webhook_reachable(port):
            return True
        time.sleep(2)
    return False

def _sync_bridge_routes(port: int):
    """Sync all profile email routes to the bridge after gateway restart.
    Reads amail.jsons from all profiles and calls bridge API to register routes
    with the current Hermes webhook host:port. This ensures stale routes (e.g.
    from a previous webhook port) are overwritten with the correct target.
    Skips if no bridge is deployed (webhook_host is empty).
    """
    import json, os, urllib.request, urllib.error
    from pathlib import Path

    home = os.path.expanduser("~/.hermes")
    gw_cfg_path = os.path.join(home, "amail_gateway.json")
    if not os.path.exists(gw_cfg_path):
        return

    with open(gw_cfg_path) as f:
        gw_cfg = json.load(f)

    bridge_addr = gw_cfg.get("webhook_host", "")
    if not bridge_addr:
        log_step("No bridge deployed — skipping route sync")
        return

    # Build bridge base URL
    if re.match(r'^(\d+\.\d+\.\d+\.\d+|\[.*\]):', bridge_addr):
        bridge_base = f"http://{bridge_addr}"
    else:
        bridge_base = f"https://{bridge_addr}"

    # Collect all profile emails
    profiles = {}  # email → (host, port)

    # Root profile
    root_amail = os.path.join(home, "amail.json")
    if os.path.exists(root_amail):
        try:
            with open(root_amail) as f:
                pf = json.load(f)
            email = pf.get("email", "")
            if email:
                profiles[email] = ("127.0.0.1", port)
        except Exception:
            pass

    # Named profiles
    profiles_dir = os.path.join(home, "profiles")
    if os.path.isdir(profiles_dir):
        for name in sorted(os.listdir(profiles_dir)):
            amail_json = os.path.join(profiles_dir, name, "amail.json")
            if not os.path.exists(amail_json):
                continue
            try:
                with open(amail_json) as f:
                    pf = json.load(f)
                email = pf.get("email", "")
                if email:
                    profiles[email] = ("127.0.0.1", port)
            except Exception:
                continue

    if not profiles:
        log_step("No profile emails found — skipping bridge route sync")
        return

    # Register each route on the bridge
    registered = 0
    errors = 0
    for email, (host, p) in profiles.items():
        data = json.dumps({"email": email, "host": host, "port": p}).encode()
        req = urllib.request.Request(
            f"{bridge_base}/api/v1/routes",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                registered += 1
        except Exception as e:
            log_warn(f"Bridge route registration failed for {email}: {e}")
            errors += 1

    if errors == 0:
        log_ok(f"Bridge routes synced: {registered} email(s) → {bridge_base}")
    else:
        log_ok(f"Bridge routes synced: {registered} ok, {errors} failed → {bridge_base}")


def main():
    restart_only = "--restart-only" in sys.argv
    port = read_webhook_port()

    if restart_only:
        log_step("Restarting Hermes gateway for webhook routes...")
        ok = kill_and_restart_gateway(port)
        if webhook_reachable(port):
            log_ok(f"Hermes webhook restarted (port {port})")
            _sync_bridge_routes(port)
            return 0
        else:
            log_warn(f"Hermes webhook port {port} unreachable after restart")
            return 1

    # 1. Ensure webhook config
    ensure_webhook_config()

    # 2. Install gateway service if needed
    if not gateway_installed():
        log_step("Installing Hermes gateway service...")
        try:
            subprocess.run(["hermes", "gateway", "install"],
                input=b"Y\nY\n", check=True, timeout=60, capture_output=True)
            log_ok("Gateway service installed")
        except Exception as e:
            log_warn(f"Gateway install failed: {e}")
            return 1

    # 3. Check if webhook is already reachable
    if webhook_reachable(port):
        log_ok(f"Hermes webhook reachable (port {port})")
        return 0

    # 4. Start gateway
    log_step("Starting Hermes gateway...")
    if kill_and_restart_gateway(port):
        log_ok(f"Hermes webhook restarted (port {port})")
        return 0

    log_warn(f"Hermes webhook port {port} unreachable")
    log_warn("  Bridge forwarding will fail — restart Hermes manually")
    return 1

if __name__ == "__main__":
    sys.exit(main())
