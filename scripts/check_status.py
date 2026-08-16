#!/usr/bin/env python3
"""
check_status.py — One-shot amail pipeline runtime status check (generic)

Covers the full chain: amail-gateway → amail-bridge → agent config →
agent hook interface → ping-pong. Platform-agnostic: works for any
agent system (Hermes/OpenClaw/DeerFlow/dsh) via a per-platform adapter
(L3/L4 vary by platform; L1/L2/L5 are shared).

Usage:
    python3 scripts/check_status.py [--agent-type hermes|openclaw|auto]
    python3 scripts/check_status.py --json       # JSON output
    python3 scripts/check_status.py --verbose    # with fix suggestions
    python3 scripts/check_status.py --ping       # run ping-pong test only
"""
import sys, os, json, subprocess, time, re, socket
from pathlib import Path
from datetime import datetime, timezone
import urllib.request, urllib.error

# ── ANSI helpers ───────────────────────────────────────────────
GREEN  = '\033[0;32m'
RED    = '\033[0;31m'
YELLOW = '\033[1;33m'
BROWN  = '\033[0;33m'
BOLD   = '\033[1m'
NC     = '\033[0m'
CHECK  = '\u2713'
CROSS  = '\u2717'

# ── Path constants ─────────────────────────────────────────────
AGENT_HOME = Path(os.environ.get("AGENT_HOME", str(Path.home() / ".hermes")))
# --agent-home 直接指定 agent 系统 home(如 Hermes profile 目录),覆盖 env 默认;
# 影响 AGENT_CFG/SUBS_FILE/PROFILES_DIR 全部派生路径
if "--agent-home" in sys.argv:
    try:
        ai = sys.argv.index("--agent-home")
        if ai + 1 < len(sys.argv):
            _ah = Path(sys.argv[ai + 1]).expanduser()
            if _ah.is_dir():
                AGENT_HOME = _ah
    except Exception:
        pass
AGENTMAIL_HOME = Path.home() / ".agentmail"
SYSTEMS_DIR = AGENTMAIL_HOME / "systems"
MAIL_DIR    = AGENTMAIL_HOME / "mail"
BRIDGE_DIR  = AGENTMAIL_HOME / "bridge"
LOGS_DIR    = AGENTMAIL_HOME / "logs"

def _clean_agent_dir_name(addr: str) -> str:
    """agent 地址 → 目录名（与 tools/agentmail_base._clean_agent_dir_name 一致）。"""
    return re.sub(r"[^\w.\-]", "_", addr)


def _split_host_port(addr: str) -> tuple[str, str]:
    """host:port 拆分(支持 [ipv6]:port)。"""
    addr = addr.strip()
    if addr.startswith("["):
        host, _, rest = addr[1:].partition("]")
        return host, rest.lstrip(":")
    host, _, port = addr.rpartition(":")
    return host, port

def _resolve_system_id(args: list[str] | None = None) -> str:
    """Determine system_id: --system-id arg > AGENT_HOME/.agentmail > env."""
    if args:
        for i, a in enumerate(args):
            if a == "--system-id" and i + 1 < len(args):
                return args[i + 1]
    pointer = AGENT_HOME / ".agentmail"
    if pointer.is_file():
        try:
            return json.loads(pointer.read_text()).get("system_id", "")
        except Exception:
            pass
    return os.environ.get("SYSTEM_ID", "")

def _resolve_agent_email() -> str:
    """Read email from AGENT_HOME/.agentmail pointer."""
    pointer = AGENT_HOME / ".agentmail"
    if pointer.is_file():
        try:
            return json.loads(pointer.read_text()).get("email", "")
        except Exception:
            pass
    return ""

def _system_agent_path(sid: str) -> Path:
    return SYSTEMS_DIR / sid / "agentmail_gateway.json"

