#!/usr/bin/env python3
"""Apply amail preprocessor patch to Hermes gateway/platforms/webhook.py.

Adds:
  1. PREPROCESS_REGISTRY dict + register_preprocessor() function
  2. Preprocessor invocation in webhook handler (before prompt rendering)

Auto-detects Hermes commit version and adjusts insertion points accordingly.
See HERMES_PATCH_MAP.md for details.

Usage: python3 apply_webhook_patch.py <path/to/webhook.py>
"""
import sys
import re
import os
import subprocess

# ═══════════════════════════════════════════════════════════════
# Commit → anchor position mapping
#
# Each entry: (since_commit, {"typing": N, "logger": N, "prompt": N})
# "since_commit" means this entry applies when HEAD is an ancestor
# of or equal to since_commit. Ordered oldest → newest.
# ═══════════════════════════════════════════════════════════════

WEBHOOK_ANCHOR_MAP = [
    # (anchor commit, {typing_import_line, logger_line, prompt_anchor_line})
    ("898b6d7d5", {"typing": 37, "logger": 55, "prompt": 409}),
    ("60531889d", {"typing": 37, "logger": 55, "prompt": 410}),
    ("9c90b3a59", {"typing": 37, "logger": 55, "prompt": 425}),
    ("61ac11872", {"typing": 37, "logger": 55, "prompt": 436}),
    ("bbf02c322", {"typing": 39, "logger": 57, "prompt": 439}),
    ("15aa6884a", {"typing": 39, "logger": 57, "prompt": 451}),
    ("bd8e2ec1a", {"typing": 39, "logger": 57, "prompt": 460}),
    ("afc861550", {"typing": 40, "logger": 58, "prompt": 503}),
    ("f35abb122", {"typing": 40, "logger": 58, "prompt": 552}),
]

# ── Helpers ───────────────────────────────────────────────────

