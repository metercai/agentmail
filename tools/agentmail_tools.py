"""agentmail_tools — Mail toolset: send_mail, contacts, email_summary."""
from __future__ import annotations
import json
import logging
import os
import re
import secrets
import hashlib
import threading
import time
from pathlib import Path
from typing import Optional, Callable, Dict, List, Any

from agentmail_base import _load_profile_config, _agentmail_system_dir


logger = logging.getLogger(__name__)
_TOOLSET = "agentmail"



    def __init__(self, gateway_url: str, api_key: str, timeout: int = 30):
        self.gateway_url = gateway_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[dict] = None,
        raw_body: Optional[bytes] = None,
        headers: Optional[dict] = None,
    ) -> dict:
        """"Make an HTTP request to the gateway API. Returns parsed JSON or error dict."""
        url = f"{self.gateway_url}{path}"
        req_headers = {"Accept": "application/json"}
        if self.api_key:
            req_headers["X-Api-Key"] = self.api_key
        if headers:
            req_headers.update(headers)

        data = None
        if raw_body is not None:
            data = raw_body
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")

        try:
            req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_body = resp.read().decode("utf-8")
                status = resp.status
                try:
                    parsed = json.loads(resp_body)
                    # Handle JSON arrays -- wrap into {"data": [...]}
                    if isinstance(parsed, list):
                        return {"status": status, "data": parsed}
                    # Don't let response body overwrite HTTP status
                    parsed.pop("status", None)
                    return {"status": status, **parsed}
                except json.JSONDecodeError:
                    return {"status": status, "body": resp_body}
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                err_body.pop("status", None)
            except Exception:
                err_body = {"error": str(e)}
            return {"status": e.code, "error": str(e), **err_body}
        except Exception as e:
            return {"status": 0, "error": str(e)}

    # ── Send API ────────────────────────────────────────────────

    def send_mail(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
        sender: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> dict:
        """POST /api/v1/send"""
        payload: Dict[str, Any] = {
            "to": to,
            "markdown": body,
        }
        if sender:
            payload["sender"] = sender
        if subject:
            payload["subject"] = subject
        if cc:
            payload["cc"] = cc
        if attachments:
            payload["attachments"] = attachments

        headers = {}
        if message_id:
            headers["Message-ID"] = message_id
        if in_reply_to:
            headers["In-Reply-To"] = in_reply_to
        if references:
            headers["References"] = references
        if headers:
            payload["headers"] = headers

        return self._request("POST", "/api/v1/send", body=payload)

    # ── Attachment API ──────────────────────────────────────────

    def upload_attachment(self, file_path: str) -> dict:
        """POST /api/v1/upload -- upload a file as an attachment."""
        path = Path(file_path)
        if not path.is_file():
            return {"status": 400, "error": f"File not found: {file_path}"}
        content = path.read_bytes()
        # Use multipart-like approach via raw bytes with content-type header
        boundary = "----HermesBoundary"
        body = (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
        return self._request(
            "POST",
            "/api/v1/upload",
            raw_body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    def download_attachment(self, attachment_id: str) -> Optional[bytes]:
        """GET /api/v1/attachments/{id} -- download attachment bytes."""
        url = f"{self.gateway_url}/api/v1/attachments/{attachment_id}"
        req = urllib.request.Request(
            url,
            headers={"X-Api-Key": self.api_key},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except Exception as e:
            logger.error("download_attachment(%s) failed: %s", attachment_id, e)
            return None

    # ── Whitelist API ───────────────────────────────────────────

    def add_whitelist(
        self, system_id: str, domain_addr: str, direction: str,
        value: str, description: Optional[str] = None
    ) -> dict:
        return self._request(
            "POST",
            "/api/v1/whitelists",
            body={
                "system_id": system_id,
                "domain_addr": domain_addr,
                "direction": direction,
                "value": value,
                "description": description,
            },
        )

    def check_whitelist_value(self, domain_addr: str, value: str, direction: str = "to") -> dict:
        """GET /api/v1/whitelists/check — check if a value is whitelisted.

        Returns {"in_contacts": True/False, "direction": "..."} — no info leakage
        beyond the single queried address.
        """
        result = self._request(
            "GET",
            f"/api/v1/whitelists/check?domain_addr={domain_addr}&value={value}&direction={direction}",
        )
        whitelisted = result.get("status") == 200 and result.get("whitelisted", False)
        entry_direction = result.get("direction", direction) if whitelisted else direction
        return {"in_contacts": whitelisted, "direction": entry_direction}

    def update_whitelist_by_value(self, domain_addr: str, value: str, direction: str) -> dict:
        """PUT /api/v1/whitelists?domain_addr=&value= — update direction by composite key.

        Unlike update_whitelist_entry which requires a DB entry_id, this uses
        the same composite-key lookup as delete_whitelist_by_value — no
        information leakage from listing all entries.
        """
        return self._request("PUT",
            f"/api/v1/whitelists?domain_addr={domain_addr}&value={value}",
            body={"direction": direction})

    def delete_whitelist_by_value(self, domain_addr: str, value: str) -> dict:
        """DELETE /api/v1/whitelists?domain_addr=&value= — delete by composite key."""
        return self._request("DELETE",
            f"/api/v1/whitelists?domain_addr={domain_addr}&value={value}")

    # ── Agent State API (per-agent KV store) ─────────────────────

    def agent_state_get(self, key: str) -> Optional[str]:
        """GET /api/v1/agent-state/:key - returns value string or None."""
        result = self._request("GET", f"/api/v1/agent-state/{key}")
        if result.get("status") == 200:
            return result.get("value")
        return None

    def agent_state_put(self, key: str, value: str) -> dict:
        """PUT /api/v1/agent-state/:key - upsert a value."""
        return self._request("PUT", f"/api/v1/agent-state/{key}", body={"value": value})

    # ── Semantic endpoints ──────────────────────────────

    def put_contact(self, address: str, profile: str) -> dict:
        """PUT /api/v1/contacts/:address — atomic write + name index + merge."""
        return self._request("PUT", f"/api/v1/contacts/{address}",
                             body={"profile": profile})

    def get_contact(self, address: str) -> Optional[dict]:
        """GET /api/v1/contacts/:address — returns {address, profile} or None."""
        result = self._request("GET", f"/api/v1/contacts/{address}")
        if result.get("status") == 200:
            return {"address": result.get("address"), "profile": result.get("profile")}
        return None

    def get_contacts_by_name(self, name: str) -> list:
        """GET /api/v1/contacts?name=... — returns [{"address":...,"profile":...}]."""
        result = self._request("GET", f"/api/v1/contacts?name={name}")
        if result.get("status") == 200:
            return result.get("results", [])
        return []

    def put_thread_summary(self, message_id: str, summary: str) -> dict:
        """PUT /api/v1/thread-summary/:message_id — resolve thread_id + write."""
        return self._request("PUT", f"/api/v1/thread-summary/{message_id}",
                             body={"summary": summary})

    def get_thread_summary(self, message_id: str) -> Optional[str]:
        """GET /api/v1/thread-summary/:message_id — resolve + read, returns summary str or None."""
        result = self._request("GET", f"/api/v1/thread-summary/{message_id}")
        if result.get("status") == 200:
            return result.get("summary")
        return None

    # ── Domain / API Key management ─────────────────────────────

    def list_system_domains(self, system_id: str) -> list:
        """GET /api/v1/admin/systems/:sid/domains — list domains for a system."""
        result = self._request("GET", f"/api/v1/admin/systems/{system_id}/domains")
        data = result.get("data", result) if isinstance(result, dict) else result
        return data if isinstance(data, list) else []

    def update_system_domain(self, domain_id: str, webhook_url: str = "",
                             webhook_secret: str = "") -> dict:
        """PUT /api/v1/admin/system-domains/:id — update webhook config."""
        body = {}
        if webhook_url:
            body["webhook_url"] = webhook_url
        if webhook_secret:
            body["webhook_secret"] = webhook_secret
        return self._request("PUT", f"/api/v1/admin/system-domains/{domain_id}", body=body)

    def get_api_key_by_email(self, email: str) -> dict:
        """GET /api/v1/admin/api-keys?email= — lookup API key by email."""
        result = self._request("GET", f"/api/v1/admin/api-keys?email={email}")
        entries = result.get("entries", result.get("data", []))
        if isinstance(entries, list) and entries:
            return entries[0]
        return {}

    def delete_api_key(self, key_id: int) -> dict:
        """DELETE /api/v1/admin/api-keys/:id — delete an API key."""
        return self._request("DELETE", f"/api/v1/admin/api-keys/{key_id}")

    def register_email(
        self,
        system_id: str,
        mx_domain: str,
        email: str,
        webhook_url: str,
        webhook_secret: str,
        manager_address: str = "",
        generate_code: bool = False,
    ) -> dict:
        """POST /api/v1/admin/systems/:sid/addresses — register an agent address.
        When generate_code=True, also creates an activation code in one call."""
        params = "?generate_code=true" if generate_code else ""
        result = self._request(
            "POST",
            f"/api/v1/admin/systems/{system_id}/addresses{params}",
            body={
                "id": f"addr-{email.replace('@', '-at-')}-{int(time.time())}",
                "email": email,
                "webhook_url": webhook_url,
                "webhook_secret": webhook_secret,
                "manager_address": manager_address,
            },
        )
        return result

    # ── System Activation ─────────────────────────────────────────

    def activate_system(self, code: str, **kwargs) -> dict:
        """POST /api/v1/activate-system -- Activate a system using a product code.

        No authentication required -- the activation code IS the credential.
        Extra kwargs (system_id, system_name, domain) are passed through
        as optional fields -- the server auto-generates any missing values.

        Args:
            code: The product activation code (e.g. "prod-xxxx-xxxx-...")

        Returns ``{"status": 200, "raw_key": "sk-...", "system_id": "...", ...}``
        """
        body = {"code": code}
        # Pass through any optional overrides
        for k in ("system_id", "system_name", "domain"):
            v = kwargs.get(k)
            if v:
                body[k] = v
        result = self._request("POST", "/api/v1/activate-system", body=body)
        raw_key = result.get("raw_key", "")
        if not raw_key:
            return {"success": False, "error": f"activation failed: {result}"}
        return {
            "success": True,
            "raw_key": raw_key,
            "system_id": result.get("system_id", ""),
            "system_name": result.get("system_name", ""),
            "domain": result.get("domain", ""),
        }

    # ── Address Activation (Agent side) ─────────────────────────

    def activate_address(self, code: str, email_address: str = "", scopes: Optional[list] = None) -> dict:
        """POST /api/v1/activate-address -- Agent activates an address code to get raw_key.

        No authentication required -- the address activation code IS the credential.

        Args:
            code: The address activation code (e.g. "addr-xxxx-xxxx-...")
            email_address: The email address to bind to the API key (required)
            scopes: Optional scope list (defaults to ["agent"])

        Returns ``{"status": 200, "raw_key": "sk-...", "api_key_id": N, ...}``
        """
        body = {"code": code, "email_address": email_address, "scopes": scopes or ["agent"]}


    tmp_path = subs_path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(subs, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_path.replace(subs_path)
    logger.info("[agentmail_gateway] %s webhook route: %s %s",
                "Updated" if existed else "Created", route_name, subs_path)
    return not existed



# ═══════════════════════════════════════════════════════════════
# Agent Tools
# ═══════════════════════════════════════════════════════════════

def send_mail(
    to: Union[str, List[str]],
    subject: str,
    body: str,
    cc: Optional[Union[str, List[str]]] = None,
    attachments: Optional[List[str]] = None,
    message_id: Optional[str] = None,
) -> dict:
    """Send an email via your agentmail address.

    Attachments (file paths) are automatically uploaded before sending.
    For replies, pass the original email's message_id -- the tool will
    automatically resolve In-Reply-To, References headers, and the
    sender persona (from the stored inbound message metadata).
    """
    # Normalize array args to comma/space-separated strings
    if isinstance(to, list):
        to = ", ".join(to)
    if isinstance(cc, list):
        cc = ", ".join(cc)

    config = _load_profile_config()
    if not config:
        return {"success": False, "error": "agentmail not configured for this profile"}

    # Auto-activate if profile has activation_code but no api_key yet
    if config.get("activation_code") and not config.get("api_key"):
        profile_dir = _resolve_profile_dir() or ""
        if profile_dir:
            _auto_activate_profile(profile_dir, config)
            config = _load_profile_config()
            if not config:
                return {"success": False, "error": "agentmail config lost after activation"}

    if not config.get("api_key"):
        return {"success": False, "error": "agentmail api_key not available (activation may have failed)"}

    # ── Guard: email must be configured ──────────────────────
    base_email = config.get("email", "")
    if not base_email:
        return {"success": False, "error": "agentmail email not configured for this profile — cannot send"}

    client = _GatewayClient(config["gateway_url"], config["api_key"])

    # ── Resolve message metadata once (avoids duplicate HTTP round-trip) ──
    msg_meta = _load_message_meta(message_id) if message_id else None

    # ── Resolve sender: persona from inbound metadata > current persona > base email ──
    sender = base_email
    if msg_meta:
        stored_persona = msg_meta.get("my_amail_addr", "")
        if stored_persona and "@" in stored_persona:
            sender = stored_persona
            logger.info("[agentmail] Reply detected — using persona sender: %s", sender)
    elif not message_id:
        # New email: auto-detect current persona from profile directory
        persona = _current_persona_name()
        if persona:
            local, domain = base_email.split("@", 1)
            sender = f"{local}.{persona}@{domain}"
            logger.info("[agentmail] New email from persona '%s' — sender: %s", persona, sender)

    # Parse recipients
    to_list = [a.strip() for a in to.split(",") if a.strip()]
    cc_list = [a.strip() for a in cc.split(",") if a.strip()] if cc else None

    # Detect forward vs reply from subject line (case-insensitive "fw:" prefix)
    _is_forward = bool(message_id and subject and subject.lower().startswith("fw:"))

    # Resolve threading headers from message_id
    in_reply_to = None
    references = None
    if message_id:
        if not _is_forward:
            in_reply_to = message_id
        if msg_meta:
            # Build References: original references + original message_id
            refs = msg_meta.get("references", [])
            if isinstance(refs, str):
                refs = [r.strip() for r in refs.split() if r.strip()]
            all_refs = refs + [message_id]
            # Deduplicate while preserving order
            seen = set()
            deduped = []
            for r in all_refs:
                if r not in seen:
                    seen.add(r)
                    deduped.append(r)
            references = " ".join(deduped)
        else:
            # No metadata -- just use message_id as the reference chain start
            references = message_id

    # Resolve and validate attachments
    resolved_paths, resolve_errors = _resolve_attachments(attachments) if attachments else ([], [])
    if resolve_errors:
        return {"success": False, "error": "Attachment resolution failed", "details": resolve_errors}

    # Size checks + upload
    upload_errors = []
    attachment_ids = []
    for path in resolved_paths:
        size_err = _check_attachment_size(path)
        if size_err:
            upload_errors.append(size_err)
            continue
        resp = client.upload_attachment(path)
        if resp.get("status") == 201:
            attachment_ids.append({"id": resp.get("attachment_id", resp.get("id", ""))})
        else:
            upload_errors.append(f"Upload failed for {Path(path).name}: {resp.get('error', 'HTTP ' + str(resp.get('status', '?')))}")

    if upload_errors and not attachment_ids:
        return {"success": False, "error": "All attachments failed", "details": upload_errors}

    result = client.send_mail(
        to=",".join(to_list),
        subject=subject,
        body=body,
        cc=",".join(cc_list) if cc_list else None,
        attachments=attachment_ids if attachment_ids else None,
        in_reply_to=in_reply_to,
        references=references,
        sender=sender,
        message_id=_build_message_id(config),
    )

    # Store outbound message metadata for future replies
    out_msg_id = result.get("message_id") or result.get("email_id") or ""
    if out_msg_id:
        _store_message_meta(out_msg_id, references=references)

    # Optionally save outbound email snapshot
    if out_msg_id and config.get("save_raw_snapshots"):
        _save_outbound_snapshot(out_msg_id, sender, sender, to, subject, body,
                                cc_list or [], attachment_ids or [],
                                in_reply_to or "", references or "")

    # Auto-bootstrap thread summary for new (non-reply) emails
    thread_bootstrapped = False
    if out_msg_id and not message_id:
        try:
            initial_summary = f"Subject: {subject}\nStatus: awaiting response"
            set_email_summary(out_msg_id, initial_summary)
            thread_bootstrapped = True
            logger.info("[agentmail] Thread summary bootstrapped for new email: %s", out_msg_id)
        except Exception as e:
            logger.warning("[agentmail] Failed to bootstrap thread summary: %s", e)

    # Flatten status into success/error
    status = result.pop("status", 0)
    if 200 <= status < 300:
        out = {"success": True, **result}
        if thread_bootstrapped:
            out["thread_bootstrapped"] = True
        if upload_errors:
            failed_names = [Path(e.split(":")[0] if ":" not in e else "").name or e for e in upload_errors]
            out["note"] = f"Sent, but {len(upload_errors)} attachment(s) had issues: {'; '.join(upload_errors[:3])}"
        return out
    else:
        error = result.get("error", result.get("detail", f"HTTP {status}"))
        return {"success": False, "error": f"Send failed: {error}"}


def manage_contacts(
    action: str,
    address: Optional[str] = None,
    direction: str = "all",
    **kwargs,
) -> dict:
    """Manage your address book (whitelist).

    Args:
        action: "check", "add", or "remove"
        address: email address to add/remove (required for add/remove)
        direction: "from" (default, inbound receive) or "to" (outbound send) or "all"
    """
    config = _load_profile_config()
    if not config:
        return {"success": False, "error": "agentmail not configured for this profile"}

    client = _GatewayClient(config["gateway_url"], config["api_key"])
    # Agent whitelist is per-profile, not per-domain.
    # domain_addr = agentmail address (agent-1@mail.project.com)
    email_addr = config.get("email", "")
    system_id = config.get("system_id", "")

    if action == "check":
        if not address:
            return {"success": False, "error": "address is required for check"}
        result = client.check_whitelist_value(email_addr, address, direction)
        return {
            "success": True,
            "in_contacts": result.get("in_contacts", False),
            "direction": result.get("direction", direction),
            "address": address,
        }

    elif action == "add":
        if not address:
            return {"success": False, "error": "address is required for add"}
        # Agent cannot directly add to whitelist.
        # Instead, send a request email to the manager for approval.
        # The manager replies with "add X to my contacts" which is processed
        # by webhook.rs handle_manager_commands.
        manager_addr = config.get("manager_address", "")
        if not manager_addr:
            return {"success": False, "error": "No manager_address configured — cannot send approval request"}
        client_mgr = _GatewayClient(config["gateway_url"], config["api_key"])
        description = kwargs.get("description", "") if kwargs else ""
        desc_line = f"\ndescription: {description}" if description else ""
        result = client_mgr.send_mail(
            to=manager_addr,
            subject=f"[Amail] Contact request: {address}",
            body=f"Please add {address} to {email_addr}'s contacts with direction={direction}.{desc_line}\n\n"
                 f"To approve, reply to this email with:\nadd {address} to my contacts with direction={direction}",
        )
        status = result.get("status", 0)
        if 200 <= status < 300:
            return {"success": True, "note": f"Approval request sent to manager ({manager_addr})"}
        error = result.get("error", f"HTTP {status}")
        return {"success": False, "error": f"Failed to send approval request: {error}"}

    elif action == "remove":
        if not address:
            return {"success": False, "error": "address is required for remove"}
        result = client.delete_whitelist_by_value(email_addr, address)
        status = result.pop("status", 0)
        if status == 204:
            return {"success": True}
        if status == 404:
            return {"success": False, "error": f"{address} not found in whitelist"}
        error = result.get("error", result.get("detail", f"HTTP {status}"))
        return {"success": False, "error": f"Failed to remove {address}: {error}"}

    elif action == "update":
        if not address:
            return {"success": False, "error": "address is required for update"}
        new_direction = kwargs.get("direction", direction)
        if not new_direction:
            return {"success": False, "error": "direction is required for update"}
        result = client.update_whitelist_by_value(email_addr, address, new_direction)
        status = result.pop("status", 0)
        if 200 <= status < 300:
            return {"success": True, "note": f"direction updated to {new_direction}"}
        error = result.get("error", result.get("detail", f"HTTP {status}"))
        return {"success": False, "error": f"Failed to update {address}: {error}"}


    else:
        return {"success": False, "error": f"Unknown action: {action}"}



# ── Contact profile (for context awareness) ──────────────────────

def contact_profile(address: str = "", name: str = "") -> dict:
    """Look up a contact profile by address or name.

    At least one of address or name must be provided.
    - address: exact lookup via GET /api/v1/contacts/:address
    - name: server-side search via GET /api/v1/contacts?name=
    """
    if not address and not name:
        return {"address": "", "profile": None, "error": "address or name required"}

    config = _load_profile_config()
    if not config:
        return {"address": address, "profile": None}
    client = _GatewayClient(config["gateway_url"], config["api_key"])

    # Search by address (exact match) — semantic endpoint
    if address:
        contact = client.get_contact(address)
        if contact:
            return {"address": address, "profile": contact.get("profile")}
        return {"address": address, "profile": None}

    # Search by name (server-side)
    results = client.get_contacts_by_name(name.strip())
    if not results:
        return {"address": "", "profile": None, "searched_name": name}
    if len(results) == 1:
        return {"address": results[0]["address"], "profile": results[0]["profile"]}
    return {"ambiguous": True, "candidates": [r["address"] for r in results]}



def set_contact_profile(address: str, profile: str) -> dict:
    """Store or update a contact profile. The gateway handles JSON merge,
    name extraction, and name index maintenance atomically.
    """
    config = _load_profile_config()
    if not config:


    except Exception:
        return

    profile_email = profile_config.get("email", "")
    if not profile_email:
        return

    # Find and delete the API key by email address
    client = _GatewayClient(gateway_url, admin_key)
    entries = client.list_api_keys()
    if isinstance(entries, list):
        for entry in entries:
            if entry.get("email_address") == profile_email:
                api_key_id = entry.get("id")
                if api_key_id:
                    client.delete_api_key(api_key_id)
                    logger.info("[agentmail_gateway] Deleted API key for %s (id=%s)", profile_email, api_key_id)
                break

    # Remove the centralized config files
    config_path.unlink(missing_ok=True)
    # Also clean up profiles sub-path if different from config_path
    if system_id and name != "default":
        alt = _agentmail_system_dir(system_id) / "profiles" / name / "agentmail.json"
        if alt.is_file() and str(alt) != str(config_path):
            alt.unlink(missing_ok=True)
    # Clean up .agentmail pointer
    pointer = Path(profile_dir) / ".agentmail"
    if pointer.is_file():
        pointer.unlink(missing_ok=True)


# Register the hooks explicitly (not via decorator to avoid ordering issues)
register_profile_hook("profile_created", _auto_register_email)
register_profile_hook("profile_deleted", _auto_deregister_email)


# ═══════════════════════════════════════════════════════════════
# Tool Registration (top-level -- auto-discovered by Hermes registry)
# Wrapped in try/except so setup() and preprocessor can be imported
# without the Hermes runtime (CLI / integration scripts).
# ═══════════════════════════════════════════════════════════════

try:
    from tools.registry import registry, tool_result  # noqa: E402
    _HERMES_REGISTRY_AVAILABLE = True
except ImportError:
    _HERMES_REGISTRY_AVAILABLE = False
    class _DummyRegistry:
        def register(self, **kw): pass
    registry = _DummyRegistry()  # type: ignore
    def tool_result(x): return x  # noqa: E743


def _handle_send_mail(args, **_kw):
    return tool_result(send_mail(
        to=args.get("to", ""),
        subject=args.get("subject", ""),
        body=args.get("body", ""),
        cc=args.get("cc"),
        attachments=args.get("attachments"),
        message_id=args.get("message_id"),
    ))


def _handle_manage_contacts(args, **_kw):
    return tool_result(manage_contacts(
        action=args.get("action", "check"),
        address=args.get("address"),
        direction=args.get("direction", "all"),
    ))


registry.register(
    name="send_mail",
    toolset=_TOOLSET,
    schema={
        "name": "send_mail",
        "description": (
            "Send an email via your agentmail address. "
            "Attachments are automatically uploaded from local file paths. "
            "For replies: pass the original inbound message_id -- the tool "
            "automatically resolves In-Reply-To, References headers, and sender persona."
            "For new emails: omit message_id; the tool will auto-create a new message_id."
            "After sending, you may call set_email_summary to refine the thread summary."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": (
                        "Comma-separated recipient email addresses. "
                        "When replying: include the inbound 'sender' "
                        "plus other 'recipients.to' addresses (excluding your own)."
                    ),
                },
                "subject": {
                    "type": "string",
                    "description": (
                        "Email subject line. "
                        "When replying: prefix the inbound subject with 'Re: '."
                    ),
                },
                "body": {
                    "type": "string",
                    "description": "Email body (plain text or markdown).",
                },
                "cc": {
                    "type": "string",
                    "description": (
                        "Optional comma-separated CC recipients. "
                        "When replying: use 'recipients.cc' from the inbound payload."
                    ),
                },
                "attachments": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional list of file paths to attach. "
                        "Accepts absolute paths, CWD-relative paths, or bare filenames. "
                        "Bare filenames are resolved by searching the workspace directory tree."
                    ),
                },
                "message_id": {
                    "type": "string",
                    "description": (
                        "For replies: pass the 'message_id' field from the inbound email payload. "
                        "The tool will automatically resolve threading headers "
                        "and the sender persona from stored message metadata. "
                        "Omit for new outbound emails."
                    ),
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    handler=_handle_send_mail,
)

registry.register(
    name="manage_contacts",
    toolset=_TOOLSET,
    schema={
        "name": "manage_contacts",
        "description": (
            "Manage your address book (contacts). "
            "Use 'check' to verify a contact, 'add' to allow a new sender, "
            "'remove' to revoke access."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["check", "add", "remove", "update"],
                    "description": "Action: check if a contact exists, add a new one (sends approval request), remove a contact, or update direction on existing contact.",
                },
                "address": {
                    "type": "string",
                    "description": "Email address to check, add, or remove (required for all actions).",
                },
                "direction": {
                    "type": "string",
                    "enum": ["from", "to", "all"],
                    "description": "Direction: 'from' (inbound, allow receiving), 'to' (outbound, allow sending), or 'all'.",
                },
            },
            "required": ["action", "address"],
        },
    },
    handler=_handle_manage_contacts,
)

# register contact_profile tool
def _handle_contact_profile(args, **_kw):
    return tool_result(contact_profile(
        address=args.get("address", ""),
        name=args.get("name", ""),
    ))

registry.register(
    name="contact_profile",
    toolset=_TOOLSET,
    schema={
        "name": "contact_profile",
        "description": (
            "Look up a contact by address or name. "
            "At least one required. Address is exact match; name searches for a "
            "matching 'name' field in stored profiles. "
            "Returns {address, profile} where the 'profile' value is a JSON string with keys: "
            "name (display name), title (job title), location (city/timezone), "
            "relationship (how they relate to you), focus (recurring topics/priorities), "
            "close_contacts (frequent CCs, semicolon-separated), "
            "style (communication preference). "
            "Returns '{}' if no profile stored."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "Email address for exact lookup.",
                },
                "name": {
                    "type": "string",
                    "description": "Contact name for search (case-insensitive substring match on the 'name' field in contact profiles).",
                },
            },
        },
    },
    handler=_handle_contact_profile,
)