BRIDGE_CFG  = BRIDGE_DIR / "amail_bridge.toml"
BRIDGE_PID  = BRIDGE_DIR / "bridge.pid"
BRIDGE_LOG  = LOGS_DIR / "amail-bridge.log"
AGENT_CFG   = AGENT_HOME / "config.yaml"
# --agent 指定 profile 时,读该 profile 的 config.yaml(端口随 profile)
if "--agent" in sys.argv:
    try:
        ai = sys.argv.index("--agent")
        if ai + 1 < len(sys.argv):
            _prof_cfg = AGENT_HOME / "profiles" / sys.argv[ai + 1].split("@")[0] / "config.yaml"
            if _prof_cfg.exists():
                AGENT_CFG = _prof_cfg
    except Exception:
        pass
SUBS_FILE   = AGENT_HOME / "webhook_subscriptions.json"
PROFILES_DIR = AGENT_HOME / "profiles"
ROUTES_FILE = BRIDGE_DIR / "amail_routes.toml"

# Agent-scoped paths (require --agent argument for per-agent data)
_AGENT_DIR: Path | None = None

def _agentmail_log() -> Path:
    global _AGENT_DIR
    if _AGENT_DIR:
        return LOGS_DIR / f"agentmail.{_AGENT_DIR.name}.log"
    # Fallback: read email from pointer to find the agent
    email = _resolve_agent_email()
    if email:
        _AGENT_DIR = MAIL_DIR / _clean_agent_dir_name(email)
        return LOGS_DIR / f"agentmail.{_clean_agent_dir_name(email)}.log"
    return LOGS_DIR / "agentmail.default.log"

def _agentmail_raw() -> Path:
    if _AGENT_DIR:
        return _AGENT_DIR
    return MAIL_DIR / "default"

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
            ("agent (platform config + hook interface)",  [c for c in self.checks if c["level"] == "agent"]),
            ("agent-gateway (Hermes gateway)",  [c for c in self.checks if c["level"] == "agent-gw"]),
            ("agent-profile (agent entity)",   [c for c in self.checks if c["level"] == "profile"]),
        ]
        for title, items in groups:
            if not items:
                continue
            print(f"\n  {BROWN}╓─ {title}{NC}")
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
#  Platform adapters (generic check tool — L3/L4 vary per platform)
# ═══════════════════════════════════════════════════════════════
# Each adapter provides:
#   name()                    → platform id ("hermes"/"openclaw"/...)
#   detect()                  → bool: is this platform present on this host?
#   list_agents()             → [{name, email, cfg, api_key, ...}] agents to check
#   check_config(c, agent)    → L3: name&apikey/webhook/skill/toolset/register
#   check_hook(c, agent)      → L4: inbound mail hook interface probe
# Shared L1 gateway / L2 bridge / L5 ping-pong are platform-independent.

def _detect_agent_type() -> str:
    """Probe the host for a supported agent platform. Returns id or 'unknown'.

    探测优先级(2026-08-16 双平台共存机器实测):
    ① --agent-home 被显式指定(非默认 ~/.hermes)→ 视为 Hermes 意图
       (Hermes 是唯一用 agent-home 定位的平台;OpenClaw 固定 ~/.openclaw)
    ② ~/.openclaw/openclaw.json 存在 → openclaw
    ③ AGENT_HOME 下有 hermes-agent 或 profiles/ → hermes
    ④ unknown
    """
    explicit_home = False
    if "--agent-home" in sys.argv:
        try:
            ai = sys.argv.index("--agent-home")
            v = sys.argv[ai + 1]
            if v and Path(v).expanduser() != Path.home() / ".hermes":
                explicit_home = True
        except (ValueError, IndexError):
            pass
    if explicit_home:
        return "hermes"
    if (Path.home() / ".openclaw" / "openclaw.json").is_file():
        return "openclaw"
    if (AGENT_HOME / "hermes-agent").exists() or (AGENT_HOME / "profiles").is_dir():
        return "hermes"
    return "unknown"


# ── Hermes adapter ─────────────────────────────────────────────
def _hermes_detect() -> bool:
    return (AGENT_HOME / "hermes-agent").exists() or (AGENT_HOME / "profiles").is_dir()


