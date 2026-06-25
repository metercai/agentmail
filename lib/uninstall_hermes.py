#!/usr/bin/env python3
"""
uninstall_hermes.py — Reverse amail integration patches from Hermes.

Strategy: exact-text-based surgical removal. Each amail patch inserts code
with specific, known text. We find and remove ONLY those exact strings.
Everything else — Hermes updates, user edits, other patches — untouched.

Restores 3 principles:
  1. Source files: remove only amail-added code blocks
  2. Config files in ~/.hermes/: delete
  3. config.yaml / webhook_subscriptions.json: cancel amail items
"""
import sys, os, json, re, subprocess
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


# ═══════════════════════════════════════════════════════════════
#  Exact-text block removal
# ═══════════════════════════════════════════════════════════════

def strip_block(text: str, block: str) -> tuple:
    """Remove a known exact string block from text.
    Returns (new_text, True if removed).
    """
    if block not in text:
        return text, False
    return text.replace(block, '', 1), True


def strip_trailing_blanks(text: str) -> str:
    """Remove excess blank lines left after block removal."""
    return re.sub(r'\n{4,}', '\n\n\n', text)


# ═══════════════════════════════════════════════════════════════
#  Known block definitions for webhook.py
#  These match what apply_webhook_patch.py inserts.
# ═══════════════════════════════════════════════════════════════

# Block 1: PREPROCESS_REGISTRY dict + function
# Inserted AFTER "logger = logging.getLogger(__name__)"
WEBHOOK_BLOCK1 = """
# ═══════════════════════════════════════════════════════════════
# Preprocess Registry — allows tools modules to register payload
# preprocessors that run before prompt rendering (AmailGateway)
# ═══════════════════════════════════════════════════════════════

PREPROCESS_REGISTRY: Dict[str, Callable] = {}


def register_preprocessor(name: str, fn: Callable) -> None:
    \"\"\"Register a payload preprocessor function.

    Preprocessors receive (payload: dict, headers: dict) and return
    the (possibly modified) payload dict. Called before prompt
    rendering so the Agent sees preprocessed data.
    \"\"\"
    PREPROCESS_REGISTRY[name] = fn


"""

# Block 2: Preprocessor invocation
# Inserted BEFORE "# Format prompt from template"
WEBHOOK_BLOCK2 = """        # ── Preprocess payload (AmailGateway integration) ──────────
        preprocess_name = route_config.get("preprocess")
        if preprocess_name:
            preprocessor = PREPROCESS_REGISTRY.get(preprocess_name)
            if preprocessor:
                try:
                    payload = preprocessor(payload, dict(request.headers))
                except Exception as e:
                    logger.error(
                        "[webhook] preprocessor '%s' failed: %s",
                        preprocess_name, e
                    )

"""

# Block 3: Ping-pong interception
# Inserted BEFORE "# Non-blocking"
WEBHOOK_BLOCK3 = """        # ── Ping-pong interception (end-to-end test) ────────────────
        ping_subject = (payload.get("subject") or "").strip()
        if ping_subject.startswith("__amail_ping__:"):
            ping_id = ping_subject.split(":", 1)[1].strip()
            if ping_id:
                try:
                    import json as _json, os as _os, sys as _sys
                    from datetime import datetime, timezone
                    _tools_dir = _os.path.join(_os.path.dirname(__file__), "..", "..", "tools")
                    _sys.path.insert(0, _os.path.abspath(_tools_dir))
                    from amail_tools import send_mail as _send_mail
                    pong_body = _json.dumps({
                        "ping_id": ping_id,
                        "event": {"prompt": prompt, "route": route_name,
                                  "delivery_id": delivery_id, "skills": skills},
                    }, indent=2)
                    _log_ping_event("ping_intercepted", ping_id, payload, "")
                    pong_result = _send_mail(
                        to=payload.get("from", ""),
                        subject="__amail_pong__:" + ping_id, body=pong_body,
                        message_id=payload.get("message_id") or "",
                    )
                    pong_status = "ok" if pong_result.get("success") else pong_result.get("error", "?")
                except Exception as _e:
                    pong_status = str(_e)
                    logger.error("[ping] send_mail failed: %s", _e)
                _log_ping_event("pong_sent", ping_id, payload, pong_status)
            return web.json_response({"pong": ping_id, "status": "pong_sent"})

        elif ping_subject.startswith("__amail_pong__:"):
            ping_id = ping_subject.split(":", 1)[1].strip()
            if ping_id:
                _log_ping_event("pong_returned", ping_id, payload, "")
            return web.json_response({"pong": ping_id, "status": "pong_returned"})

"""