# register set_contact_profile tool
def _handle_set_contact_profile(args, **_kw):
    return tool_result(set_contact_profile(


        address=args.get("address", ""),
        profile=args.get("profile", ""),
    ))

registry.register(
    name="set_contact_profile",
    toolset=_TOOLSET,
    schema={
        "name": "set_contact_profile",
        "description": (
            "Update the profile for an existing contact. "
            "Only updates contacts that already exist in your address book."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "Email address of the contact to update.",
                },
                "profile": {
                    "type": "string",
                    "description": (
                        "JSON-formatted string of profile fields to update. "
                        "Valid keys: name, title, location, relationship, focus, "
                        "close_contacts, style. "
                        "Prefix '+' to append, '-' to remove, no prefix to overwrite. "
                        "Unprefixed values inherit the prefix of the preceding value. "
                        "All values are strings; separate multiple values with semicolons. "
                        "Max 5 values per key. "
                        "Example: {\"location\": \"Beijing\", \"focus\": \"-Q3 planning; +Q4 planning\"}"
                    ),
                },
            },
            "required": ["address", "profile"],
        },
    },
    handler=_handle_set_contact_profile,
)

# ═══════════════════════════════════════════════════════════════
# Message Metadata — stored in gateway agent_state (internal), keyed msg:{message_id}
#    value: {"references": [...], "thread_id": "..."}
# ═══════════════════════════════════════════════════════════════

