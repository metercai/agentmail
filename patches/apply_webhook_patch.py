#!/usr/bin/env python3
"""Apply amail preprocessor patch to Hermes gateway/platforms/webhook.py.

Adds:
  1. PREPROCESS_REGISTRY dict + register_preprocessor() function
  2. Preprocessor invocation in webhook handler (before prompt rendering)

Usage: python3 apply_webhook_patch.py <path/to/webhook.py>
"""
import sys, re

target = sys.argv[1]
with open(target) as f:
    content = f.read()

patched = False

# ── Patch 1: add Callable to typing import ────────────────────
m = re.search(r'(from typing import .+)', content)
if m and "Callable" not in m.group(1):
    content = content.replace(m.group(1), m.group(1) + ", Callable", 1)
    patched = True

# ── Patch 2: add PREPROCESS_REGISTRY after logger ─────────────
if "PREPROCESS_REGISTRY" not in content:
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
    content = content.replace(
        "logger = logging.getLogger(__name__)",
        "logger = logging.getLogger(__name__)" + registry
    )
    patched = True

# ── Patch 3: add preprocessor call in webhook handler ─────────
if "PREPROCESS_REGISTRY.get" not in content:
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
    if "# Format prompt from template" in content:
        content = content.replace(
            "# Format prompt from template",
            call_block + "        # Format prompt from template"
        )
        patched = True
    else:
        print("WARNING: could not find '# Format prompt from template' — patch 3 skipped", file=sys.stderr)

if patched:
    with open(target, "w") as f:
        f.write(content)
    print("OK")
else:
    print("ALREADY PATCHED")
