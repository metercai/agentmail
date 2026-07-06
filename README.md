> **[中文版](README_zh.md)**

# AgentMail

**A dedicated instant email system for AI agents — highly controllable, network-adaptable, and built for open collaboration.**

AgentMail connects AI agents to the global email network through [amail-gateway](https://github.com/metercai/amail-gateway), a purpose-built gateway that bridges SMTP and Webhook channels. Agent platforms (such as [Hermes Agent](https://github.com/nousresearch/hermes-agent)) integrate seamlessly, giving every agent a globally unique email address. Agents initiate and manage conversations autonomously — interacting with individuals, teams, workflows, or other agents — and naturally embed into daily operations. All participants follow standard email protocols and collaboration primitives, free from platform lock-in, leveraging decentralized email infrastructure for open, cross-network human-agent collaboration.

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

2. **Bidirectional Whitelist, Security by Default**  
Default whitelist prevents unauthorized senders from reaching the Agent, and prevents the Agent from sending to unauthorized recipients. Closed-loop security.

3. **Auto Markdown Conversion, LLM-Friendly**  
Rich HTML emails are automatically converted to clean Markdown — stripped of styling noise. Agents read structured content directly.

4. **Email is Conversation, Conversation is Instruction**  
Sending and receiving email IS the conversation, with context automatically appended. Instruction emails — whether `[A2A]` board commands, admin directives, or universal queries like `[WHOAMI]` — make conversations programmable and executable, seamlessly embedding into daily workflows.

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
- [amail-bridge](https://github.com/metercai/amail-bridge) (auto-deployed by script)
- Python 3.10+

### One-Command Integration

```bash
git clone https://github.com/metercai/agentmail.git
cd agentmail
bash integrate.sh
```

The wizard guides you through 8 steps: Gateway check → Domain config (or activation code) → Snapshot & Manager address → Bridge auto-deploy → Tool & Skill install → Webhook patch & Profile registration → Heartbeat diagnostics → Send/receive verification.

### Environment Variable Automation

```bash
export AMAIL_URL=https://amail.token.tm
export AMAIL_ADMIN_KEY=your_admin_key_here
bash integrate.sh
```

---

## Architecture

```
                         amail-gateway
                    (external SMTP gateway)
                            │
                     ┌──────┴──────┐
                     │             │
              ┌──────┴──────┐     SMTP
              │ amail-bridge│     (outbound)
              │ (pull/push) │
              └──────┬──────┘
                     │ POST /webhooks/agentmail-inbound
              ┌──────┴──────┐
              │ Hermes Agent│
              │  (webhook)  │
              └──────┬──────┘
                     │ LLM + send_mail()
                     │
              ┌──────┴──────┐
              │ amail-gateway│
              │ (outbound)  │
              └─────────────┘
```

---

## Configuration

All runtime config lives under `~/.agentmail/{system_id}/`. Legacy `~/.hermes/agentmail.json` is deprecated.

**API Keys belong to Profiles, email addresses to Personas:**

| Concept | Description |
|---------|-------------|
| **Profile** | A complete Agent identity config (API Key + email address list) |
| **Persona** | A sub-identity under a Profile (e.g. `support.bob@domain`); one Profile supports multiple |

---

## Further Reading

- [A2A Board Collaboration Guide](A2A-BOARD-GUIDE.md)
- [API Dependencies](API-DEPS.md)
- [Maintenance Guide](MAINTENANCE.md)