def _hermes_list_agents() -> list[dict]:
    """Hermes: one agent per profile (+ default root profile).

    两种布局:
    - AGENT_HOME = Hermes 根(~/.hermes):default 根 profile + profiles/*/
    - AGENT_HOME = 某 profile 目录(如 ~/.hermes/profiles/agentmail,
      check_status --agent-home 常用):该目录自身即 agent
    """
    agents = []
    is_profile_dir = (AGENT_HOME / ".agentmail").is_file() and not (AGENT_HOME / "profiles").is_dir()

    if is_profile_dir:
        # AGENT_HOME 即 profile:自身是一个 agent
        ptr = AGENT_HOME / ".agentmail"
        email = ""
        try:
            email = json.loads(ptr.read_text()).get("email", "")
        except Exception:
            pass
        agents.append({
            "name": AGENT_HOME.name, "email": email,
            "profile_dir": AGENT_HOME,
            "config": AGENT_HOME / "config.yaml",
        })
        return agents

    # Hermes 根布局:default 根 profile
    ptr = AGENT_HOME / ".agentmail"
    if ptr.is_file():
        try:
            d = json.loads(ptr.read_text())
            agents.append({
                "name": "default", "email": d.get("email", ""),
                "profile_dir": AGENT_HOME,
                "config": AGENT_HOME / "config.yaml",
            })
        except Exception:
            pass
    # Named profiles
    profiles_dir = AGENT_HOME / "profiles"
    if profiles_dir.is_dir():
        for pdir in sorted(profiles_dir.iterdir()):
            if not pdir.is_dir():
                continue
            ptr = pdir / ".agentmail"
            email = ""
            try:
                email = json.loads(ptr.read_text()).get("email", "")
            except Exception:
                pass
            agents.append({
                "name": pdir.name, "email": email,
                "profile_dir": pdir,
                "config": pdir / "config.yaml",
            })
    return agents


def _hermes_check_config(c: Check, agent: dict):
    """L3 Hermes: name&apikey / webhook / skill / toolset / register."""
    name = agent.get("name", "?")
    pd = agent.get("profile_dir")
    cfg = agent.get("config")
    email = agent.get("email", "")

    # 3.1 name & api_key: 该 agent 的 agentmail.json
    sid = _resolve_system_id()
    aj_path = (SYSTEMS_DIR / sid / _clean_agent_dir_name(email) / "agentmail.json") if (sid and email) else None
    api_key = ""
    if aj_path and aj_path.is_file():
        try:
            api_key = json.loads(aj_path.read_text()).get("api_key", "")
        except Exception:
            pass
    ok = bool(email and api_key)
    c.add("agent", "name_apikey", ok,
          f"{name}: {email or 'no email'}" + (", api_key ✓" if api_key else ", api_key MISSING"),
          "Run register_profiles.py to register the profile")

    # 3.2 webhook: profile config platforms.webhook + route secret
    wh_ok = False
    try:
        import yaml
        if cfg and cfg.exists():
            wh = (yaml.safe_load(cfg.read_text()) or {}).get("platforms", {}).get("webhook", {})
            wh_ok = bool(wh.get("enabled") and wh.get("extra", {}).get("secret"))
    except Exception:
        pass
    c.add("agent", "webhook", wh_ok,
          f"{name}: webhook " + ("enabled + secret ✓" if wh_ok else "MISSING (platforms.webhook)"),
          "Run ensure_webhook_config.py / configure.sh")

    # 3.3 skill: profile skills/agentmail/
    skill_dir = pd / "skills" / "agentmail" if pd else None
    skill_ok = bool(skill_dir and skill_dir.is_dir())
    c.add("agent", "skill", skill_ok,
          f"{name}: skills/agentmail " + ("✓" if skill_ok else "MISSING"),
          "Run install-skill or copy skills/SKILL.md")

    # 3.4 toolset: platform_toolsets.webhook/cli 含 agentmail
    ts_ok = False
    try:
        import yaml
        if cfg and cfg.exists():
            pt = (yaml.safe_load(cfg.read_text()) or {}).get("platform_toolsets", {})
            for seg in ("webhook", "cli"):
                tools = pt.get(seg) or []
                if "agentmail" in tools:
                    ts_ok = True
                    break
    except Exception:
        pass
    c.add("agent", "toolset", ts_ok,
          f"{name}: platform_toolsets " + ("含 agentmail ✓" if ts_ok else "MISSING"),
          "Run ensure_webhook_config.py")

    # 3.5 register: 云端注册(api_key 存在 + webhook route 存在)
    route_ok = False
    subs = pd / "webhook_subscriptions.json" if pd else None
    if subs and subs.exists():
        try:
            routes = json.loads(subs.read_text())
            route_ok = any("agentmail" in k.lower() for k in (routes or {}))
        except Exception:
            pass
    reg_ok = bool(api_key and route_ok)
    c.add("agent", "register", reg_ok,
          f"{name}: " + ("registered ✓" if reg_ok else "api_key/route 不全"),
          "Run register_profiles.py")


