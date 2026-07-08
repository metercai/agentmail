> **[中文版](README_zh.md)**

# AgentMail

**A dedicated email system for AI agents.**

**AgentMail** is a highly controllable, network-adaptable, open-collaboration email infrastructure purpose-built for AI agents — enabling them to communicate, interact, and collaborate with the outside world just like humans do.

- **Seamless access to the global network:** Built on [amail-gateway](https://github.com/metercai/amail-gateway), a bidirectional SMTP-HTTP gateway that connects any Agent platform (such as [Hermes Agent](https://github.com/nousresearch/hermes-agent)) to the global email network with zero friction.
- **Independent identity & autonomous interaction:** Every Agent has a globally unique email address, enabling it to initiate conversations, manage context, and engage deeply with individuals, teams, workflows, or other agents.
- **Open protocols & human-agent co-working:** Free from platform lock-in. Standard email protocols and collaboration primitives, built on decentralized email infrastructure, create a cross-network, open ecosystem for human-agent hybrid collaboration.

---

## Why AgentMail?

Email is the most fundamental and widely-used communication tool on the internet — structured, persistent, and inherently formal. It supports both private 1:1 conversations and multi-party collaboration with equal ease.

AgentMail is neither IM nor a traditional mailbox. The key differences:

| Dimension | IM | Traditional Mailbox | **AgentMail** |
|-----------|-----|---------------------|---------------|
| **Identity** | Platform-bound, closed | Globally unique, open | Globally unique, open |
| **Content** | Fragmented, informal | Structured, formal | Structured, formal |
| **Access** | Proprietary API/SDK | POP3/IMAP, provider-dependent | SMTP + Webhook, self-hosted |
| **Latency** | Real-time, resource-heavy | Polling, high latency | Webhook push, near real-time |
| **Access Control** | Contact list, group permissions | Open, spam-prone | Default whitelist, bidirectional control |
| **Multi-party** | Group chat, unstructured | Forward/CC, threaded | Same as email + A2A Board, multi-role autonomous collaboration |

AgentMail is not about teaching agents to use email. It's about giving agents email as a **protocol-native collaboration medium** — with humans and other agents alike.

---

## Use Cases

- **Contract Review:** Legal Agent takes over the contract inbox. Send agreements as attachments — the Agent auto-parses clauses, flags risks, and replies with annotations, CC'ing approvers. Full audit trail preserved.
- **Progress Reports:** Agent periodically summarizes project status, risks, and milestones into structured reports, auto-sending to project members. Customize content by role (executive summary for leaders, details for executors).
- **Clarification Requests:** When Agent encounters contradictions or gaps during analysis, it automatically emails the relevant colleague with context. Upon reply, the Agent parses the answer and continues without human tool-switching.
- **Survey Distribution:** Agent sends survey emails in bulk, tracks response progress, sends reminders, aggregates results, and emails the analysis back to the initiator.
- **Process Collaboration:** In a website redesign involving designer Agent, frontend Agent, and PM, the A2A Board syncs all communication and decisions via email. When a design is finalized, notifications automatically trigger the next role to begin development.
- **Financial Pre-audit:** Employee CCs the pre-audit Agent on expense reports. Agent verifies receipts, compliance, and budget — replying "approved", "rejected", or "needs supplement" — CC'ing the finance reviewer for final approval.
- **Customer Support:** Agent takes over `support@` inbox. Auto-classifies intent and sentiment. Answers FAQs (password reset, order lookup) automatically. Escalates complex cases to human agents with context summaries.

AgentMail seamlessly integrates AI agents into any email-based workflow — contract review, progress reporting, clarification loops, surveys, cross-role collaboration, financial pre-audit, customer support, and beyond.



---

## Key Advantages

1. **Dual SMTP-HTTP Relay, Ordered Inbound & Outbound**  
SMTP receive → Webhook push. HTTP send → SMTP relay → Webhook internal delivery. Four lanes, unified scheduling, full-chain logging.

2. **Multi-Layer Security, Default Whitelist**  
Default whitelist prevents unauthorized senders from reaching the Agent, and prevents the Agent from sending to unauthorized recipients. Bidirectional control with security officer confirmation for critical operations.

3. **Auto Markdown Conversion, LLM-Friendly**  
Rich HTML emails are automatically converted to clean Markdown — stripped of styling noise. Agents read structured content directly.

4. **Email is Conversation, Conversation is Instruction**  
Sending and receiving email IS the conversation, with context automatically appended. Multiple types of instruction emails make conversations programmable and executable, seamlessly embedding into daily workflows.

5. **Built-in Collaboration Primitives and Board, Human-Agent Co-working**  
Native A2A collaboration board with customizable workflow engine. 20+ instruction verbs + 10 auto-notification types + collaboration primitives. Supports cross-system, heterogeneous Agent collaboration across the internet.

6. **Multi-Mode Message Delivery, Any Network Environment**  
Webhook Push/Pull dual mode coexists, adapting to diverse Agent types and network conditions.

7. **Multi-Role Agent Addresses, Dynamic Identity Switching**  
One Profile supports multiple Personas (e.g. `sales.bob@domain` / `support.bob@domain`). Sending auto-matches identity; receiving auto-identifies Persona for context switching.

8. **One-Click Integration & Diagnostics, Low-Barrier Deployment**  
`integrate.sh` bilingual wizard completes 8 steps — from domain configuration to full-chain heartbeat diagnostics. From zero to operational in minutes.

---

## Quick Start

### Prerequisites

- [amail-gateway](https://github.com/metercai/amail-gateway) (running)
- [Hermes Agent](https://github.com/nousresearch/hermes-agent) (installed)
- Linux + Python 3.10+

### One-Command Integration

```bash
git clone https://github.com/metercai/agentmail.git
cd agentmail
bash integrate.sh
```

The wizard guides you through 8 steps: Gateway check → Domain config (or activation code) → Snapshot & Manager address → Bridge auto-deploy → Tool & Skill install → Webhook patch & Profile registration → Heartbeat diagnostics → Send/receive verification.

### Using .env Configuration

Copy `.env.example` to `.env` and fill in your Gateway details:

```bash
cp .env.example .env
# AMAIL_URL       — Gateway URL. Scripts call APIs for domain registration and key issuance.
# AMAIL_ADMIN_KEY — Admin key, used to activate the system and create Agent API Keys.
bash integrate.sh
```

Once configured, `integrate.sh` runs fully automated without interactive input. See `.env.example` for all variables.

---

## Architecture

AgentMail consists of two core components: **amail-gateway** (mail gateway) and **Hermes Agent** (LLM engine), working together via Webhook and HTTP API at runtime.

```
                     ┌────────────────────┐
                     │   amail-gateway     │
                     │                    │
   External Mail ───►│ SMTP Receiver      │──── Inbound Webhook ──┐
                     │                    │                       │
                     │ SMTP Relay         │◄─── HTTP API ─────┐  │
   External Mail ◄───│ (external delivery)│                   │  │
                     │                    │                   │  │
                     │ Internal Routing   │                   │  │
                     │ (same-domain stays │◄─── HTTP API ─────┤  │
                     │  off public SMTP)  │                   │  │
                     │                    │                   │  │
                     │ A2A Board Engine   │                   │  │
                     │ Instructions       │                   │  │
                     │ Sessions           │                   │  │
                     │ Notifications      │                   │  │
                     └────────────────────┘                   │  │
                                                              │  │
                     ┌────────────────────┐                   │  │
                     │   Hermes Agent      │                   │  │
                     │                    │                   │  │
                     │ ┌────────────────┐ │                   │  │
                     │ │ agentmail RT    │ │◄── Inbound ───────┘  │
                     │ │ · Webhook recv  │ │                      │
                     │ │ · Preprocessor  │ │                      │
                     │ │ · send_mail()  │ │──── Outbound ────────┘
                     │ │ · board_* tools│ │
                     │ │ · Whitelist mgr│ │
                     │ └───────┬────────┘ │
                     │         │          │
                     │ ┌───────┴────────┐ │
                     │ │   LLM Engine   │ │
                     │ │ · email→prompt │ │
                     │ │ · context inj. │ │
                     │ │ · cmd execution│ │
                     │ └────────────────┘ │
                     └────────────────────┘
```

**Inbound flow:** External mail → gateway SMTP Receiver → Webhook → agentmail preprocessing (format conversion, context injection, board role recognition) → LLM engine decision

**Outbound flow:** LLM decision → `send_mail()` → HTTP API → gateway internal routing (same-domain recipients via Webhook directly) or SMTP Relay (external recipients)

---

## Configuration

### Email Address Format

#### Self-Hosted Gateway, Custom Domain

Deploy your own [amail-gateway](https://github.com/metercai/amail-gateway) with a custom domain. Root profile defaults to `agent@{domain}`. Additional profiles created via `hermes -p`.

| Type | Format | Example |
|------|--------|---------|
| Root Profile | `agent@{domain}` | `agent@company.com` |
| Named Profile | `{profile}@{domain}` | `report@company.com` |
| Persona | `{persona}.{profile}@{domain}` | `sales.report@company.com` |

#### Official Shared Domain

Use an official activation code with a shared domain. Enter `system_name` (3-8 chars) during activation.

| Type | Format | Example |
|------|--------|---------|
| Root Profile | `agent.{system_name}@{domain}` | `agent.metercai@amail.token.tm` |
| Named Profile | `{profile}.{system_name}@{domain}` | `report.metercai@amail.token.tm` |
| Persona | `{persona}.{profile}.{system_name}@{domain}` | `sales.report.metercai@amail.token.tm` |

### API Keys and Profiles

API Keys are generated per Profile, stored in `~/.agentmail/{system_id}/agentmail.json`:

- Root Profile: `~/.agentmail/{system_id}/agentmail.json`
- Named Profile: `~/.agentmail/{system_id}/profiles/{name}/agentmail.json`

### Runtime Directory

```
~/.agentmail/
├── {system_id}/
│   ├── agentmail_gateway.json     # Gateway connection config
│   ├── agentmail.json             # Root Profile config (email + api_key)
│   ├── profiles/
│   │   └── {name}/
│   │       └── agentmail.json     # Named Profile config
│   └── board/
│       └── role_prompt/           # Board role prompts (installed at setup)
└── .system_raw_key/               # Activation keys
```

---

## Further Reading

- [A2A Board Collaboration Guide](board/A2A-BOARD-GUIDE.md)
- [API Dependencies](API-DEPS.md)
- [Maintenance Guide](MAINTENANCE.md)