# Local-only helpers for raw email snapshots (not gateway data)


def _build_message_id(config: dict) -> str:
    """Generate a Message-ID header value from the configured domain."""
    import uuid as _uuid
    domain = config.get("domain", "") or "amail.local"
    return f"<{_uuid.uuid4().hex}@{domain}>"


def _sanitize_message_id(message_id: str) -> str:
    mid = message_id.strip().lstrip("<").rstrip(">")
    for ch in "/\\:*?\"<>|@ ":
        mid = mid.replace(ch, "_")
    return mid


# ── Attachment path resolution ─────────────────────────────────────

ATTACH_MAX_SIZE_MB = 10
ATTACH_MAX_SEARCH_DEPTH = 5    # max directory depth from workspace root
ATTACH_MAX_SEARCH_MATCHES = 50  # stop early if too many candidates
ATTACH_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv",
    ".hermes", "target", ".pytest_cache", ".mypy_cache",
    ".tox", ".eggs", "dist", "build", "__pypackages__",
}


def _resolve_attachments(raw_paths: list) -> tuple:
    """Resolve a list of attachment references to verified absolute paths.

    Resolution order for each item:
      1. Absolute path — verify it exists.
      2. CWD-relative — resolve, verify it exists.
      3. Bare filename — walk workspace looking for a unique match.
      4. No match / ambiguous → returned as error for the caller to surface.

    Returns (resolved: list[str], errors: list[str]).
    """
    import glob as _glob

    resolved: list[str] = []
    errors: list[str] = []

    cwd = Path.cwd()
    workspace_roots = _workspace_roots()

    for raw in raw_paths:
        raw = raw.strip()
        if not raw:
            continue

        p = Path(raw)

        # 1. Absolute path
        if p.is_absolute():
            if p.is_file():
                resolved.append(str(p))
            else:
                errors.append(f"Attachment not found: {raw}")
            continue

        # 2. CWD-relative
        cwd_candidate = (cwd / p).resolve()
        if cwd_candidate.is_file():
            resolved.append(str(cwd_candidate))
            continue

        # 3. Bare filename — search workspace trees
        name = p.name
        if not name:
            errors.append(f"Invalid attachment path: {raw}")
            continue

        matches: list[Path] = []
        for root in workspace_roots:
            if not root.is_dir():
                continue
            for candidate in root.rglob(name):
                # Depth guard — skip files nested too deep
                depth = len(candidate.relative_to(root).parts)
                if depth > ATTACH_MAX_SEARCH_DEPTH:
                    continue
                if _is_skipped_dir(candidate):
                    continue
                if candidate.name != name:
                    continue
                matches.append(candidate)
                # Early exit — avoid scanning the entire filesystem
                if len(matches) >= ATTACH_MAX_SEARCH_MATCHES:
                    break
            if len(matches) >= ATTACH_MAX_SEARCH_MATCHES:
                break

        # Deduplicate by resolved path
        unique = list(dict.fromkeys(str(m.resolve()) for m in matches))

        if len(unique) == 0:
            errors.append(
                f"Attachment '{name}' not found in workspace. "
                f"Provide an absolute or CWD-relative path."
            )
        elif len(unique) == 1:
            resolved.append(unique[0])
        else:
            # Multiple matches — need disambiguation
            candidates = "\n    ".join(unique[:5])
            errors.append(
                f"Ambiguous attachment '{name}' — found {len(unique)} files:\n"
                f"    {candidates}\n"
                f"  Use a more specific path."
            )

    return resolved, errors