def _hermes_check_hook(c: Check, agent: dict):
    """L4 Hermes: POST /webhooks/agentmail-inbound — route registered & responsive."""
    port = 8646
    try:
        import yaml
        cfg = agent.get("config")
        if cfg and cfg.exists():
            wh = (yaml.safe_load(cfg.read_text()) or {}).get("platforms", {}).get("webhook", {})
            port = int(wh.get("port") or wh.get("extra", {}).get("port") or 8646)
    except Exception:
        pass
    route_name = "agentmail-inbound"
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
            c.add("agent", "hook", True, f"POST {route_name} → HTTP {r.status}")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):  # route 存在 + 验签保护
            c.add("agent", "hook", True,
                  f"POST {route_name} → {e.code} (route active, HMAC required)")
        elif e.code == 404:
            c.add("agent", "hook", False, f"POST {route_name} → 404 route missing",
                  "Run register_profiles.py to create the route")
        else:
            c.add("agent", "hook", False, f"POST {route_name} → HTTP {e.code}")
    except Exception as e:
        c.add("agent", "hook", False, f"Cannot reach {url}: {e}",
              "Start Hermes gateway with --accept-hooks")


# ── OpenClaw adapter ───────────────────────────────────────────
def _openclaw_detect() -> bool:
    return (Path.home() / ".openclaw" / "openclaw.json").is_file()


def _openclaw_list_agents() -> list[dict]:
    """OpenClaw: one agent per ~/.openclaw/agents/{id}."""
    agents = []
    agents_dir = Path.home() / ".openclaw" / "agents"
    # OpenClaw 系统指针在 ~/.openclaw/.agentmail(不依赖 AGENT_HOME)
    sid = ""
    ptr = Path.home() / ".openclaw" / ".agentmail"
    if ptr.is_file():
        try:
            sid = json.loads(ptr.read_text()).get("system_id", "")
        except Exception:
            pass
    if not sid:
        sid = _resolve_system_id()
    if agents_dir.is_dir():
        for adir in sorted(agents_dir.iterdir()):
            if not adir.is_dir():
                continue
            email = ""
            # amail email 从系统 agentmail.json 反查(agent_id 匹配)
            sysdir = SYSTEMS_DIR / sid
            if sysdir.is_dir():
                for sub in sysdir.iterdir():
                    aj = sub / "agentmail.json"
                    if aj.is_file():
                        try:
                            d = json.loads(aj.read_text())
                            if d.get("agent_id") == adir.name:
                                email = d.get("email", "")
                                break
                        except Exception:
                            pass
            agents.append({
                "name": adir.name, "email": email,
                "agent_dir": adir,
                "config": Path.home() / ".openclaw" / "openclaw.json",
            })
    return agents


