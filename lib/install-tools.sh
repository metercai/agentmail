# Step 6: Install amail tools into Hermes
# ═══════════════════════════════════════════════════════════════
step_begin "$T_TOOLS"

TOOLSETS_PY="$HERMES_DIR/toolsets.py"
TOOLS_DST="$HERMES_DIR/tools/amail_tools.py"

if [ -f "$TOOLS_DST" ] && grep -q "send_mail" "$TOOLSETS_PY" 2>/dev/null; then
    step_ok "$T_TOOLS_SKIP"
else
    # Copy the tool 
# Install amail skill (handles inbound email webhook payloads)
SKILL_DIR="$HOME/.hermes/skills/amail"
if [ ! -f "$SKILL_DIR/SKILL.md" ]; then
    mkdir -p "$SKILL_DIR"
    cat > "$SKILL_DIR/SKILL.md" << 'SKILLEOF'
---
description: Handle incoming amail webhook payloads — process emails and reply via SMTP
toolset: amail
---

You are processing an inbound email delivered via amail webhook.

The webhook payload contains:
- `from`: sender email
- `to`: recipient email (your agent address)
- `subject`: email subject
- `body`: plain text body
- `headers`: email headers
- `attachments`: list of attachment objects
- `mail_id`: unique email identifier

Process the email:
1. Read the body and determine the intent
2. For the welcome test email (from integration setup), reply with the current time
3. Use the `send_mail` tool to reply — set `to` to the sender's address, `subject` to "Re: " + original subject
SKILLEOF
    step_ok "amail skill installed"
fi

file
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
    if f'"{name}"' not in content.strip():
        content = re.sub(r'(_HERMES_CORE_TOOLS\\s*=\\s*\\[)', r'\\1\\n    "' + name + '",', content, count=1)
        needs_write = True

# Add amail toolset to TOOLSETS if not present
if '"amail"' not in content:
    amail_block = '''    "amail": {
        "description": "Agent email tools: send, contacts, contact profiles, and thread summaries via amail",
        "tools": ["send_mail", "manage_contacts", "contact_profile", "set_contact_profile", "email_summary", "set_email_summary"],
        "includes": [],
    },'''
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

# ═══════════════════════════════════════════════════════════════