def _workspace_roots() -> list[Path]:
    """Return the directories to search for bare-filename attachments."""
    roots: list[Path] = [Path.cwd()]

    # Profile directory (agent's working sandbox)
    profile_dir = _resolve_profile_dir() or ""
    if profile_dir:
        roots.append(Path(profile_dir))

    # Home — broad but last-resort; walk depth limited in practice
    home = Path.home()
    if home.is_dir():
        roots.append(home)

    return roots


def _is_skipped_dir(path: Path) -> bool:
    """True if any ancestor of *path* is a directory that should be skipped."""
    for parent in path.parents:
        if parent.name in ATTACH_SKIP_DIRS:
            return True
    return False


def _check_attachment_size(path: str) -> Optional[str]:
    """Return an error message if the file exceeds the size limit, else None."""
    try:
        size_mb = Path(path).stat().st_size / (1024 * 1024)
        if size_mb > ATTACH_MAX_SIZE_MB:
            return (
                f"Attachment '{Path(path).name}' is {size_mb:.1f} MB — "
                f"max allowed is {ATTACH_MAX_SIZE_MB} MB"
            )
    except OSError:
        pass
    return None


# ── Raw email snapshots ────────────────────────────────────────────

def _save_outbound_snapshot(out_msg_id: str, my_addr: str, sender: str,
                             to: str, subject: str, body: str,
                             cc_list: list, attachment_ids: list,
                             in_reply_to: str, references: str) -> None:
    """Save a JSON snapshot of an outbound email to raw_email/.

    my_addr determines the snapshot subdirectory (persona or base address).
    """
    safe_mid = _sanitize_message_id(out_msg_id)
    safe_addr = _sanitize_message_id(my_addr)
    now = datetime.now()
    yyyymm = now.strftime("%Y%m")
    snapshot_dir = _raw_email_dir() / yyyymm
    snapshot_path = snapshot_dir / f"out-{safe_mid}.json"
    payload = {
        "message_id": out_msg_id,
        "direction": "outbound",
        "sender": sender,
        "to": to,
        "cc": ", ".join(cc_list) if cc_list else "",
        "subject": subject,
        "body": body,
        "attachments": attachment_ids,
        "in_reply_to": in_reply_to,
        "references": references,
        "sent_at": now.isoformat(),
    }
    try:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        tmp = snapshot_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                       encoding="utf-8")
        tmp.replace(snapshot_path)
    except Exception:
        logger.warning("Failed to save outbound email snapshot for %s", safe_mid)