def _openclaw_check_config(c: Check, agent: dict):
    """L3 OpenClaw: name&apikey / webhook / skill / toolset / register."""
    name = agent.get("name", "?")
    email = agent.get("email", "")

    # 3.1 name & api_key(用 OpenClaw 指针的 sid,同 list_agents)
    sid = ""
    ptr = Path.home() / ".openclaw" / ".agentmail"
    if ptr.is_file():
        try:
            sid = json.loads(ptr.read_text()).get("system_id", "")
        except Exception:
            pass
    if not sid:
        sid = _resolve_system_id()
    aj_path = (SYSTEMS_DIR / sid / _clean_agent_dir_name(email) / "agentmail.json") if (sid and email) else None
    api_key = ""
    if aj_path and aj_path.is_file():
        try:
            api_key = json.loads(aj_path.read_text()).get("api_key", "")
        except Exception:
            pass
    ok = bool(email and api_key)
    c.add("agent", "name_apikey", ok,
          f"{name}: {email or 'no email'}" + (", api_key ✓" if api_key else ", api_key MISSING"),
          "Run register_agent.py --all")

    # 3.2 webhook: agentmail.json webhook_secret
    wh_ok = False
    if aj_path and aj_path.is_file():
        try:
            wh_ok = bool(json.loads(aj_path.read_text()).get("webhook_secret"))
        except Exception:
            pass
    c.add("agent", "webhook", wh_ok,
          f"{name}: webhook_secret " + ("✓" if wh_ok else "MISSING"),
          "Re-run register_agent.py (persists webhook_secret)")

    # 3.3 skill: ~/.openclaw/skills/agentmail/
    skill_ok = (Path.home() / ".openclaw" / "skills" / "agentmail").is_dir()
    c.add("agent", "skill", skill_ok,
          f"{name}: skills/agentmail " + ("✓" if skill_ok else "MISSING"),
          "Run install-skill.sh")

    # 3.4 toolset: openclaw.json mcp.servers.amail
    ts_ok = False
    try:
        oc_path = agent.get("config")
        if oc_path and oc_path.exists():
            oc = json.loads(oc_path.read_text())
            mcp = oc.get("mcp", {})
            servers = mcp.get("servers", {}) if isinstance(mcp, dict) else {}
            ts_ok = "amail" in servers
    except Exception:
        pass
    c.add("agent", "toolset", ts_ok,
          f"{name}: mcp.servers.amail " + ("✓" if ts_ok else "MISSING"),
          "Add amail MCP server to openclaw.json")

    # 3.5 register
    reg_ok = bool(api_key)
    c.add("agent", "register", reg_ok,
          f"{name}: " + ("registered ✓" if reg_ok else "api_key MISSING"),
          "Run register_agent.py --all")


def _openclaw_check_hook(c: Check, agent: dict):
    """L4 OpenClaw: receiver endpoint (amail_openclaw_bridge.py) probe."""
    url = "http://127.0.0.1:8799/hook"
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
            c.add("agent", "hook", True, f"POST /hook → HTTP {r.status}")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            c.add("agent", "hook", True, f"POST /hook → {e.code} (receiver active)")
        elif e.code == 404:
            c.add("agent", "hook", False, f"POST /hook → 404",
                  "Start amail_openclaw_bridge.py on port 8799")
        else:
            c.add("agent", "hook", False, f"POST /hook → HTTP {e.code}")
    except Exception as e:
        c.add("agent", "hook", False, f"Cannot reach {url}: {e}",
              "Start amail_openclaw_bridge.py on port 8799")


PLATFORMS = {
    "hermes": {
        "detect": _hermes_detect,
        "list_agents": _hermes_list_agents,
        "check_config": _hermes_check_config,
        "check_hook": _hermes_check_hook,
    },
    "openclaw": {
        "detect": _openclaw_detect,
        "list_agents": _openclaw_list_agents,
        "check_config": _openclaw_check_config,
        "check_hook": _openclaw_check_hook,
    },
}


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


