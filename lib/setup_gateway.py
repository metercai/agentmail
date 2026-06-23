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
    """Read webhook port from Hermes config.yaml."""
    config_path = os.path.expanduser("~/.hermes/config.yaml")
    try:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        return int(cfg.get("webhook", {}).get("extra", {}).get("port", 8644))
    except:
        return 8644

def ensure_webhook_config():
    """Ensure webhook section exists in config.yaml."""
    config_path = os.path.expanduser("~/.hermes/config.yaml")
    if not os.path.exists(config_path):
        log_warn(f"Config not found: {config_path}")
        return False

    with open(config_path) as f:
        content = f.read()

    if "webhook:" in content and "enabled:" in content[content.index("webhook:"):]:
        return True  # already configured

    # Add webhook config
    import secrets
    secret = secrets.token_hex(32)
    wh_config = f"""
webhook:
    enabled: true
    extra:
        host: 0.0.0.0
        port: 8644
        secret: {secret}
"""
    with open(config_path, 'a') as f:
        f.write(wh_config)
    log_ok("Webhook config added to config.yaml")
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

def main():
    port = read_webhook_port()

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

    # 4. Start gateway (try install first, fall back to run in background)
    log_step("Starting Hermes gateway...")
    started = False
    
    # First try systemd service
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
    
    # Fall back: run gateway as foreground process in background
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

    # 5. Verify
    for _ in range(5):
        if webhook_reachable(port):
            log_ok(f"Hermes webhook restarted (port {port})")
            return 0
        time.sleep(2)

    log_warn(f"Hermes webhook port {port} unreachable")
    log_warn("  Bridge forwarding will fail — restart Hermes manually")
    return 1

if __name__ == "__main__":
    sys.exit(main())