def _current_persona_name() -> Optional[str]:
    """Return the current persona name from the active Hermes profile directory.

    Returns None for the default (base) profile; otherwise the profile dir name
    (e.g. "alice" for ~/.hermes/profiles/alice).
    """
    profile_dir = _resolve_profile_dir() or ""
    if not profile_dir:
        return None
    p = Path(profile_dir).resolve()
    home_hermes = (Path.home() / ".hermes").resolve()
    if p == home_hermes:
        return None
    # Must be a subdirectory of ~/.hermes/profiles/ — extract the persona name
    profiles_dir = home_hermes / "profiles"
    try:
        p.relative_to(profiles_dir)
    except ValueError:
        return None
    name = p.name
    return name if name else None




def _agentmail_dir() -> Path:
    """Return the per-agent data directory (AGENTMAIL_HOME env or default)."""
    env = os.environ.get("AGENTMAIL_HOME", "")
    if env:
        return Path(env)
    # Try pointer file first
    pdir = _resolve_profile_dir() or ""
    if pdir:
        pointer = Path(pdir) / ".agentmail"
        if pointer.is_file():
            try:
                pd = json.loads(pointer.read_text())
                email = pd.get("email", "")
                if email:
                    ag_home = f"~/.agentmail/{email.replace('@', '_')}"
                    return Path(ag_home).expanduser()
            except Exception:
                pass
    # Fallback: use default directory
    return Path.home() / ".agentmail" / "default"