def _resolve_platform_sid(agent_type: str) -> str:
    """平台相关 system_id:Hermes = AGENT_HOME 指针;OpenClaw =
    ~/.openclaw/.agentmail 指针。--system-id 显式指定优先。"""
    if "--system-id" in sys.argv:
        try:
            ai = sys.argv.index("--system-id")
            if ai + 1 < len(sys.argv):
                return sys.argv[ai + 1]
        except (ValueError, IndexError):
            pass
    if agent_type == "openclaw":
        ptr = Path.home() / ".openclaw" / ".agentmail"
    else:
        ptr = AGENT_HOME / ".agentmail"
    if ptr.is_file():
        try:
            return json.loads(ptr.read_text()).get("system_id", "")
        except Exception:
            pass
    return os.environ.get("SYSTEM_ID", "")


def _read_gw_cfg(sid: str = "") -> dict | None:
    """Load ~/.agentmail/system-{sid}/agentmail_gateway.json, return None on failure."""
    if not sid:
        sid = _resolve_system_id(sys.argv)
    p = _system_agent_path(sid) if sid else SYSTEMS_DIR / "agentmail_gateway.json"
    if not p.exists() or not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _get_webhook_port() -> int:
    """Read webhook port from config.yaml."""
    if AGENT_CFG.exists():
        try:
            import yaml
            with open(AGENT_CFG) as f:
                hc = yaml.safe_load(f) or {}
            return int(hc.get("platforms", {}).get("webhook", {})
                      .get("extra", {}).get("port", 8644))
        except Exception:
            pass
    return 8644


