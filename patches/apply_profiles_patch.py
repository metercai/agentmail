#!/usr/bin/env python3
"""Apply amail profile hooks patch to Hermes hermes_cli/profiles.py.

Adds trigger_profile_hooks() calls for profile_created and profile_deleted
events, enabling automatic amail address registration and API key cleanup.

Usage: python3 apply_profiles_patch.py <path/to/profiles.py>
"""
import sys
import re

target = sys.argv[1]
with open(target) as f:
    content = f.read()

patched = False

# ── Patch 1: profile creation hook ────────────────────────────
if "trigger_profile_hooks" not in content:
    hook_created = '''
    # ── Fire integration hooks (AmailGateway) ──
    try:
        from tools.amail_tools import trigger_profile_hooks
        trigger_profile_hooks("profile_created", canon, str(profile_dir))
    except ImportError:
        pass  # AmailGateway tools not installed
'''
    inserted = False
    # Match the line that logs "Profile ... created"
    created_pattern = re.compile(r'^.*(?:Profile.*created|created.*[Pp]rofile).*$', re.MULTILINE)
    for m in created_pattern.finditer(content):
        # Also check next line contains "logger" for confirmation
        line_end = content.find('\n', m.end()) if m.end() < len(content) else len(content)
        content = content[:line_end+1] + hook_created + content[line_end+1:]
        inserted = True
        patched = True
        break

    if not inserted:
        print("WARNING: could not find insertion point for profile_created hook", file=sys.stderr)

# ── Patch 2: profile deletion hook ────────────────────────────
if "trigger_profile_hooks(\"profile_deleted\"" not in content:
    hook_deleted = '''
    # ── Fire integration hooks (AmailGateway) ──
    try:
        from tools.amail_tools import trigger_profile_hooks
        trigger_profile_hooks("profile_deleted", canon, str(profile_dir))
    except ImportError:
        pass  # AmailGateway tools not installed
'''
    inserted = False
    # Match shutil.rmtree with profile_dir context
    rmtree_pattern = re.compile(r'^.*shutil\.rmtree\(.*profile_dir.*\).*$', re.MULTILINE)
    for m in rmtree_pattern.finditer(content):
        line_end = content.find('\n', m.end()) if m.end() < len(content) else len(content)
        content = content[:line_end+1] + hook_deleted + content[line_end+1:]
        inserted = True
        patched = True
        break

    if not inserted:
        # Fallback: match "Profile deleted" log line
        deleted_pattern = re.compile(r'^.*[Pp]rofile.*deleted.*$', re.MULTILINE)
        for m in deleted_pattern.finditer(content):
            line_end = content.find('\n', m.end()) if m.end() < len(content) else len(content)
            content = content[:line_end+1] + hook_deleted + content[line_end+1:]
            inserted = True
            patched = True
            break

    if not inserted:
        print("WARNING: could not find insertion point for profile_deleted hook", file=sys.stderr)

if patched:
    with open(target, "w") as f:
        f.write(content)
    print("OK")
else:
    print("ALREADY PATCHED")