def _raw_email_dir() -> Path:
    """Return the directory for raw email snapshots (yyyymm subdir appended by caller)."""
    return _agentmail_dir()



def _log_amail(direction: str, from_addr: str, to_addr: str, subject: str) -> None:
    """Append a lightweight email processing log entry (not dependent on save_raw_snapshots).
    
    Log is written to {AGENTMAIL_HOME}/agentmail.log for integration test verification.
    """
    import json as _json
    log_path = _agentmail_dir() / "agentmail.log"
    entry = _json.dumps({
        "ts": datetime.now().isoformat(),
        "dir": direction,
        "from": from_addr,
        "to": to_addr,
        "subj": subject,
    }, ensure_ascii=False)
    try:
        with open(log_path, "a") as f:
            f.write(entry + "\n")
    except Exception:
        logger.debug("Failed to write agentmail log: %s", log_path)

def store_inbound_message(
    message_id: str,
    references: list,
    my_amail_addr: str,
    preprocessed_payload: Optional[dict] = None,
    attachment_sources: Optional[dict] = None,
) -> Optional[str]:
    """Called by the gateway preprocessor when an inbound email arrives.

    Optionally (save_raw_snapshots=true): saves the AGENT-VISIBLE JSON snapshot
    (AFTER preprocessing) to raw_email/{agent_addr}/{yyyymm}/.

    IMPORTANT: preprocessed_payload must be the output of preprocess_mail_payload()
    — the agent-visible format with sender/recipients/my_amail_addr/direct_message fields.
    Do NOT pass the gateway RAW webhook payload.
    """
    if not message_id or not message_id.strip():
        return None
    mid = message_id.strip()
    refs = [r.strip() for r in (references or []) if r.strip()]

    # Metadata is pre-populated by the Rust gateway before webhook delivery.
    # Only save local snapshot if configured.
    config = _load_profile_config()

    # ── Optionally save agent-visible snapshot ──────────────────
    if not config or not config.get("save_raw_snapshots"):
        return None

    safe_mid = _sanitize_message_id(mid)
    safe_addr = _sanitize_message_id(my_amail_addr)
    now = datetime.now()
    yyyymm = now.strftime("%Y%m")
    snapshot_dir = _raw_email_dir() / yyyymm
    snapshot_path = snapshot_dir / f"in-{safe_mid}.json"
    attch_dir = snapshot_dir / "attch" / safe_mid

    snapshot_saved = False
    if preprocessed_payload:
        # Guard: detect gateway RAW format (has 'mail_id' field — gateway-internal UUID)
        if "mail_id" in preprocessed_payload and "recipients" not in preprocessed_payload:
            logger.warning(
                "store_inbound_message received gateway RAW payload instead of preprocessed agent-visible JSON. "
                "Call preprocess_mail_payload() first. Snapshot may contain wrong format."
            )
        try:
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            tmp = snapshot_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(preprocessed_payload, ensure_ascii=False, indent=2, default=str),
                           encoding="utf-8")
            tmp.replace(snapshot_path)
            snapshot_saved = True
        except Exception:
            logger.warning("Failed to save inbound email snapshot for %s", safe_mid)

    if attachment_sources:
        try:


            attch_dir.mkdir(parents=True, exist_ok=True)
            for filename, src_path in (attachment_sources or {}).items():
                src = Path(src_path)
                if not src.is_file():
                    continue
                safe_name = Path(filename).name
                dst = attch_dir / safe_name
                dst.write_bytes(src.read_bytes())
        except Exception:
            logger.warning("Failed to copy attachments for %s", safe_mid)

    return str(snapshot_path) if snapshot_saved else None