def _resolve_git_root(target_path: str) -> str:
    """Return the git root directory for the target file."""
    try:
        d = os.path.dirname(os.path.abspath(target_path))
        r = subprocess.run(
            ["git", "-C", d, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return os.path.dirname(os.path.abspath(target_path))


def _get_hermes_commit(git_root: str) -> str:
    """Return the short (12-char) HEAD commit hash."""
    try:
        r = subprocess.run(
            ["git", "-C", git_root, "rev-parse", "--short=12", "HEAD"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _is_ancestor(git_root: str, ancestor: str, commit: str) -> bool:
    """Return True if `ancestor` is an ancestor of `commit` (or equal)."""
    try:
        r = subprocess.run(
            ["git", "-C", git_root, "merge-base", "--is-ancestor", ancestor, commit],
            capture_output=True, text=True, timeout=5
        )
        return r.returncode == 0
    except Exception:
        return False


def _resolve_anchors(git_root: str, commit: str) -> dict:
    """Find the best anchor positions for a given Hermes commit."""
    anchors = {"typing": 40, "logger": 58, "prompt": 552}  # default (newest)
    if commit == "unknown":
        return anchors
    # Walk from newest to oldest, pick first match
    for since_commit, mapping in reversed(WEBHOOK_ANCHOR_MAP):
        if _is_ancestor(git_root, since_commit, commit):
            return mapping
    return anchors


def _auto_detect_anchors(lines: list) -> dict:
    """Auto-scan file for anchor positions by known string markers."""
    anchors = {}
    for i, line in enumerate(lines, 1):
        if "from typing import " in line and "typing" not in anchors:
            anchors["typing"] = i
        if "logger = logging.getLogger(__name__)" in line and "logger" not in anchors:
            anchors["logger"] = i
        if "# Format prompt from template" in line and "prompt" not in anchors:
            anchors["prompt"] = i
        if "# Non-blocking" in line and "non_blocking" not in anchors:
            anchors["non_blocking"] = i
    return anchors


# ── Main ──────────────────────────────────────────────────────

if len(sys.argv) < 2:
    print("Usage: python3 apply_webhook_patch.py <path/to/webhook.py>", file=sys.stderr)
    sys.exit(1)

target = sys.argv[1]
git_root = _resolve_git_root(target)
hermes_commit = _get_hermes_commit(git_root)
anchors = _resolve_anchors(git_root, hermes_commit)

print(f"Hermes commit: {hermes_commit}", file=sys.stderr)
print(f"Anchors: typing={anchors['typing']} logger={anchors['logger']} prompt={anchors['prompt']}", file=sys.stderr)

with open(target) as f:
    content = f.read()

lines = content.split('\n')
_original_lines = list(lines)  # snapshot for diagnosis
patched = False

# ── Patch 1: add Callable to typing import ────────────────────
m = re.search(r'(from typing import .+)', content)
if m and "Callable" not in m.group(1):
    content = content.replace(m.group(1), m.group(1) + ", Callable", 1)
    patched = True
    print("Patch 1: Callable added to import", file=sys.stderr)

# ── Patch 2: add PREPROCESS_REGISTRY after logger (always replace) ──
# Remove old instance if present
content = re.sub(
    r'# Preprocess Registry \u2014 allows tools modules to register payload\n'
    r'.*?PREPROCESS_REGISTRY\[name\] = fn\n+',
    '',
    content, count=1, flags=re.DOTALL
)
registry = """

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

# Insert after logger = logging.getLogger(__name__)
logger_marker = "logger = logging.getLogger(__name__)"
if logger_marker in content:
    content = content.replace(logger_marker, logger_marker + registry, 1)
    patched = True
    print("Patch 2: PREPROCESS_REGISTRY added/updated", file=sys.stderr)
else:
    print("WARNING: could not find logger marker — patch 2 skipped", file=sys.stderr)

# ── Patch 3: add preprocessor call in webhook handler (always replace) ──
# Remove old instance if present: from the comment marker to blank line before # Format prompt
old_start = '        # ── Preprocess payload (AmailGateway integration) ──────────'
old_end   = '                # Format prompt from template'
if old_start in content:
    before = content[:content.index(old_start)]
    after  = content[content.index(old_end):]
    content = before + after
call_block = '''
        # ── Preprocess payload (AmailGateway integration) ──────────
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

'''
# Insert before "# Format prompt from template"
target = "# Format prompt from template"
if target in content:
    content = content.replace(target, call_block + "        " + target, 1)
    patched = True
    print("Patch 3: preprocessor call added/updated", file=sys.stderr)
else:
    print("WARNING: could not find '# Format prompt from template' — patch 3 skipped", file=sys.stderr)

# ── Patch 4: ensure _log_ping_event helper (always replace) ────
# Remove old instance if present, then append latest
import re as _re4
content, _nr = _re4.subn(
    r'\n+def _log_ping_event\(.*?(?=\n(?:def |\Z))',
    '',
    content,
    count=0,
    flags=_re4.DOTALL
)
def _log_ping_event(dir_: str, ping_id: str, payload: dict, pong_status: str):
    """Append a JSON line to agentmail.log for ping-pong tracking."""
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
import inspect as _ins
content += "\n" + _ins.getsource(_log_ping_event)
patched = True
print("Patch 4: _log_ping_event added", file=sys.stderr)
# ── Patch 5: add ping-pong interception (end-to-end test, always replace) ──
# Remove old instance if present
content = re.sub(
    r'        # ── Ping-pong interception.*?pong_returned"\)\}\n+',
    '',
    content, count=1, flags=re.DOTALL
)
ping_block = '''
        # ── Ping-pong interception (end-to-end test) ────────────────
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

'''
# Insert before "# Non-blocking" comment
target_line = "# Non-blocking"
if target_line in content:
    content = content.replace(target_line, ping_block + "        " + target_line, 1)
    patched = True
    print("Patch 5: ping-pong interception added/updated", file=sys.stderr)
else:
    print("WARNING: could not find '# Non-blocking' — patch 5 skipped", file=sys.stderr)

if patched:
    with open(target, "w") as f:
        f.write(content)
    print("OK")
else:
    print("ALREADY PATCHED")

# ── Version diagnosis ─────────────────────────────────────────
# If commit is not in ANCHOR_MAP, auto-detect positions and
# suggest a new entry for the Hermes team to commit.
if hermes_commit != "unknown":
    _in_map = any(
        _is_ancestor(git_root, sc, hermes_commit)
        for sc, _ in WEBHOOK_ANCHOR_MAP
    )
    if not _in_map:
        detected = _auto_detect_anchors(_original_lines)
        print(file=sys.stderr)
        print(f"  ╔═══ NEW HERMES COMMIT: {hermes_commit}", file=sys.stderr)
        print(f"  ║ Not in WEBHOOK_ANCHOR_MAP — auto-detected:", file=sys.stderr)
        for k in ["typing", "logger", "prompt", "non_blocking"]:
            v = detected.get(k, "?")
            print(f"  ║   {k}: {v}", file=sys.stderr)
        print(f"  ║", file=sys.stderr)
        print(f"  ║ Suggested anchor entry:", file=sys.stderr)
        print(f'  ║   ("{hermes_commit}", {{"typing": {detected.get("typing","?")},'
              f' "logger": {detected.get("logger","?")},'
              f' "prompt": {detected.get("prompt","?")}}}),', file=sys.stderr)
        print(f"  ║ Add to WEBHOOK_ANCHOR_MAP and commit.", file=sys.stderr)
        print(f"  ╚═══", file=sys.stderr)
