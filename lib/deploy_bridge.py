#!/usr/bin/env python3
"""Deploy amail-bridge: domain key, bridge config, startup.
Replaces deploy-bridge.sh — cleaner, testable Python."""
import sys, os, json, subprocess, socket, time
import urllib.request, urllib.error, re

def log_step(msg: str):
    print(f"[step] {msg}")

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
                        ak: str, sid: str, api_key: str = ""):
    """Write amail_bridge.toml."""
    log_path = os.path.expanduser("~/.hermes/amail-bridge.log")
    lines = [
        f'addr = "{addr}"',
        f'mode = "{mode}"',
        '',
        '[logging]',
        f'file = "{log_path}"',
        'level = "info"',
        '',
        '[pull]',
        f'gateway_url = "{gw}"',
        f'admin_key = "{ak}"',
        f'system_id = "{sid}"',
        'poll_interval_sec = 10',
    ]
    if api_key:
        lines.insert(lines.index('[pull]') + 1, f'api_key = "{api_key}"')
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')

def start_bridge(bin_path: str, cfg_path: str, pid_path: str) -> bool:
    """Start bridge process. Returns True if running."""
    # Kill old
    if os.path.exists(pid_path):
        try:
            old_pid = int(open(pid_path).read().strip())
            os.kill(old_pid, 15)
        except: pass
        os.remove(pid_path)

    log_path = os.path.expanduser("~/.hermes/bridge.log")
    with open(log_path, 'a') as lf:
        proc = subprocess.Popen([bin_path, '-c', cfg_path],
            stdout=lf, stderr=lf, start_new_session=True)

    time.sleep(1.5)
    if proc.poll() is None:
        with open(pid_path, 'w') as f:
            f.write(str(proc.pid))
        return True
    return False

def main():
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
        home = os.path.expanduser("~/.hermes")
        cfg_path = os.path.join(home, "amail_gateway.json")
        with open(cfg_path) as f:
            cfg = json.load(f)
        if cfg.get("admin_key") != domain_key:
            cfg["admin_key"] = domain_key
            with open(cfg_path, 'w') as f:
                json.dump(cfg, f, indent=2)
            ak = domain_key

    # ── Bridge deployment ────────────────────────────────────
    home = os.path.expanduser("~/.hermes")
    bridge_dir = os.path.join(home, "bin")
    bridge_bin = os.environ.get("AMAIL_BRIDGE_BIN",
        os.path.join(bridge_dir, "amail-bridge"))
    os.makedirs(bridge_dir, exist_ok=True)

    # Download if missing
    if not os.access(bridge_bin, os.X_OK):
        ver = os.environ.get("AMAIL_BRIDGE_VERSION", "v0.5.0")
        url = f"https://github.com/metercai/amail-bridge/releases/download/{ver}/amail-bridge-{ver}-x86_64-unknown-linux-gnu.tar.gz"
        log_step(f"Downloading bridge {ver}...")
        try:
            subprocess.run(["curl", "-sL", url], stdout=subprocess.PIPE, timeout=60,
                check=True)  # just check it's reachable
            subprocess.run(
                f"curl -sL '{url}' | tar xz -C '{bridge_dir}' amail-bridge",
                shell=True, timeout=60)
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
    bridge_cfg = os.path.join(home, "amail_bridge.toml")

    # Create bridge API key
    import uuid
    bridge_domain = f"bridge-{uuid.uuid4().hex[:8]}"
    bridge_key = create_api_key(gw, ak, sid, bridge_domain, ["bridge"], "bridge")

    write_bridge_config(bridge_cfg, bridge_mode, wh_host or "127.0.0.1:38081",
                        gw, ak, sid, api_key=bridge_key)

    # Update gateway config
    gw_cfg_path = os.path.join(home, "amail_gateway.json")
    with open(gw_cfg_path) as f:
        gw_cfg = json.load(f)
    gw_cfg["webhook_host"] = wh_host
    with open(gw_cfg_path, 'w') as f:
        json.dump(gw_cfg, f, indent=2)

    # Start bridge
    pid_path = os.path.join(home, "bridge.pid")
    if start_bridge(bridge_bin, bridge_cfg, pid_path):
        log_ok(f"bridge started (mode={bridge_mode}, {wh_host})")
        if bridge_key:
            log_ok(f"bridge API key created (category=bridge)")
    else:
        log_warn(f"bridge failed to start — check {home}/bridge.log")

    return 0

if __name__ == "__main__":
    sys.exit(main())
