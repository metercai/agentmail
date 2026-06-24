#!/usr/bin/env python3
"""
check_status.py — One-shot amail pipeline runtime status check

Covers the full chain: amail-gateway → amail-bridge → agent-gateway → agent-profile
Each layer ≤3 key checkpoints with path verification. Output: formatted table or JSON.

Usage:
    python3 lib/check_status.py              # table output
    python3 lib/check_status.py --json       # JSON output
    python3 lib/check_status.py --verbose    # with fix suggestions
"""
import sys, os, json, subprocess, time, re, socket
from pathlib import Path
from datetime import datetime, timezone
import urllib.request, urllib.error

# ── ANSI helpers ───────────────────────────────────────────────
GREEN  = '\033[0;32m'
RED    = '\033[0;31m'
YELLOW = '\033[1;33m'
BOLD   = '\033[1m'
NC     = '\033[0m'
CHECK  = '\u2713'
CROSS  = '\u2717'

# ── Path constants ─────────────────────────────────────────────
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
AGENTMAIL_HOME = Path.home() / ".agentmail"
GW_CONFIG   = HERMES_HOME / "amail_gateway.json"
BRIDGE_CFG  = AGENTMAIL_HOME / "amail_bridge.toml"
BRIDGE_PID  = AGENTMAIL_HOME / "bridge.pid"
BRIDGE_LOG  = AGENTMAIL_HOME / "amail-bridge.log"
HERMES_CFG  = HERMES_HOME / "config.yaml"
SUBS_FILE   = HERMES_HOME / "webhook_subscriptions.json"
PROFILES_DIR = HERMES_HOME / "profiles"
ROUTES_FILE = AGENTMAIL_HOME / "amail_routes.toml"

# Agent-scoped paths (require --agent argument for per-agent data)
_AGENT_DIR: Path | None = None

def _agentmail_log() -> Path:
    global _AGENT_DIR
    if _AGENT_DIR:
        return _AGENT_DIR / "agentmail.log"
    return Path.home() / ".agentmail" / "default" / "agentmail.log"

def _agentmail_raw() -> Path:
    global _AGENT_DIR
    if _AGENT_DIR:
        return _AGENT_DIR
    return Path.home() / ".agentmail" / "default"

# ── TOML-like parser (bare keys + sections) ────────────────────
def _parse_toml(text: str) -> dict[str, dict[str, str]]:
    """Parse a minimal TOML subset: bare top-level keys + [section] blocks."""
    data: dict[str, dict[str, str]] = {"__top__": {}}
    cur = "__top__"
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r'^\[(\w+)\]$', s)
        if m:
            cur = m.group(1)
            data.setdefault(cur, {})
            continue
        if "=" in s:
            k, v = s.split("=", 1)
            data.setdefault(cur, {})[k.strip()] = v.strip().strip('"').strip("'")
    return data