def _load_message_meta(message_id: str) -> Optional[dict]:
    """Load message metadata from gateway agent_state. Returns None if not found."""
    config = _load_profile_config()
    if not config:
        return None
    client = _GatewayClient(config["gateway_url"], config["api_key"])
    value = client.agent_state_get(f"msg:{message_id.strip()}")
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _store_message_meta(message_id: str, references: Optional[str] = None) -> None:
    """Store outbound message metadata to gateway for future replies."""
    if not message_id or not message_id.strip():
        return
    mid = message_id.strip()
    refs = [r.strip() for r in (references or "").split() if r.strip()]
    thread_id = refs[0] if refs else mid
    msg_value = json.dumps({"references": refs, "thread_id": thread_id})
    config = _load_profile_config()
    if config:
        client = _GatewayClient(config["gateway_url"], config["api_key"])
        client.agent_state_put(f"msg:{mid}", msg_value)


# ═══════════════════════════════════════════════════════════════
# email_summary / set_email_summary — via semantic thread-summary endpoints
#    key: thread:{thread_id}, value: summary text
# ═══════════════════════════════════════════════════════════════

def email_summary(message_id: str) -> dict:
    """Look up the stored summary for the email thread containing this message.

    Uses semantic endpoint GET /admin/thread-summary/:message_id which
    resolves message_id → thread_id internally.
    """
    config = _load_profile_config()
    if not config:
        return {"thread_id": "", "summary": ""}
    client = _GatewayClient(config["gateway_url"], config["api_key"])
    result = client.get_thread_summary(message_id)
    if result:
        # get_thread_summary returns the summary string on success
        return {"thread_id": message_id, "summary": result}
    return {"thread_id": message_id, "summary": ""}