# ═══════════════════════════════════════════════════════════════
#  Level 1: amail-gateway (external mail gateway)
# ═══════════════════════════════════════════════════════════════
def check_gateway(c: Check, sid: str = ""):
    """amail-gateway: health + SMTP port + API credentials"""
    cfg = _read_gw_cfg(sid)
    if not cfg:
        c.add("gateway", "config", False,
              "agentmail_gateway.json not found",
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
        # agent_admin 是集成后 config 中的标准 key 类别(9dca44e 架构)
        ok = ("platform" in scope or "system" in scope
              or "agent_admin" in scope or cat == "agent_admin")
        c.add("gateway", "api_key", ok,
              f"scope={scope}, category={cat}, system_id={sid[:16]}..." if ok else
              f"scope={scope} — need platform/system/agent_admin",
              "Use a key with platform, system or agent_admin scope")
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
    """Cross-check bridge config fields against agentmail_gateway.json.
    All config files are local (copied by deploy_bridge.py even when
    bridge runs remotely), so these checks always run when bridge is deployed.
    """
    gw = _read_gw_cfg()
    if not gw:
        return  # gateway level will report its own error

    mismatches = []

    # 用标准 tomllib 重读 bridge 配置(自定义 _parse_toml 不支持数组)
    try:
        import tomllib
        with open(BRIDGE_CFG, "rb") as _f:
            _td = tomllib.load(_f)
    except Exception:
        _td = td

    # (A) pull.amail_url vs gateway_url
    pull_cfg = _td.get("pull", {})
    systems = pull_cfg.get("systems") or []
    if systems:
        bridge_amail = systems[0].get("amail_url", "")
        bridge_sid = systems[0].get("system_id", "")
    else:
        bridge_amail = pull_cfg.get("amail_url", "")
        bridge_sid = pull_cfg.get("system_id", "")
    gw_url = gw.get("gateway_url", "").rstrip("/")
    if bridge_amail and gw_url:
        b_host = bridge_amail.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]
        g_host = gw_url.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]
        if b_host != g_host:
            mismatches.append(f"bridge pulls from '{b_host}' but gateway is '{g_host}'")

    # (B) pull.system_id vs gateway system_id
    gw_sid = gw.get("system_id", "")
    if bridge_sid and gw_sid and bridge_sid != gw_sid:
        mismatches.append(f"bridge system_id differs: '{bridge_sid[:16]}...' vs '{gw_sid[:16]}...'")

    # (C) bridge addr vs gateway webhook_host
    # NAT 部署: bridge 绑定本地地址(127.0.0.1/0.0.0.0/::)而 webhook_host 是
    # 公网映射地址,两者必然不同——此时只比较端口;两边都是具体公网地址才
    # 要求完全一致。
    bridge_addr = _td.get("__top__", {}).get("addr", "") or _td.get("bridge", {}).get("addr", "")
    gw_wh = gw.get("webhook_host", "")
    if bridge_addr and gw_wh and bridge_addr != gw_wh:
        _bhost, _bport = _split_host_port(bridge_addr)
        _ghost, _gport = _split_host_port(gw_wh)
        _local_hosts = ("0.0.0.0", "::", "", "127.0.0.1", "localhost", "[::1]")
        if _bhost in _local_hosts and _bport and _bport == _gport:
            pass  # 本地绑定 + 端口一致 = 配置一致(NAT 映射到公网同端口)
        else:
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
    # 多系统支持:pull.systems 数组优先,空则回退单系统扁平字段。
    # 用标准 tomllib 重读(自定义 _parse_toml 不支持数组)。
    try:
        import tomllib
        with open(BRIDGE_CFG, "rb") as _f:
            _td = tomllib.load(_f)
        pull_cfg = _td.get("pull", {})
    except Exception:
        pull_cfg = td.get("pull", {})
    systems = pull_cfg.get("systems") or []
    if systems:
        amail_url = systems[0].get("amail_url", "")
        pull_key = systems[0].get("api_key", "") or systems[0].get("admin_key", "")
    else:
        amail_url = pull_cfg.get("amail_url", "")
        pull_key = pull_cfg.get("admin_key", "")
        pull_key = pull_key or pull_cfg.get("api_key", "")
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
    except Exception:
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
    # hermes-agent 源码仓位于 hermes 根(profile 目录时上溯两层)
    _hermes_root = AGENT_HOME.parent.parent if AGENT_HOME.parent.name == "profiles" else AGENT_HOME
    hermes_dir = Path(os.environ.get("HERMES_DIR", str(_hermes_root / "hermes-agent")))
    webhook_py = hermes_dir / "gateway" / "platforms" / "webhook.py"
    if webhook_py.exists():
        try:
            content = webhook_py.read_text()
            ok = "PREPROCESS_REGISTRY" in content and "agentmail" in content.lower()
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
                if "agentmail" not in key.lower():
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
                if "agentmail" not in skills:
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
              "No agentmail-inbound route found",
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
            # 支持全 URL(http://host:port/path)与裸 host:port 两种格式
            if target.startswith("http://") or target.startswith("https://"):
                from urllib.parse import urlparse
                u = urlparse(target)
                host = u.hostname or "127.0.0.1"
                port = u.port or (443 if u.scheme == "https" else 80)
            else:
                host, port_str = target.rsplit(":", 1)
                port = int(port_str)
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
      amail-gateway → (bridge) → Hermes webhook /webhooks/agentmail-inbound
    The bridge doesn't expose a receive endpoint — it PULLS from
    amail-gateway and PUSHES to Hermes webhook. So probing the Hermes
    webhook directly verifies the route is registered and responsive.
    """
    route_name = "agentmail-inbound"
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
            c.add("agent-gw", "webhook_callback", True,
                  f"route active — POST /webhooks/{route_name} → HTTP {r.status}")
    except urllib.error.HTTPError as e:
        # 401 = route exists + authenticates (our probe has no HMAC signature)
        # 403 = route exists, HMAC mismatch
        # 404 = route not registered
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
    """agent-profile: agentmail.json + email + system_id + recent activity"""
    cfg = _read_gw_cfg()
    if not cfg:
        c.add("profile", "config_ref", False,
              "agentmail_gateway.json missing",
              "Run integrate.sh first")
        return

    system_id = cfg.get("system_id", "")
    profiles_found = 0
    profiles_ok = 0
    details = []

    # Scan ~/.agentmail/systems/{system_id}/ for address-keyed configs
    sysdir = SYSTEMS_DIR / system_id
    if sysdir.is_dir():
        for name in sorted(os.listdir(str(sysdir))):
            aj = sysdir / name / "agentmail.json"
            if not aj.is_file():
                continue
            profiles_found += 1
            try:
                pf = json.loads(aj.read_text())
                email = pf.get("email", "")
                if email:
                    profiles_ok += 1
                    details.append(f"{name}: {email}")
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
        c.add("profile", "recent_activity", True,
              "no email activity yet (new system)")
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
#  Ping-Pong End-to-End Test (delegated to shared scripts/ping_test.py)
# ═══════════════════════════════════════════════════════════════
def _run_ping_test() -> int:
    """Delegate to the shared, agent-agnostic ping test script.

    The implementation moved to scripts/ping_test.py (SMTP auth inbound +
    agentmail.log three-stage assertion) so every agent system
    (Hermes/OpenClaw/DeerFlow/dsh) uses the SAME ping/pong verification.
    """
    import subprocess
    script = Path(__file__).resolve().parent / "ping_test.py"
    cmd = [sys.executable, str(script)]
    if "--system-id" in sys.argv:
        try:
            i = sys.argv.index("--system-id")
            cmd += ["--system-id", sys.argv[i + 1]]
        except (ValueError, IndexError):
            pass
    if "--agent" in sys.argv:
        try:
            i = sys.argv.index("--agent")
            cmd += ["--agent", sys.argv[i + 1]]
        except (ValueError, IndexError):
            pass
    cmd += ["--agent-home", str(AGENT_HOME)]
    return subprocess.call(cmd)


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════
def main():
    global _AGENT_DIR
    if "--agent" in sys.argv:
        try:
            ia = sys.argv.index("--agent")
            agent = sys.argv[ia + 1]
            _AGENT_DIR = MAIL_DIR / _clean_agent_dir_name(agent)
        except (ValueError, IndexError):
            pass
    if "--ping" in sys.argv:
        return _run_ping_test()

    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    json_out = "--json" in sys.argv

    # 平台识别:--agent-type 显式指定,否则自动探测
    agent_type = "auto"
    if "--agent-type" in sys.argv:
        try:
            ai = sys.argv.index("--agent-type")
            agent_type = sys.argv[ai + 1]
        except (ValueError, IndexError):
            pass
    if agent_type == "auto":
        agent_type = _detect_agent_type()
    adapter = PLATFORMS.get(agent_type)
    if not adapter:
        print(f"{YELLOW}⚠ Unknown agent platform: {agent_type} (auto-detect → {_detect_agent_type()}){NC}")

    # 平台相关 sid(Hermes=AGENT_HOME 指针 / OpenClaw=~/.openclaw 指针)
    platform_sid = _resolve_platform_sid(agent_type)

    c = Check()
    c.verbose = verbose

    # L1 gateway(通用)
    check_gateway(c, platform_sid)
    # L2 bridge(通用,未部署自动跳过)
    check_bridge(c)

    # L3/L4 agent 配置完整性 + hook 接口(平台适配)
    if adapter:
        agents = adapter["list_agents"]()
        if not agents:
            c.add("agent", "discovery", False,
                  f"no agents found for platform '{agent_type}'",
                  "Check the platform home dir / agents registry")
        for a in agents:
            try:
                adapter["check_config"](c, a)
            except Exception as e:
                c.add("agent", "config", False, f"{a.get('name')}: {e}")
            try:
                adapter["check_hook"](c, a)
            except Exception as e:
                c.add("agent", "hook", False, f"{a.get('name')}: {e}")
    else:
        # 未知平台:回退旧 Hermes 专用检查(兼容)
        check_agent_gateway(c)
        check_profiles(c)

    if json_out:
        c.print_json()
    else:
        c.print_table()
        print()
        if c.all_pass():
            print(f"  {GREEN}{BOLD}✓ All clear — amail-gateway → agent-platform ready{NC}")
        else:
            fail = sum(1 for ch in c.checks if not ch["pass"])
            print(f"  {YELLOW}{BOLD}⚠ {fail}  issue(s) — check items marked  {CROSS} {NC}")
            if not verbose:
                print("    Use --verbose for fix suggestions")

    return 0 if c.all_pass() else 1


if __name__ == "__main__":
    sys.exit(main())
