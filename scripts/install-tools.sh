# Step 6: Install amail tools into Hermes
# ═══════════════════════════════════════════════════════════════
step_begin "$T_TOOLS"

TOOLSETS_PY="$HERMES_DIR/toolsets.py"
TOOLS_DST="$HERMES_DIR/tools/agentmail_tools.py"

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

if needs_write:
    with open(path, "w") as f:
        f.write(content)
PYEOF
        echo "$T_OK"
    else
        echo "$T_SKIP"
    fi
fi

# ── Install a2a_board role files ──
ROLE_SRC="$PROJECT_ROOT/board/role_prompt_en"
ROLE_DST="$HOME/.agentmail/a2a_board/skills/role"
mkdir -p "$ROLE_DST"
if [ -d "$ROLE_SRC" ]; then
    for f in "$ROLE_SRC"/*.md; do
        [ -f "$f" ] || continue
        fname=$(basename "$f")
        if [ ! -f "$ROLE_DST/$fname" ] || [ "$f" -nt "$ROLE_DST/$fname" ]; then
            cp "$f" "$ROLE_DST/$fname" 2>/dev/null
        fi
    done
fi

# Copy skill files to each Hermes profile
if [ -f "$HERMES_DIR/profiles.py" ]; then
    SKILL_SRC="$PROJECT_ROOT/skills"
    for prof_dir in "$HOME/.hermes/profiles"/*/; do
        [ -d "$prof_dir" ] || continue
        prof_skill_dir="$prof_dir/skills/agentmail"
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