def set_email_summary(message_id: str, summary: str) -> dict:
    """Store or update the summary for the email thread containing this message.

    Resolves message_id → thread_id, then writes the summary to gateway
    agent_state keyed 'thread:{thread_id}'.
    """
    if not message_id or not message_id.strip():
        return {"success": False, "error_code": "MESSAGE_ID_REQUIRED"}
    if not isinstance(summary, str):
        return {"success": False, "error_code": "SUMMARY_MUST_BE_STRING"}
    if len(summary) > 2000:
        return {"success": False, "error_code": "SUMMARY_TOO_LONG", "max_length": 2000}

    config = _load_profile_config()
    if not config:
        return {"success": False, "error": "agentmail not configured for this profile"}
    client = _GatewayClient(config["gateway_url"], config["api_key"])

    result = client.put_thread_summary(message_id, summary)
    if result.get("status") == 200:
        return {"success": True}
    error = result.get("error", f"HTTP {result.get('status')}")
    return {"success": False, "error": f"Failed to store summary: {error}"}


# ── Registry: email_summary ─────────────────────────────────────

def _handle_email_summary(args, **_kw):
    return tool_result(email_summary(
        message_id=args.get("message_id", ""),
    ))

registry.register(
    name="email_summary",
    toolset=_TOOLSET,
    schema={
        "name": "email_summary",
        "description": (
            "Look up the stored summary for an email thread. "
            "Pass any message_id from the thread -- the tool resolves "
            "the canonical thread_id automatically. "
            "Returns {thread_id, summary}. "
            "The summary is a plain-text snapshot of active topics, decisions, "
            "pending actions, and unresolved questions. Empty string if none stored. "
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Any message_id from the thread whose summary to retrieve.",
                },
            },
            "required": ["message_id"],
        },
    },
    handler=_handle_email_summary,
    emoji="📧",
)

# ── Registry: set_email_summary ─────────────────────────────────

def _handle_set_email_summary(args, **_kw):
    return tool_result(set_email_summary(
        message_id=args.get("message_id", ""),
        summary=args.get("summary", ""),
    ))