# ── Check record ───────────────────────────────────────────────
class Check:
    def __init__(self):
        self.checks: list[dict] = []
        self.verbose = False

    def add(self, level: str, name: str, ok: bool, detail: str, fix: str = ""):
        self.checks.append({
            "level": level, "check": name,
            "pass": ok, "detail": detail, "fix": fix,
        })

    def all_pass(self) -> bool:
        return all(c["pass"] for c in self.checks)

    def print_table(self):
        groups = [
            ("amail-gateway (external mail gateway)", [c for c in self.checks if c["level"] == "gateway"]),
            ("amail-bridge (local NAT traversal bridge)",  [c for c in self.checks if c["level"] == "bridge"]),
            ("agent-gateway (Hermes gateway)",  [c for c in self.checks if c["level"] == "agent-gw"]),
            ("agent-profile (agent entity)",   [c for c in self.checks if c["level"] == "profile"]),
        ]
        for title, items in groups:
            if not items:
                continue
            icon = GREEN if all(i["pass"] for i in items) else (YELLOW if any(i["pass"] for i in items) else RED)
            print(f"\n  {BOLD}{icon}╓─ {title}{NC}")
            for chk in items:
                ik = GREEN + CHECK + NC if chk["pass"] else RED + CROSS + NC
                print(f"  {ik} {chk['check']}: {chk['detail']}")
                if self.verbose and not chk["pass"] and chk.get("fix"):
                    print(f"     {YELLOW}→{NC} {chk['fix']}")

    def print_json(self):
        print(json.dumps({
            "all_pass": self.all_pass(),
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "checks": self.checks,
        }, indent=2, ensure_ascii=False))


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════
def _json_req(url: str, headers: dict | None = None,
              data: bytes | None = None, method: str | None = None,
              timeout: int = 10) -> tuple[int, dict | list]:
    """HTTP request returning (status_code, parsed_json)."""
    req = urllib.request.Request(url, data=data, headers=headers or {},
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def _read_gw_cfg() -> dict | None:
    """Load amail_gateway.json, return None on failure."""
    if not GW_CONFIG.exists():
        return None
    try:
        return json.loads(GW_CONFIG.read_text())
    except Exception:
        return None


def _get_webhook_port() -> int:
    """Read webhook port from config.yaml."""
    if HERMES_CFG.exists():
        try:
            import yaml
            with open(HERMES_CFG) as f:
                hc = yaml.safe_load(f) or {}
            return int(hc.get("platforms", {}).get("webhook", {})
                      .get("extra", {}).get("port", 8644))
        except Exception:
            pass
    return 8644


# ═══════════════════════════════════════════════════════════════
#  Level 1: amail-gateway (external mail gateway)
# ═══════════════════════════════════════════════════════════════
def check_gateway(c: Check):
    """amail-gateway: health + SMTP port + API credentials"""
    cfg = _read_gw_cfg()
    if not cfg:
        c.add("gateway", "config", False,
              "amail_gateway.json not found",
              "Run integrate.sh to configure amail-gateway")
        return

    gw_url = cfg.get("gateway_url", "").rstrip("/")
    ak = cfg.get("admin_key", "")
    if not gw_url:
        c.add("gateway", "config", False,
              "gateway_url is empty in config", "Re-run integrate.sh")
        return

    # 1.1 Health
    code, body = _json_req(f"{gw_url}/health")
    if code == 200:
        uptime = body.get("uptime_secs", "?") if isinstance(body, dict) else "?"
        c.add("gateway", "health", True, f"HTTP {code}, uptime {uptime}s")
    else:
        err = body.get("error", body) if isinstance(body, dict) else str(body)
        c.add("gateway", "health", False, f"HTTP {code}: {err}",
              "Start amail-gateway service on the gateway server")
        return

    # 1.2 SMTP port 25
    host = gw_url.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((host, 25))
        banner = s.recv(256).decode(errors="replace").strip()
        s.close()
        c.add("gateway", "smtp_port", True, f"Port 25 open, banner: {banner[:60]}")
    except Exception as e:
        c.add("gateway", "smtp_port", False,
              f"Port 25 unreachable: {e}",
              "Check firewall and amail-gateway SMTP listener")

    # 1.3 API key scope
    if not ak:
        c.add("gateway", "api_key", False,
              "No admin_key configured",
              "Run integrate.sh Step 2 to set admin_key")
        return
    code, data = _json_req(f"{gw_url}/api/v1/whoami",
                           headers={"X-Api-Key": ak})
    if code == 200:
        scope = data.get("scope", "")
        cat = data.get("category", "")
        sid = data.get("system_id", "")
        ok = "platform" in scope or "system" in scope
        c.add("gateway", "api_key", ok,
              f"scope={scope}, category={cat}, system_id={sid[:16]}..." if ok else
              f"scope={scope} — need platform/system",
              "Use a key with platform or system scope")
    else:
        c.add("gateway", "api_key", False,
              f"whoami HTTP {code}", "Check admin_key is correct")


# ═══════════════════════════════════════════════════════════════
#  Level 2: amail-bridge (local NAT traversal bridge)
#  Optional component. If config not found, bridge is simply
#  not deployed (gateway → agent-gateway directly).
#  May run on a different machine in the LAN.
# ═══════════════════════════════════════════════════════════════
def check_bridge(c: Check):
    """amail-bridge: config + process + log + pull path (P0)"""

    # 2.1 Config — this is the single source of truth for bridge existence
    if not BRIDGE_CFG.exists():
        # Bridge not deployed — this is valid for direct-connect setups
        c.add("bridge", "config", True, "not deployed (gateway → agent-gateway direct)")
        return

    try:
        td = _parse_toml(BRIDGE_CFG.read_text())
        mode   = td.get("__top__", {}).get("mode", "") or td.get("bridge", {}).get("mode", "")
        addr   = td.get("__top__", {}).get("addr", "") or td.get("bridge", {}).get("addr", "")
        amail_url = td.get("pull", {}).get("amail_url", "")
        poll_int  = td.get("pull", {}).get("poll_interval_sec", "")
        parts = [f"mode={mode}"]
        if addr:    parts.append(f"addr={addr}")
        if amail_url: parts.append(f"amail_url={amail_url}")
        if poll_int:  parts.append(f"poll={poll_int}s")
        c.add("bridge", "config", True, ", ".join(parts))
    except Exception as e:
        c.add("bridge", "config", False,
              f"Parse error: {e}", "Check amail_bridge.toml syntax")
        return

    # Determine if bridge is running on this machine
    local_pid = _detect_local_bridge_pid()

    # 2.2 Process — only meaningful when bridge is local
    if local_pid:
        c.add("bridge", "process", True, f"Local PID={local_pid}")
    else:
        c.add("bridge", "process", True,
              "not on this machine (check addr or PID file for local)")

    # 2.3 Activity — only local
    if local_pid and BRIDGE_LOG.exists():
        _check_bridge_activity(c)
    elif local_pid:
        c.add("bridge", "activity", True, "running, no log yet (no emails processed)")
    else:
        c.add("bridge", "activity", True, "N/A — bridge is remote")

    # 2.4 [P0] Pull path: bridge → amail-gateway (works remotely too)
    _check_bridge_pull_path(c, td)

    # 2.5 [P1] Bridge self health (remote HTTP to bridge addr)
    if addr:
        _check_bridge_health(c, addr)

    # 2.6 Cross-config: bridge ↔ gateway consistency
    _check_bridge_gateway_consistency(c, td)


def _check_bridge_gateway_consistency(c: Check, td: dict):
    """Cross-check bridge config fields against amail_gateway.json.
    All config files are local (copied by deploy_bridge.py even when
    bridge runs remotely), so these checks always run when bridge is deployed.
    """
    gw = _read_gw_cfg()
    if not gw:
        return  # gateway level will report its own error

    mismatches = []

    # (A) pull.amail_url vs gateway_url
    bridge_amail = td.get("pull", {}).get("amail_url", "")
    gw_url = gw.get("gateway_url", "").rstrip("/")
    if bridge_amail and gw_url:
        b_host = bridge_amail.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]
        g_host = gw_url.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]
        if b_host != g_host:
            mismatches.append(f"bridge pulls from '{b_host}' but gateway is '{g_host}'")

    # (B) pull.system_id vs gateway system_id
    bridge_sid = td.get("pull", {}).get("system_id", "")
    gw_sid = gw.get("system_id", "")
    if bridge_sid and gw_sid and bridge_sid != gw_sid:
        mismatches.append(f"bridge system_id differs: '{bridge_sid[:16]}...' vs '{gw_sid[:16]}...'")

    # (C) bridge addr vs gateway webhook_host
    bridge_addr = td.get("__top__", {}).get("addr", "") or td.get("bridge", {}).get("addr", "")
    gw_wh = gw.get("webhook_host", "")
    if bridge_addr and gw_wh and bridge_addr != gw_wh:
        # Only flag if both are set and they differ
        mismatches.append(f"bridge addr '{bridge_addr}' ≠ gateway webhook_host '{gw_wh}'")

    if mismatches:
        detail = "; ".join(mismatches)
        c.add("bridge", "config_consistency", False, detail,
              "Re-run integrate.sh to synchronize configs")
    else:
        c.add("bridge", "config_consistency", True, "bridge ↔ gateway configs match")