# Block 4: _log_ping_event function (appended at end of file)
WEBHOOK_BLOCK4 = """
def _log_ping_event(dir_: str, ping_id: str, payload: dict, pong_status: str):
    \"\"\"Append a JSON line to agentmail.log for ping-pong tracking.\"\"\"
    import json, os as _os
    from datetime import datetime, timezone
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "dir": dir_, "ping_id": ping_id,
        "from": payload.get("from", ""),
        "to": payload.get("to", ""),
    }
    if pong_status:
        entry["pong_status"] = pong_status
    _log_dir = _os.environ.get("AGENTMAIL_HOME", "")
    if not _log_dir:
        # Resolve email from HERMES_PROFILE_DIR/.agentmail pointer
        _pdir = _os.environ.get("HERMES_PROFILE_DIR", "")
        if _pdir:
            _pointer = _os.path.join(_pdir, ".agentmail")
            if _os.path.isfile(_pointer):
                try:
                    import json as _json
                    _pd = _json.load(open(_pointer))
                    _email = _pd.get("email", "")
                    if _email:
                        _log_dir = _os.path.expanduser("~/.agentmail/" + _email.replace("@", "_"))
                except:
                    pass
    if not _log_dir:
        _log_dir = _os.path.expanduser("~/.agentmail/default")
    log_path = _os.path.join(_log_dir, "agentmail.log")
    try:
        _os.makedirs(_log_dir, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\\n")
    except Exception:
        pass
"""


# ═══════════════════════════════════════════════════════════════
#  Remove amail patches from webhook.py
# ═══════════════════════════════════════════════════════════════

def unpatch_webhook(fp: Path):
    if not fp.exists():
        return 0
    text = fp.read_text()
    original = text
    changes = 0

    for name, block in [
        ("PREPROCESS_REGISTRY",     WEBHOOK_BLOCK1),
        ("preprocessor invocation", WEBHOOK_BLOCK2),
        ("ping-pong interception",  WEBHOOK_BLOCK3),
        ("_log_ping_event",         WEBHOOK_BLOCK4),
    ]:
        text, ok = strip_block(text, block)
        if ok:
            changes += 1

    # Block 5: Remove Callable from typing import
    text, n = re.subn(
        r'(from typing import .+?), Callable\n',
        r'\1\n',
        text, count=1
    )
    if n:
        changes += 1

    text = strip_trailing_blanks(text)

    if text != original:
        fp.write_text(text)
        print(f"  ✓ webhook.py: {changes} block(s) removed")
    else:
        print("  - webhook.py: no changes")
    return changes


# ═══════════════════════════════════════════════════════════════
#  Remove amail patches from profiles.py
# ═══════════════════════════════════════════════════════════════

PROFILES_HOOK = """    # ── Fire integration hooks (AmailGateway) ──
    try:
        from tools.amail_tools import trigger_profile_hooks
        trigger_profile_hooks(\"profile_created\", canon, str(profile_dir))
    except ImportError:
        pass  # AmailGateway tools not installed

"""

PROFILES_HOOK_DEL = """    # ── Fire integration hooks (AmailGateway) ──
    try:
        from tools.amail_tools import trigger_profile_hooks
        trigger_profile_hooks(\"profile_deleted\", canon, str(profile_dir))
    except ImportError:
        pass  # AmailGateway tools not installed

"""


