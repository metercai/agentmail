# Step 6: Install amail tools into Hermes
# ═══════════════════════════════════════════════════════════════
step_begin "$T_TOOLS"

TOOLSETS_PY="$HERMES_DIR/toolsets.py"
TOOLS_DST="$HERMES_DIR/tools/amail_tools.py"

if [ -f "$TOOLS_DST" ] && grep -q "send_mail" "$TOOLSETS_PY" 2>/dev/null; then
    step_ok "$T_TOOLS_SKIP"
else
    # Copy the tool file
    mkdir -p "$HERMES_DIR/tools"
    echo -n "  $T_TOOLS_COPY "
    if cp "$TOOLS_PY" "$TOOLS_DST" 2>/dev/null; then
        echo "$T_OK"
    else
        echo "$T_FAILED"
        step_fail "$T_TOOLS_FAIL"
    fi

    # Register in toolsets.py
    echo -n "  $T_TOOLS_REG "
    if [ -f "$TOOLSETS_PY" ]; then
        python3 << PYEOF
import re
path = "$TOOLSETS_PY"
with open(path) as f:
    content = f.read()

needs_write = False

# Add tool names to _HERMES_CORE_TOOLS if not present
tool_names = ["send_mail", "manage_contacts", "contact_profile", "set_contact_profile", "email_summary", "set_email_summary"]
for name in tool_names:
    if f'"$name"' not in content.strip():
        content = re.sub(r'(_HERMES_CORE_TOOLS\\s*=\\s*\\[)', r'\\1\\n    "' + name + '",', content, count=1)
        needs_write = True

# Add amail toolset to TOOLSETS if not present
if '"amail"' not in content:
    amail_block = '''    "amail": {
        "description": "Agent email tools: send, contacts, contact profiles, and thread summaries via amail",
        "tools": ["send_mail", "manage_contacts", "contact_profile", "set_contact_profile", "email_summary", "set_email_summary"],
        "includes": [],
    },'"'
    content = re.sub(r'(TOOLSETS\\s*=\\s*\\{)', r'\\1\\n' + amail_block, content, count=1)
    needs_write = True

if needs_write:
    with open(path, 'w') as f:
        f.write(content)
    print("updated")
else:
    print("nochange")
PYEOF
        echo "$T_OK"
    else
        echo "$T_FAILED"
        step_warn "$T_TOOLS_FAIL"
    fi
fi

# ── Install amail skill ─────────────────────────────────────────
SKILL_DIR="$HOME/.hermes/skills/amail"
SKILL_SRC="$SCRIPT_DIR/skill/SKILL.md"
mkdir -p "$SKILL_DIR"
if cp "$SKILL_SRC" "$SKILL_DIR/SKILL.md" 2>/dev/null; then
    step_ok "amail skill installed"
else
    step_warn "amail skill copy failed (missing $SKILL_SRC)"
fi

# ── Install skill for named profiles ────────────────────────────
PROFILES_DIR="$HOME/.hermes/profiles"
if [ -d "$PROFILES_DIR" ]; then
    for prof in "$PROFILES_DIR"/*/; do
        prof_name=$(basename "$prof")
        prof_skill_dir="$prof/skills/amail"
        if [ ! -f "$prof_skill_dir/SKILL.md" ]; then
            mkdir -p "$prof_skill_dir"
            cp "$SKILL_SRC" "$prof_skill_dir/SKILL.md" 2>/dev/null
        fi
    done
fi
