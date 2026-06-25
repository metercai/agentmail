# Step 6: Install amail tools into Hermes
# ═══════════════════════════════════════════════════════════════
step_begin "$T_TOOLS"

TOOLSETS_PY="$HERMES_DIR/toolsets.py"
TOOLS_DST="$HERMES_DIR/tools/amail_tools.py"

# Check if reinstall is needed: compare checksums
NEED_COPY=false
if [ ! -f "$TOOLS_DST" ]; then
    NEED_COPY=true
elif ! md5sum --quiet -c /dev/null 2>/dev/null; then
    # md5sum not available — fall back to mtime comparison
    [ "$TOOLS_PY" -nt "$TOOLS_DST" ] && NEED_COPY=true
else
    SRC_MD5=$(md5sum "$TOOLS_PY" 2>/dev/null | cut -d' ' -f1)
    DST_MD5=$(md5sum "$TOOLS_DST" 2>/dev/null | cut -d' ' -f1)
    [ "$SRC_MD5" != "$DST_MD5" ] && NEED_COPY=true
fi

if [ "$NEED_COPY" = false ] && grep -q "send_mail" "$TOOLSETS_PY" 2>/dev/null; then
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
    amail_block = '    "amail": {\n'
    amail_block += '        "description": "Agent email tools: send, contacts, contact profiles, and thread summaries via amail",\n'
    amail_block += '        "tools": ["send_mail", "manage_contacts", "contact_profile", "set_contact_profile", "email_summary", "set_email_summary"],\n'
    amail_block += '        "includes": [],\n'
    amail_block += '    },\n'
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
SKILL_SRC="$SCRIPT_DIR/skill/SKILL.md"
DESC_SRC="$SCRIPT_DIR/skill/DESCRIPTION.md"
SKILL_DIR="$HOME/.hermes/skills/amail"
mkdir -p "$SKILL_DIR"
for f_pair in "SKILL.md:SKILL_SRC" "DESCRIPTION.md:DESC_SRC"; do
    fname="${f_pair%%:*}"
    var="${f_pair##*:}"
    eval src="\$$var"
    dst="$SKILL_DIR/$fname"
    if [ ! -f "$src" ]; then
        step_warn "amail skill $fname copy failed (missing $src)"
        continue
    fi
    need_copy=false
    if [ ! -f "$dst" ]; then
        need_copy=true
    else
        src_md5=$(md5sum "$src" 2>/dev/null | cut -d' ' -f1)
        dst_md5=$(md5sum "$dst" 2>/dev/null | cut -d' ' -f1)
        [ "$src_md5" != "$dst_md5" ] && need_copy=true
    fi
    if [ "$need_copy" = true ]; then
        cp "$src" "$dst" 2>/dev/null
    fi
done
step_ok "amail skill installed"

# ── Install skill for named profiles ────────────────────────────
PROFILES_DIR="$HOME/.hermes/profiles"
if [ -d "$PROFILES_DIR" ]; then
    for prof in "$PROFILES_DIR"/*/; do
        prof_name=$(basename "$prof")
        prof_skill_dir="$prof/skills/amail"
        for f_pair in "SKILL.md:SKILL_SRC" "DESCRIPTION.md:DESC_SRC"; do
            fname="${f_pair%%:*}"
            var="${f_pair##*:}"
            eval src="\$$var"
            dst="$prof_skill_dir/$fname"
            need_copy=false
            if [ ! -f "$dst" ]; then
                need_copy=true
            else
                src_md5=$(md5sum "$src" 2>/dev/null | cut -d' ' -f1)
                dst_md5=$(md5sum "$dst" 2>/dev/null | cut -d' ' -f1)
                [ "$src_md5" != "$dst_md5" ] && need_copy=true
            fi
            if [ "$need_copy" = true ]; then
                mkdir -p "$prof_skill_dir"
                cp "$src" "$dst" 2>/dev/null
            fi
        done
    done
fi