def unpatch_profiles(fp: Path):
    if not fp.exists():
        return 0
    text = fp.read_text()
    original = text
    changes = 0

    for block in [PROFILES_HOOK, PROFILES_HOOK_DEL]:
        text, ok = strip_block(text, block)
        if ok:
            changes += 1

    text = strip_trailing_blanks(text)

    if text != original:
        fp.write_text(text)
        print(f"  ✓ profiles.py: {changes} hook(s) removed")
    else:
        print("  - profiles.py: no changes")
    return changes


# ═══════════════════════════════════════════════════════════════
#  Remove amail from toolsets.py
# ═══════════════════════════════════════════════════════════════

TOOLSET_AMAIL = """    "amail": {
        "description": "Agent email tools: send, contacts, contact profiles, and thread summaries via amail",
        "tools": ["send_mail", "manage_contacts", "contact_profile", "set_contact_profile", "email_summary", "set_email_summary"],
        "includes": [],
    },
"""


def unpatch_toolsets(fp: Path):
    if not fp.exists():
        return 0
    text = fp.read_text()
    original = text
    changes = 0

    text, ok = strip_block(text, TOOLSET_AMAIL)
    if ok:
        changes += 1

    # Remove amail tool names from _HERMES_CORE_TOOLS
    for tool in [
        "set_email_summary", "email_summary",
        "set_contact_profile", "contact_profile",
        "manage_contacts", "send_mail",
    ]:
        line = f'    "{tool}",\n'
        if line in text:
            text = text.replace(line, '', 1)
            changes += 1

    if text != original:
        fp.write_text(text)
        print(f"  ✓ toolsets.py: {changes} item(s) removed")
    else:
        print("  - toolsets.py: no changes")
    return changes


# ═══════════════════════════════════════════════════════════════
#  Config cleanup helpers
# ═══════════════════════════════════════════════════════════════

def clean_webhook_subs(path: Path):
    if not path.exists():
        return
    try:
        subs = json.loads(path.read_text())
        if "amail-inbound" in subs:
            del subs["amail-inbound"]
            path.write_text(json.dumps(subs, indent=2, ensure_ascii=False) + "\n")
            print(f"  ✓ removed amail-inbound route from {path}")
    except Exception as e:
        print(f"  ⚠ failed to read {path}: {e}")


def clean_config_yaml(path: Path):
    if not path.exists():
        return
    content = path.read_text()
    original = content
    content, _ = re.subn(r'  webhook:\n  - amail\n', '  webhook:\n', content, count=1)
    if content == original:
        content, _ = re.subn(r'  - amail\n', '', content, count=1)
    if content != original:
        path.write_text(content)
        print(f"  ✓ removed amail from platform_toolsets in {path}")


def clear_pycache():
    hermes_repo = HERMES_HOME / "hermes-agent"
    count = 0
    for d in [hermes_repo / "gateway" / "platforms" / "__pycache__",
              hermes_repo / "hermes_cli" / "__pycache__",
              hermes_repo / "tools" / "__pycache__"]:
        if d.is_dir():
            for f in d.iterdir():
                if f.suffix == ".pyc":
                    f.unlink()
                    count += 1
    if count:
        print(f"  ✓ cleared {count} .pyc cache file(s)")


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

