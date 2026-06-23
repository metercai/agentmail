#!/usr/bin/env python3
"""Setup Hermes gateway + webhook for bridge communication."""
import sys, os, subprocess, time, urllib.request

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

    # Add proper webhook platform config
    import secrets
    secret = secrets.token_hex(32)
    wh_config = f"""
platforms:
    webhook:
        enabled: true
        extra:
            host: 0.0.0.0
            port: 8644
            secret: {secret}

platform_toolsets:
    webhook:
        - amail
        - web
        - file
        - terminal
        - search
        - delegation
"""
    with open(config_path, 'a') as f:
        f.write(wh_config)
    log_ok("Webhook platform config added to config.yaml (platforms.webhook.extra)")
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
            with open(log_path, 'a') as lf:
                subprocess.Popen(
                    ["hermes", "gateway", "run", "--accept-hooks"],
                    stdout=lf, stderr=lf,
                    start_new_session=True
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

def main():
    restart_only = "--restart-only" in sys.argv
    port = read_webhook_port()

    if restart_only:
        log_step("Restarting Hermes gateway for webhook routes...")
        kill_and_restart_gateway(port)
        return 0 if webhook_reachable(port) else 1

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
