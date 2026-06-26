#!/usr/bin/env python3
"""Deploy amail-bridge: domain key, bridge config, startup."""
import sys, os, json, subprocess, socket, time
import urllib.request, urllib.error, re

def log_step(msg: str):
    print(f"  {msg}")

def log_ok(msg: str):
    print(f"  ✓ {msg}")

def log_warn(msg: str):
    print(f"  ⚠ {msg}")

def whoami(gw: str, ak: str) -> dict:
    req = urllib.request.Request(f"{gw}/api/v1/whoami", headers={"X-Api-Key": ak})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except:
        return {}

def create_api_key(gw: str, ak: str, system_id: str, email: str,
                   scopes: list, category: str) -> str:
    """Create API key. Returns raw_key or empty string."""
    data = json.dumps({
        "system_id": system_id, "email_address": email,
        "scopes": scopes, "category": category,
    }).encode()
    req = urllib.request.Request(f"{gw}/api/v1/api-keys", data=data,
        headers={"X-Api-Key": ak, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("raw_key", "")
    except:
        return ""

def detect_ip() -> str:
    """Detect best public IP. Returns IPv4 or IPv6 or 127.0.0.1."""
    try:
        out = subprocess.check_output(
            ["ip", "-4", "addr", "show", "scope", "global"], text=True, timeout=5)
        m = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', out)
        if m and m.group(1) != "127.0.0.1":
            return m.group(1)
    except: pass
    try:
        out = subprocess.check_output(
            ["ip", "-6", "addr", "show", "scope", "global"], text=True, timeout=5)
        m = re.search(r'inet6 ([\da-f:]+)', out)
        if m and "::1" not in m.group(1) and not m.group(1).startswith("fe80"):
            return m.group(1)
    except: pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except:
        return "127.0.0.1"

def format_webhook_host(ip: str) -> str:
    """Format IP as webhook_host with port."""
    if ":" in ip and "." not in ip:  # IPv6
        return f"[{ip}]:38081"
    else:
        return f"{ip}:38081"

def write_bridge_config(path: str, mode: str, addr: str, gw: str,
                        ak: str, sid: str, api_key: str = "",
                        webhook_secret: str = ""):
    """Write amail_bridge.toml."""
    log_path = os.path.expanduser("~/.agentmail/amail-bridge.log")
    lines = [
        f'addr = "{addr}"',
        f'mode = "{mode}"',
        '',
        '[logging]',
        f'file = "{log_path}"',
        'level = "info"',
        '',
        '[pull]',
        f'amail_url = "{gw}"',
        f'admin_key = "{ak}"',
        f'system_id = "{sid}"',
        'poll_interval_sec = 2',
    ]
    if webhook_secret:
        lines.insert(-1, f'webhook_secret = "{webhook_secret}"')
    lines.extend([
        '',
        '[health]',
        'check_interval_sec = 30',
        'fail_threshold = 6',
        'connect_timeout_sec = 3',
    ])
    if api_key:
        lines.insert(lines.index('[pull]') + 1, f'api_key = "{api_key}"')
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')

def start_bridge(bin_path: str, cfg_path: str, pid_path: str) -> bool:
    """Start bridge process. Returns True if running."""
    # Kill all old bridge processes (pkill by process name)
    subprocess.run(['pkill', '-f', 'amail-bridge.*amail_bridge.toml'],
        capture_output=True, timeout=5)
    time.sleep(1)
    
    # Kill by PID file as fallback
    if os.path.exists(pid_path):
        try:
            old_pid = int(open(pid_path).read().strip())
            os.kill(old_pid, 15)
        except: pass
        os.remove(pid_path)

    with open(os.devnull, 'w') as lf:
        proc = subprocess.Popen(
            [bin_path, '-c', cfg_path],
            stdout=lf, stderr=lf,
            start_new_session=True  # daemonize
        )

    time.sleep(1.5)
    if proc.poll() is None:
        with open(pid_path, 'w') as f:
            f.write(str(proc.pid))
        return True
    return False

def main():
    # Standalone restart: just kill and restart bridge process
    if "--restart" in sys.argv:
        bin_path = os.path.expanduser("~/.agentmail/bin/amail-bridge")
        cfg_path = os.path.expanduser("~/.agentmail/amail_bridge.toml")
        pid_path = os.path.expanduser("~/.agentmail/bridge.pid")
        start_bridge(bin_path, cfg_path, pid_path)
        return 0 if os.path.exists(pid_path) else 1

    # Read env vars from integrate.sh
    gw = os.environ.get("GATEWAY_URL", "")
    ak = os.environ.get("ADMIN_KEY", "")
    sid = os.environ.get("SYSTEM_ID", "")
    domain = os.environ.get("AMAIL_DOMAIN", "")
    wh_mode = os.environ.get("WEBHOOK_MODE", "bridge")
    wh_host = os.environ.get("WEBHOOK_HOST", "")
    use_pc = os.environ.get("USE_PRODUCT_CODE", "false") == "true"

    if not all([gw, ak, sid, domain]):
        log_warn("Required vars missing: GATEWAY_URL, ADMIN_KEY, SYSTEM_ID, AMAIL_DOMAIN")
        return 1

    # ── Domain admin key ─────────────────────────────────────
    info = whoami(gw, ak)
    admin_email = info.get("email", "")
    admin_scope = info.get("scope", "")
    admin_cat = info.get("category", "")

    domain_key = ""
    if admin_cat == "domain" and admin_email == domain:
        domain_key = ak
        log_ok(f"domain admin key already in use ({domain})")
    elif not admin_email or admin_email == domain or "platform" in (admin_scope or ""):
        raw = create_api_key(gw, ak, sid, domain, ["system"], "domain")
        if raw:
            domain_key = raw
            log_ok("domain admin key created")
        else:
            log_warn("domain key creation failed — using system admin key")
    else:
        log_warn("domain key creation failed — continuing with system admin key")

    # Save domain key
    if domain_key:
        # Find amail_gateway.json directly by system_id
        cfg_path = os.path.join(os.path.expanduser("~/.agentmail"), sid, "amail_gateway.json")
        if not os.path.isfile(cfg_path):
            log_warn("amail_gateway.json not found — cannot update admin_key")
        else:
            with open(cfg_path) as f:
                cfg = json.load(f)
            if cfg.get("admin_key") != domain_key:
                cfg["admin_key"] = domain_key
                with open(cfg_path, 'w') as f:
                    json.dump(cfg, f, indent=2)
                ak = domain_key

    # ── Bridge deployment ────────────────────────────────────
    bridge_dir = os.path.expanduser("~/.agentmail/bin")
    bridge_bin = os.environ.get("AMAIL_BRIDGE_BIN",
        os.path.join(bridge_dir, "amail-bridge"))
    os.makedirs(bridge_dir, exist_ok=True)

    # Download if missing
    if not os.access(bridge_bin, os.X_OK):
        ver = os.environ.get("AMAIL_BRIDGE_VERSION", "v0.5.0")
        url = f"https://github.com/metercai/amail-bridge/releases/download/{ver}/amail-bridge-{ver}-x86_64-unknown-linux-gnu.tar.gz"
        log_step(f"Downloading bridge {ver}...")
        try:
            # Download and extract
            dl = subprocess.run(
                ["curl", "-sL", url],
                capture_output=True, timeout=60)
            if dl.returncode == 0:
                subprocess.run(
                    ["tar", "xz", "-C", bridge_dir, "amail-bridge"],
                    input=dl.stdout, timeout=30, capture_output=True)
        except: pass

    if not os.access(bridge_bin, os.X_OK):
        log_warn("bridge binary not found")
        return 0

    # Determine webhook host
    if wh_mode == "bridge" and not wh_host:
        ip = detect_ip()
        wh_host = format_webhook_host(ip)
        log_step(f"Auto-detected bridge address: {wh_host}")
    elif wh_host:
        log_step(f"Using configured bridge address: {wh_host}")

    if not wh_host and wh_mode != "internal":
        return 0

    # Write bridge config
    bridge_mode = "pull" if wh_mode == "bridge" else "push"
    cfg_dir = os.path.expanduser("~/.agentmail")
    os.makedirs(cfg_dir, exist_ok=True)
    bridge_cfg = os.path.join(cfg_dir, "amail_bridge.toml")

    # Create bridge API key (use system-level key for higher privilege)
    import uuid
    system_key = ""
    system_key_path = os.path.join(
        os.path.expanduser("~/.agentmail/.system_raw_key"), f"{sid}_admin.key"
    )
    if os.path.exists(system_key_path):
        try:
            with open(system_key_path) as f:
                system_key = f.read().strip()
        except Exception:
            pass
    bridge_ak = system_key or ak  # prefer system key, fallback to domain key
    bridge_domain = f"bridge-{uuid.uuid4().hex[:8]}"
    bridge_key = create_api_key(gw, bridge_ak, sid, bridge_domain, ["bridge"], "bridge")
    if not bridge_key:
        log_warn("bridge API key creation failed — bridge auth may not work")

    # Read webhook secret from Hermes config
    webhook_secret = ""
    try:
        import yaml
        hermes_cfg_path = os.path.expanduser("~/.hermes/config.yaml")
        with open(hermes_cfg_path) as f:
            hc = yaml.safe_load(f)
        webhook_secret = hc.get("platforms", {}).get("webhook", {}).get("extra", {}).get("secret", "")
    except:
        pass

    write_bridge_config(bridge_cfg, bridge_mode, wh_host or "127.0.0.1:38081",
                        gw, ak, sid, api_key=bridge_key,
                        webhook_secret=webhook_secret)

    # Read gateway config to update webhook_host
    gw_cfg = None
    gw_cfg_path = None
    if sid:
        sub = os.path.join(os.path.expanduser("~/.agentmail"), sid, "amail_gateway.json")
        if os.path.isfile(sub):
            try:
                with open(sub) as f:
                    gw_cfg = json.load(f)
                gw_cfg_path = sub
            except Exception:
                pass
    if gw_cfg_path and gw_cfg is not None:
        gw_cfg["webhook_host"] = wh_host
        with open(gw_cfg_path, 'w') as f:
            json.dump(gw_cfg, f, indent=2)

    # Start bridge
    pid_path = os.path.join(cfg_dir, "bridge.pid")
    if start_bridge(bridge_bin, bridge_cfg, pid_path):
        log_ok(f"bridge started (mode={bridge_mode}, {wh_host})")
        if bridge_key:
            log_ok(f"bridge API key created (category=bridge)")
    else:
        log_warn(f"bridge failed to start — check {cfg_dir}/bridge.log")

    return 0

if __name__ == "__main__":
    sys.exit(main())