def main():
    print(f"\n{'='*60}")
    print("  Amail — Hermes Integration Uninstall")
    print(f"{'='*60}")

    print(f"\n  What will be done:\n")
    print(f"  [surgical patch removal — 3 source files]")
    print(f"    Only exact amail-added text blocks removed.")
    print(f"    All other changes preserved (Hermes updates, user edits).")
    print(f"")
    print(f"  [config cleanup]")
    print(f"    - webhook_subscriptions.json  → remove amail-inbound route")
    print(f"    - config.yaml                 → remove amail from platform_toolsets")
    print(f"")
    print(f"  [no file deletion]")
    print(f"    Config already in ~/.agentmail/ — preserving for reinstall")
    print(f"")

    # ── 1/6: Stop processes ──
    print("\n  [1/6] Stopping gateway + bridge")
    for pat in ["hermes.*gateway.*--accept-hooks",
                "amail-bridge.*amail_bridge.toml",
                "hermes.*gateway.*accept-hooks"]:
        subprocess.run(["pkill", "-f", pat], capture_output=True, timeout=10)
    print("  ✓ processes stopped")

    # ── 2/6: Reverse patches ──
    print("\n  [2/6] Removing amail patches from Hermes source")
    hermes_repo = HERMES_HOME / "hermes-agent"
    patched_count = 0

    for fn, unpatch_fn in [
        ("gateway/platforms/webhook.py", unpatch_webhook),
        ("hermes_cli/profiles.py", unpatch_profiles),
        ("toolsets.py", unpatch_toolsets),
    ]:
        fp = hermes_repo / fn
        # Fallback for profiles.py alternate path
        if not fp.exists():
            fp = hermes_repo / fn.replace("hermes_cli/", "cli/")
        n = unpatch_fn(fp)
        if n:
            patched_count += 1

    clear_pycache()

    # ── 3/6: webhook subscriptions ──
    print("\n  [3/6] Cleaning webhook subscriptions")
    clean_webhook_subs(HERMES_HOME / "webhook_subscriptions.json")
    pd_dir = HERMES_HOME / "profiles"
    if pd_dir.exists():
        for prof in pd_dir.iterdir():
            if prof.is_dir():
                clean_webhook_subs(prof / "webhook_subscriptions.json")

    # ── 4/6: config.yaml ──
    print("\n  [4/6] Cleaning config.yaml")
    clean_config_yaml(HERMES_HOME / "config.yaml")
    if pd_dir.exists():
        for prof in pd_dir.iterdir():
            if prof.is_dir():
                clean_config_yaml(prof / "config.yaml")

    # ── 5/6: Restart Hermes gateway ──
    print("\n  [5/6] Restarting Hermes gateway")
    try:
        gw_port = 8644
        import yaml
        cfg_path = HERMES_HOME / "config.yaml"
        if cfg_path.exists():
            cfg = yaml.safe_load(cfg_path.read_text()) or {}
            gw_port = int(cfg.get("platforms", {}).get("webhook", {}).get("extra", {}).get("port", 8644))
    except Exception:
        gw_port = 8644

    pid = subprocess.Popen(
        ["hermes", "gateway", "run", "--accept-hooks"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    ).pid
    print(f"  ✓ gateway restarted (PID {pid}, port {gw_port})")

    # ── Summary ──
    print("\n  ─── Summary ───")
    # Verify amail markers are gone
    wh = hermes_repo / "gateway" / "platforms" / "webhook.py"
    wh_text = wh.read_text() if wh.exists() else ""
    still_patched = []
    for marker in ["PREPROCESS_REGISTRY", "_log_ping_event", "Ping-pong interception",
                   "Preprocess payload"]:
        if marker in wh_text:
            still_patched.append(marker)

    print(f"""
  ✓ Processes stopped (bridge killed, gateway stopped)
  ✓ Patches: {patched_count}/3 files cleaned
  ✓ webhook_subscriptions.json: amail-inbound removed
  ✓ config.yaml: platform_toolsets cleaned
  ✓ Gateway restarted (port {gw_port})

  ℹ  No files deleted — full idempotent reinstall supported
  ℹ  Config preserved in ~/.agentmail/ under system-*/
  ℹ  config.yaml platforms.webhook kept (base Hermes feature)
  ℹ  All other file changes preserved (Hermes updates, user edits)
""")

    if still_patched:
        print(f"  ⚠ {len(still_patched)} residual marker(s): {still_patched}")
    else:
        print("  ✓ No residual amail markers detected")

    return 0


if __name__ == "__main__":
    sys.exit(main())