def _detect_local_bridge_pid() -> str:
    """Check if a bridge process is running on this machine. Returns PID string or ''."""
    if BRIDGE_PID.exists():
        try:
            pid = int(BRIDGE_PID.read_text().strip())
            os.kill(pid, 0)
            return str(pid)
        except Exception:
            pass
    try:
        out = subprocess.run(["pgrep", "-f", "amail-bridge"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip().replace("\n", ", ")
    except Exception:
        pass
    return ""


def _check_bridge_activity(c: Check):
    """Check log freshness. Bridge may be idle with no emails to process."""
    try:
        age = time.time() - BRIDGE_LOG.stat().st_mtime
        if age < 30:
            c.add("bridge", "activity", True, f"log {int(age)}s ago — actively running")
        elif age < 120:
            c.add("bridge", "activity", True, f"log {int(age)}s ago — may be idle")
        else:
            hrs = int(age / 3600)
            c.add("bridge", "activity", True,
                  f"log {int(age)}s ago — idle ({hrs}h)")
    except Exception as e:
        c.add("bridge", "activity", True, f"Cannot read: {e}")


def _check_bridge_pull_path(c: Check, td: dict) -> bool:
    """P0: Verify bridge credentials can reach amail-gateway pull API. Returns True if pass."""
    amail_url = td.get("pull", {}).get("amail_url", "")
    pull_key  = td.get("pull", {}).get("admin_key", "")
    pull_key  = pull_key or td.get("pull", {}).get("api_key", "")
    if not amail_url or not pull_key:
        c.add("bridge", "pull_path", False,
              "amail_url or admin_key missing in bridge config",
              "Check [pull] section in amail_bridge.toml")
        return False

    body = json.dumps({"limit": 1}).encode()
    code, resp = _json_req(
        f"{amail_url.rstrip('/')}/api/v1/admin/pending",
        headers={"X-Api-Key": pull_key, "Content-Type": "application/json"},
        data=body, method="POST")

    if code == 200:
        batches = resp.get("batches", []) if isinstance(resp, dict) else []
        detail = f"API 200, {len(batches)} pending batch(es)"
        c.add("bridge", "pull_path", True, detail)
    elif code == 400:
        # 400 can mean no routes configured on bridge side — the server
        # is reachable and auth works, just no emails to pull
        c.add("bridge", "pull_path", False,
              "HTTP 400 — route table may be empty on bridge",
              "Ensure bridge has registered routes via admin API")
    else:
        c.add("bridge", "pull_path", False,
              f"HTTP {code} — bridge cannot reach gateway's pending API",
              "Check amail_url and admin_key in amail_bridge.toml")
    return code == 200


def _check_bridge_health(c: Check, addr: str):
    """P1: Bridge self health endpoint."""
    url = f"http://{addr}/health" if "://" not in addr else f"{addr}/health"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as r:
            body = json.loads(r.read()) if r.status == 200 else {}
            status = body.get("status", "ok") if isinstance(body, dict) else "ok"
            c.add("bridge", "self_health", True,
                  f"HTTP {r.status}, status={status}")
    except Exception as e:
        c.add("bridge", "self_health", False,
              f"Unreachable at {url}: {e}",
              "Bridge binary may not be running or addr is wrong")


# ═══════════════════════════════════════════════════════════════
#  Level 3: agent-gateway (Hermes gateway → webhook → PREPROCESS)
# ═══════════════════════════════════════════════════════════════
def check_agent_gateway(c: Check):
    """agent-gateway: webhook port + route integrity + PREPROCESS + callback test (P1)"""
    port = _get_webhook_port()

    # 3.1 Webhook port
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
        with urllib.request.urlopen(req, timeout=3) as r:
            c.add("agent-gw", "webhook_port", r.status == 200,
                  f"Port {port} HTTP {r.status}")
    except Exception as e:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(("127.0.0.1", port))
            s.close()
            c.add("agent-gw", "webhook_port", True,
                  f"Port {port} TCP open (no /health)")
        except Exception:
            c.add("agent-gw", "webhook_port", False,
                  f"Port {port} unreachable",
                  "Start Hermes gateway: hermes gateway run --accept-hooks")

    # 3.2 [P0] Webhook route integrity check
    _check_webhook_routes(c)

    # 3.3 PREPROCESS registration
    hermes_dir = Path(os.environ.get("HERMES_DIR",
                                     str(HERMES_HOME / "hermes-agent")))
    webhook_py = hermes_dir / "gateway" / "platforms" / "webhook.py"
    if webhook_py.exists():
        try:
            content = webhook_py.read_text()
            ok = "PREPROCESS_REGISTRY" in content and "amail" in content.lower()
            c.add("agent-gw", "preprocess", ok,
                  "PREPROCESS found with amail handler" if ok else
                  "PREPROCESS not registered for amail",
                  "Run integrate.sh Step 7 to apply webhook patch")
        except Exception as e:
            c.add("agent-gw", "preprocess", False, f"Read error: {e}")
    else:
        c.add("agent-gw", "preprocess", False,
              "webhook.py not found (Hermes installed?)",
              "Ensure Hermes agent is installed correctly")

    # 3.4 [P1] Route targets: bridge routes → Hermes webhook
    _check_route_targets(c, port)

    # 3.5 [P1] Simulated webhook callback
    _check_webhook_callback(c, port)


def _check_webhook_routes(c: Check):
    """P0: Verify amail route completeness in webhook_subscriptions.json."""
    found = False
    for subs_path in [SUBS_FILE] + sorted(PROFILES_DIR.glob("*/webhook_subscriptions.json")):
        if not subs_path.exists():
            continue
        try:
            subs = json.loads(subs_path.read_text())
            subs_data = subs if isinstance(subs, dict) else {}
            for key, val in subs_data.items():
                if "amail" not in key.lower():
                    continue
                if not isinstance(val, dict):
                    continue
                found = True
                missing = []
                # Required fields
                if not val.get("preprocess"):
                    missing.append("preprocess")
                if not val.get("secret"):
                    missing.append("secret")
                skills = val.get("skills", [])
                if "amail" not in skills:
                    missing.append("skills=[...amail...]")
                ok = len(missing) == 0
                detail = f"route='{key}'"
                if ok:
                    detail += f", preprocess='{val.get('preprocess')}'"
                else:
                    detail += f", missing: {', '.join(missing)}"
                c.add("agent-gw", "webhook_routes", ok, detail,
                      "Run integrate.sh Step 8 to register webhook routes")
                break
            if found:
                break
        except Exception:
            continue

    if not found:
        c.add("agent-gw", "webhook_routes", False,
              "No amail-inbound route found",
              "Run integrate.sh Step 8 to register webhook routes")


def _check_route_targets(c: Check, hermes_port: int):
    """P1: Verify bridge route table targets point to a living Hermes webhook.
    Reads the local amail_routes.toml (copied by bridge to this machine)
    and checks that each unique target host:port is reachable and matches
    the Hermes webhook port.
    """
    if not ROUTES_FILE.exists():
        c.add("agent-gw", "route_targets", True,
              "no routes file (bridge not deployed or no profiles registered)")
        return

    try:
        # Parse flat key=value TOML (email = "host:port")
        raw = ROUTES_FILE.read_text()
        entries: dict[str, str] = {}
        for line in raw.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if "=" in s:
                k, v = s.split("=", 1)
                email = k.strip().strip('"')
                target = v.strip().strip('"')
                entries[email] = target

        if not entries:
            c.add("agent-gw", "route_targets", True, "routes file is empty")
            return

        # Collect unique targets
        unique_targets = sorted(set(entries.values()))
        total = len(entries)
        reachable = 0
        target_details = []

        for target in unique_targets:
            host, port_str = (target.split(":") + ["8644"])[:2]
            port = int(port_str)
            # Only check targets matching this webhook port
            if port != hermes_port:
                continue
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                s.connect((host, port))
                s.close()
                reachable += 1
                target_details.append(f"{target} alive")
            except Exception as e:
                target_details.append(f"{target} unreachable: {e}")

        ok = reachable > 0 and reachable == len(target_details)
        total_routes = total; reachable_targets = reachable; matching = len(target_details); detail = f"{total_routes} route(s) — {reachable_targets}/{matching} match webhook port {hermes_port}"
        detail = f"{total} route(s), {reachable}/{len(unique_targets)} target(s) reachable"
        if target_details:
            detail += " — " + ", ".join(target_details[:3])
            if len(target_details) > 3:
                detail += f" (+{len(target_details)-3} more)"

        c.add("agent-gw", "route_targets", ok, detail,
              "Check amail_routes.toml targets match the Hermes webhook host:port")
    except Exception as e:
        c.add("agent-gw", "route_targets", False,
              f"Cannot parse routes file: {e}")


def _check_webhook_callback(c: Check, port: int):
    """
    P1: POST minimal payload to Hermes webhook endpoint.
    Tests the final hop of the delivery chain:
      amail-gateway → (bridge) → Hermes webhook /webhooks/amail-inbound
    The bridge doesn't expose a receive endpoint — it PULLS from
    amail-gateway and PUSHES to Hermes webhook. So probing the Hermes
    webhook directly verifies the route is registered and responsive.
    """
    route_name = "amail-inbound"
    url = f"http://127.0.0.1:{port}/webhooks/{route_name}"

    payload = json.dumps({
        "message": "status-check",
        "from": "check_status@localhost",
        "subject": "amail connectivity probe",
    }).encode()

    try:
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read().decode(errors="replace")[:100]
            c.add("agent-gw", "webhook_callback", True,
                  f"route active — POST /webhooks/{route_name} → HTTP {r.status}")
    except urllib.error.HTTPError as e:
        # 401 = route exists + authenticates (our probe has no HMAC signature)
        # 403 = route exists, HMAC mismatch
        # 404 = route not registered
        ok = e.code in (200, 201, 202, 401, 403)
        if e.code == 401:
            c.add("agent-gw", "webhook_callback", True,
                  f"route active — POST /webhooks/{route_name} → 401 (HMAC required)")
        elif e.code == 403:
            c.add("agent-gw", "webhook_callback", True,
                  f"route active — POST /webhooks/{route_name} → 403 (HMAC mismatch)")
        elif e.code == 404:
            c.add("agent-gw", "webhook_callback", False,
                  f"route not found — POST /webhooks/{route_name} → 404",
                  "Run integrate.sh Step 8 to register webhook route")
        else:
            c.add("agent-gw", "webhook_callback", False,
                  f"route error — POST /webhooks/{route_name} → HTTP {e.code}",
                  "Check Hermes gateway logs")
    except Exception as e:
        c.add("agent-gw", "webhook_callback", False,
              f"Cannot reach {url}: {e}",
              "Start Hermes gateway with --accept-hooks flag")


# ═══════════════════════════════════════════════════════════════
#  Level 4: agent-profile (agent entity)
# ═══════════════════════════════════════════════════════════════
def check_profiles(c: Check):
    """agent-profile: amail.json + email + system_id + recent activity"""
    cfg = _read_gw_cfg()
    if not cfg:
        c.add("profile", "config_ref", False,
              "amail_gateway.json missing",
              "Run integrate.sh first")
        return

    system_id = cfg.get("system_id", "")
    profiles_found = 0
    profiles_ok = 0
    details = []

    # Default
    default_amail = HERMES_HOME / "amail.json"
    if default_amail.exists():
        profiles_found += 1
        try:
            pf = json.loads(default_amail.read_text())
            email = pf.get("email", "")
            sid_ok = pf.get("system_id", "") == system_id
            if email and sid_ok:
                profiles_ok += 1
                details.append(f"default: {email}")
            elif email:
                details.append(f"default: {email} (different system)")
        except Exception:
            details.append("default: unparseable")

    # Named profiles
    if PROFILES_DIR.is_dir():
        for name in sorted(os.listdir(str(PROFILES_DIR))):
            aj = PROFILES_DIR / name / "amail.json"
            if not aj.exists():
                continue
            profiles_found += 1
            try:
                pf = json.loads(aj.read_text())
                email = pf.get("email", "")
                sid_ok = pf.get("system_id", "") == system_id
                if email and sid_ok:
                    profiles_ok += 1
                    details.append(f"{name}: {email}")
                elif email:
                    details.append(f"{name}: {email} (different sys)")
            except Exception:
                details.append(f"{name}: unparseable")

    detail = f"{profiles_ok}/{profiles_found} registered" if profiles_found > 0 else "none found"
    if details:
        detail += " — " + ", ".join(details[:3])
        if len(details) > 3:
            detail += f" (+{len(details)-3} more)"
    c.add("profile", "registration", profiles_found > 0 and profiles_ok > 0,
          detail, "Run integrate.sh Step 8 to register")

    # 4.2 【P1】Last email activity from amail.log
    _check_recent_email_activity(c)


def _check_recent_email_activity(c: Check):
    """P1: Extract recent email activity from amail.log."""
    if not _agentmail_log().exists():
        c.add("profile", "recent_activity", False,
              "agentmail.log not found (no email processed yet)",
              "No activity is normal if no emails have arrived")
        return

    try:
        lines = [l.strip() for l in _agentmail_log().read_text().splitlines()
                 if l.strip()]
        if not lines:
            c.add("profile", "recent_activity", False,
                  "amail.log is empty", "Awaiting first email")
            return

        # Parse last N entries
        recent = lines[-5:]
        parsed = []
        for line in reversed(recent):
            try:
                entry = json.loads(line)
                ts = entry.get("ts", "")[:19]  # ISO datetime
                d = entry.get("dir", "")
                f = entry.get("from", "")
                t = entry.get("to", "")
                subj = entry.get("subj", "")
                age = "recent"
                try:
                    raw_ts = datetime.fromisoformat(ts)
                    age_secs = (datetime.now(timezone.utc) - raw_ts.replace(
                        tzinfo=timezone.utc)).total_seconds()
                    if age_secs < 300:
                        age = f"{int(age_secs)}s ago"
                    elif age_secs < 3600:
                        age = f"{int(age_secs/60)}m ago"
                    else:
                        age = f"{int(age_secs/3600)}h ago"
                except Exception:
                    pass
                subj_str = f" subj='{subj[:30]}'" if subj else ""
                parsed.append(f"{age} {d} from={f} to={t}{subj_str}")
            except Exception:
                parsed.append(f"(unparseable: {line[:60]}...)")

        last_age = parsed[0] if parsed else "?"
        c.add("profile", "recent_activity", True,
              f"last: {last_age}")
    except Exception as e:
        c.add("profile", "recent_activity", False,
              f"Cannot read amail.log: {e}")


# ═══════════════════════════════════════════════════════════════
#  Ping-Pong End-to-End Test
# ═══════════════════════════════════════════════════════════════
def _run_ping_test() -> int:
    """Send a ping email via SMTP and verify the pong returns."""
    import uuid, time, json, socket, base64
    from pathlib import Path

    global _AGENT_DIR

    config_path = Path.home() / ".hermes" / "amail_gateway.json"
    if not config_path.exists():
        print("✗ amail_gateway.json not found")
        return 1

    cfg = json.loads(config_path.read_text())
    gw_url = cfg.get("gateway_url", "")
    ak = cfg.get("admin_key", "")
    amail_path = Path.home() / ".hermes" / "amail.json"
    if amail_path.exists():
        acfg = json.loads(amail_path.read_text())
        agent_email = acfg.get("email", "")
    if not agent_email:
        agent_email = f"{cfg.get('system_name','tow')}@{cfg.get('domain','')}"
    # Auto-set agent dir from resolved email
    if _AGENT_DIR is None:
        _AGENT_DIR = Path.home() / ".agentmail" / agent_email.replace("@", "_")
    manager = cfg.get("manager_address", "")

    if not all([gw_url, ak, agent_email, manager]):
        print("✗ Missing required config fields")
        return 1

    ping_id = uuid.uuid4().hex[:12]
    host = gw_url.replace("https://", "").replace("http://", "").split("/")[0]

    # Send ping via SMTP auth (same mechanism as send_welcome.py)
    key_bytes = bytes.fromhex(ak)
    b64_key = base64.b64encode(key_bytes).decode().rstrip("=")
    encoded_manager = manager.replace("@", "=")
    auth_from = f"{b64_key}={encoded_manager}@auth.local"

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(15)
        s.connect((host, 25))
        banner = s.recv(4096).decode(errors="replace")
        def cmd(c):
            s.sendall(f"{c}\r\n".encode())
            return s.recv(4096).decode().strip()

        cmd("EHLO amail-ping-test")
        resp = cmd(f"MAIL FROM:<{auth_from}>")
        assert resp.startswith("250"), f"MAIL FROM failed: {resp}"
        resp = cmd(f"RCPT TO:<{agent_email}>")
        assert resp.startswith("250"), f"RCPT TO failed: {resp}"
        resp = cmd("DATA")
        assert resp.startswith("354"), f"DATA failed: {resp}"

        body = (f"From: {manager}\nTo: {agent_email}\n"
                f"Subject: __amail_ping__:{ping_id}\n"
                f"Message-ID: <ping-{ping_id}@amail.token.tm>\n"
                f"\nPing test message\n.")
        s.sendall(body.replace("\n", "\r\n").encode() + b"\r\n.\r\n")
        resp = s.recv(4096).decode().strip()
        s.sendall(b"QUIT\r\n")
        s.close()
        assert resp.startswith("250"), f"DATA end failed: {resp}"
        t_sent = time.time()
        print(f"  Ping sent: __amail_ping__:{ping_id}")
    except Exception as e:
        print(f"✗ SMTP send failed: {e}")
        return 1

    # Poll agentmail.log for pong_returned — append results incrementally
    amail_log = _agentmail_log()
    deadline = time.time() + 60
    found_ping = found_pong = found_sent = False
    ping_ts = pong_ts = sent_ts = ""

    def _parse_ts(s):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(s[:26], fmt[:len(s[:26])])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except: pass
        return None

    def _fmt_secs(ts_str, t0):
        dt = _parse_ts(ts_str)
        return (dt - t0).total_seconds() if dt else 0

    dt_sent = datetime.fromtimestamp(t_sent, tz=timezone.utc)

    while time.time() < deadline:
        if amail_log.exists():
            for line in reversed(amail_log.read_text().splitlines()):
                if ping_id not in line:
                    continue
                try:
                    entry = json.loads(line)
                    d = entry.get("dir", "")
                    ts = entry.get("ts", "")
                    if d == "ping_intercepted" and not found_ping:
                        found_ping = True
                        ping_ts = ts
                        sec = _fmt_secs(ts, dt_sent)
                        print(f"  +{sec:5.1f}s    Webhook Receive (ping)         ✓")
                    if d == "pong_sent" and found_ping and not found_sent:
                        found_sent = True
                        sent_ts = ts
                        sec = _fmt_secs(ts, dt_sent)
                        print(f"  +{sec:5.1f}s    Pong Sent (send_mail)          ✓")
                    if d == "pong_returned" and found_ping and not found_pong:
                        found_pong = True
                        pong_ts = ts
                        sec = _fmt_secs(ts, dt_sent)
                        print(f"  +{sec:5.1f}s    Webhook Return (pong)          ✓")
                        print(f"  +{sec:5.1f}s    Total round-trip: {sec:.1f}s")
                except Exception:
                    pass
        if found_ping and found_pong:
            break
        time.sleep(3)

    if not (found_ping and found_pong):
        if found_ping:
            print(f"  ✓ Ping intercepted, but pong not returned within 60s")
            return 1
        print(f"  ✗ No ping or pong detected within 60s")
        return 1

    # Verify raw email snapshots were saved
    raw_dir = _agentmail_raw()
    snap_ok = 0
    snap_total = 0
    snap_check_msg = ""
    if raw_dir.exists():
        now_ts = time.time()
        def _walk_raw(d):
            nonlocal snap_total, snap_ok
            for entry in d.iterdir():
                if entry.is_dir():
                    _walk_raw(entry)
                elif entry.is_file():
                    snap_total += 1
                    if now_ts - entry.stat().st_mtime < 300:
                        snap_ok += 1
        _walk_raw(raw_dir)
        if snap_ok > 0:
            snap_check_msg = f"✓ Snapshots: {snap_ok} new file(s) in raw_email/ (total {snap_total})"
        else:
            snap_check_msg = f"⚠ Snapshots: {snap_total} total file(s) in raw_email/, none from last 5min"
    else:
        try:
            cfg = json.loads(Path.home().joinpath(".hermes","amail.json").read_text())
            enabled = cfg.get("save_raw_snapshots", False)
        except Exception:
            enabled = False
        if enabled:
            snap_check_msg = "⚠ Snapshots enabled in config but raw_email/ directory not found"
        else:
            snap_check_msg = "⚠ Snapshots disabled in config — set save_raw_snapshots=true"
    print(f"  {snap_check_msg}")

    print(f"  ✓ Full pipeline verified — ping_id={ping_id}")
    return 0


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════
def main():
    global _AGENT_DIR
    if "--agent" in sys.argv:
        try:
            ia = sys.argv.index("--agent")
            agent = sys.argv[ia + 1]
            _AGENT_DIR = Path.home() / ".agentmail" / agent.replace("@", "_")
        except (ValueError, IndexError):
            pass
    if "--ping" in sys.argv:
        return _run_ping_test()

    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    json_out = "--json" in sys.argv

    c = Check()
    c.verbose = verbose

    check_gateway(c)
    check_bridge(c)
    check_agent_gateway(c)
    check_profiles(c)

    if json_out:
        c.print_json()
    else:
        c.print_table()
        print()
        if c.all_pass():
            print(f"  {GREEN}{BOLD}✓ All clear — amail-gateway → agent-profile ready{NC}")
        else:
            fail = sum(1 for ch in c.checks if not ch["pass"])
            print(f"  {YELLOW}{BOLD}⚠ {fail}  issue(s) — check items marked  {CROSS} {NC}")
            if not verbose:
                print(f"    Use --verbose for fix suggestions")

    return 0 if c.all_pass() else 1


if __name__ == "__main__":
    sys.exit(main())
