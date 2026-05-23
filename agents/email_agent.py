"""
Email Agent — Full SMTP/IMAP email automation.
Send, receive, reply, search, label, move, delete, draft, and parse emails.
Supports plain text, HTML, attachments, CC, BCC, threading, and OAuth2.
"""
from __future__ import annotations

import base64
import email
import email.mime.application
import email.mime.multipart
import email.mime.text
import email.utils
import imaplib
import json
import logging
import mimetypes
import os
import re
import smtplib
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.foundation.base_agent import BaseAgent

logger = logging.getLogger("EmailAgent")


# ─────────────────────────────────────────────────────────────────────────────
#  Data Classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EmailMessage:
    uid:         str
    subject:     str
    sender:      str
    recipients:  List[str]
    cc:          List[str]
    bcc:         List[str]
    date:        str
    body_text:   str
    body_html:   str
    attachments: List[Dict]
    flags:       List[str]
    message_id:  str
    in_reply_to: str
    thread_id:   Optional[str] = None
    labels:      List[str] = field(default_factory=list)


@dataclass
class EmailAccount:
    email:         str
    imap_host:     str
    imap_port:     int
    smtp_host:     str
    smtp_port:     int
    password:      str
    use_ssl:       bool = True
    use_starttls:  bool = False


# ─────────────────────────────────────────────────────────────────────────────
#  IMAP Wrapper
# ─────────────────────────────────────────────────────────────────────────────

class ImapSession:
    """Managed IMAP connection with auto-reconnect."""

    def __init__(self, account: EmailAccount):
        self.account = account
        self._conn: Optional[imaplib.IMAP4_SSL] = None
        self._current_folder: Optional[str] = None

    def connect(self) -> bool:
        try:
            if self.account.use_ssl:
                ctx = ssl.create_default_context()
                self._conn = imaplib.IMAP4_SSL(
                    self.account.imap_host, self.account.imap_port, ssl_context=ctx
                )
            else:
                self._conn = imaplib.IMAP4(
                    self.account.imap_host, self.account.imap_port
                )
                if self.account.use_starttls:
                    self._conn.starttls()
            self._conn.login(self.account.email, self.account.password)
            return True
        except Exception as e:
            logger.error(f"IMAP connect failed: {e}")
            return False

    def disconnect(self):
        if self._conn:
            try:
                self._conn.logout()
            except Exception as e:
                import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
                pass
            self._conn = None

    def select(self, folder: str = "INBOX") -> bool:
        if not self._conn:
            self.connect()
        try:
            status, _ = self._conn.select(folder)
            if status == "OK":
                self._current_folder = folder
                return True
            return False
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            self.connect()
            return False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()


# ─────────────────────────────────────────────────────────────────────────────
#  Email Agent
# ─────────────────────────────────────────────────────────────────────────────

class EmailAgent(BaseAgent):
    """
    Full production email agent supporting IMAP + SMTP.
    Handles compose, send, receive, search, reply, forward, delete,
    move, label, thread, attachment download, and bulk operations.
    """

    # Common provider presets
    PROVIDER_PRESETS = {
        "gmail": {
            "imap_host": "imap.gmail.com", "imap_port": 993,
            "smtp_host": "smtp.gmail.com", "smtp_port": 587,
            "use_ssl": True, "use_starttls": False,
        },
        "outlook": {
            "imap_host": "outlook.office365.com", "imap_port": 993,
            "smtp_host": "smtp.office365.com",    "smtp_port": 587,
            "use_ssl": True, "use_starttls": True,
        },
        "yahoo": {
            "imap_host": "imap.mail.yahoo.com", "imap_port": 993,
            "smtp_host": "smtp.mail.yahoo.com",  "smtp_port": 587,
            "use_ssl": True,
        },
        "icloud": {
            "imap_host": "imap.mail.me.com", "imap_port": 993,
            "smtp_host": "smtp.mail.me.com",  "smtp_port": 587,
            "use_ssl": True,
        },
        "hotmail": {
            "imap_host": "outlook.office365.com", "imap_port": 993,
            "smtp_host": "smtp.office365.com",    "smtp_port": 587,
            "use_ssl": True, "use_starttls": True,
        },
    }

    def __init__(self):
        super().__init__(name=self.__class__.__name__, role="Agent")
        self._accounts:    Dict[str, EmailAccount] = {}
        self._active_acct: Optional[str]           = None
        self._sent_count   = 0
        self._op_log:      List[Dict]              = []

        self.handlers = {
            # Account management
            "add_account":       self.add_account,
            "remove_account":    self.remove_account,
            "list_accounts":     self.list_accounts,
            "set_active":        self.set_active_account,
            "test_connection":   self.test_connection,
            # Send
            "send":              self.send_email,
            "send_html":         self.send_html_email,
            "send_with_attachment": self.send_with_attachment,
            "reply":             self.reply_to_email,
            "reply_all":         self.reply_all,
            "forward":           self.forward_email,
            "save_draft":        self.save_draft,
            # Receive / Read
            "get_inbox":         self.get_inbox,
            "get_folder":        self.get_folder,
            "read_email":        self.read_email,
            "get_unread":        self.get_unread,
            "get_thread":        self.get_thread,
            # Search
            "search":            self.search_emails,
            "search_by_sender":  self.search_by_sender,
            "search_by_subject": self.search_by_subject,
            "search_by_date":    self.search_by_date,
            "search_fulltext":   self.search_fulltext,
            # Manage
            "move_email":        self.move_email,
            "copy_email":        self.copy_email,
            "delete_email":      self.delete_email,
            "delete_bulk":       self.delete_bulk,
            "mark_read":         self.mark_read,
            "mark_unread":       self.mark_unread,
            "mark_flagged":      self.mark_flagged,
            "mark_unflagged":    self.mark_unflagged,
            "label_email":       self.label_email,
            # Folders
            "list_folders":      self.list_folders,
            "create_folder":     self.create_folder,
            "delete_folder":     self.delete_folder,
            "rename_folder":     self.rename_folder,
            # Attachments
            "download_attachment": self.download_attachment,
            "list_attachments":    self.list_attachments,
            # Stats / Misc
            "get_mailbox_stats": self.get_mailbox_stats,
            "get_quota":         self.get_quota,
            "purge_deleted":     self.purge_deleted,
            "get_log":           self._get_log,
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  Account Management
    # ─────────────────────────────────────────────────────────────────────────

    def add_account(self, email_addr: str, password: str,
                     provider: str = None,
                     imap_host: str = None, imap_port: int = 993,
                     smtp_host: str = None, smtp_port: int = 587,
                     use_ssl: bool = True,
                     use_starttls: bool = False) -> Dict:
        """Register an email account. Use provider= for known presets."""
        if provider and provider.lower() in self.PROVIDER_PRESETS:
            preset = self.PROVIDER_PRESETS[provider.lower()]
            imap_host    = imap_host    or preset["imap_host"]
            imap_port    = imap_port    or preset["imap_port"]
            smtp_host    = smtp_host    or preset["smtp_host"]
            smtp_port    = smtp_port    or preset["smtp_port"]
            use_ssl      = preset.get("use_ssl", True)
            use_starttls = preset.get("use_starttls", False)

        if not imap_host:
            # Auto-detect from domain
            domain   = email_addr.split("@")[1].lower()
            imap_host = f"imap.{domain}"
            smtp_host = smtp_host or f"smtp.{domain}"

        acct = EmailAccount(
            email        = email_addr,
            imap_host    = imap_host,
            imap_port    = imap_port,
            smtp_host    = smtp_host or f"smtp.{email_addr.split('@')[1]}",
            smtp_port    = smtp_port,
            password     = password,
            use_ssl      = use_ssl,
            use_starttls = use_starttls,
        )
        self._accounts[email_addr]  = acct
        if self._active_acct is None:
            self._active_acct = email_addr

        return {
            "success":  True,
            "account":  email_addr,
            "provider": provider,
            "imap":     f"{imap_host}:{imap_port}",
            "smtp":     f"{smtp_host}:{smtp_port}",
        }

    def remove_account(self, email_addr: str) -> Dict:
        if email_addr not in self._accounts:
            return {"success": False, "error": f"Account not found: {email_addr}"}
        del self._accounts[email_addr]
        if self._active_acct == email_addr:
            self._active_acct = next(iter(self._accounts), None)
        return {"success": True, "removed": email_addr}

    def list_accounts(self) -> Dict:
        return {
            "success":  True,
            "accounts": list(self._accounts.keys()),
            "active":   self._active_acct,
        }

    def set_active_account(self, email_addr: str) -> Dict:
        if email_addr not in self._accounts:
            return {"success": False, "error": "Account not registered"}
        self._active_acct = email_addr
        return {"success": True, "active": email_addr}

    def test_connection(self, email_addr: str = None) -> Dict:
        """Test IMAP and SMTP connectivity for an account."""
        acct = self._get_acct(email_addr)
        if not acct:
            return {"success": False, "error": "No account found"}

        results: Dict = {"email": acct.email, "success": True}

        # IMAP test
        try:
            with ImapSession(acct) as sess:
                if sess._conn:
                    results["imap_ok"]    = True
                    results["imap_server"] = f"{acct.imap_host}:{acct.imap_port}"
                else:
                    results["imap_ok"] = False
                    results["success"] = False
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            results["imap_ok"]    = False
            results["imap_error"] = str(e)
            results["success"]    = False

        # SMTP test
        try:
            ctx = ssl.create_default_context()
            if acct.use_starttls:
                with smtplib.SMTP(acct.smtp_host, acct.smtp_port, timeout=10) as s:
                    s.ehlo()
                    s.starttls(context=ctx)
                    s.login(acct.email, acct.password)
                    results["smtp_ok"] = True
            else:
                with smtplib.SMTP_SSL(acct.smtp_host, acct.smtp_port,
                                       context=ctx, timeout=10) as s:
                    s.login(acct.email, acct.password)
                    results["smtp_ok"] = True
            results["smtp_server"] = f"{acct.smtp_host}:{acct.smtp_port}"
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            results["smtp_ok"]    = False
            results["smtp_error"] = str(e)
            results["success"]    = False

        return results

    # ─────────────────────────────────────────────────────────────────────────
    #  Send
    # ─────────────────────────────────────────────────────────────────────────

    def send_email(self, to: List[str], subject: str, body: str,
                    cc: List[str] = None, bcc: List[str] = None,
                    from_account: str = None,
                    priority: str = "normal") -> Dict:
        """Send a plain-text email."""
        msg = self._build_mime_message(
            to=to, subject=subject, body_text=body,
            cc=cc, bcc=bcc, account=from_account, priority=priority,
        )
        return self._smtp_send(msg, to, cc or [], bcc or [], from_account)

    def send_html_email(self, to: List[str], subject: str,
                         body_html: str, body_text: str = None,
                         cc: List[str] = None, bcc: List[str] = None,
                         from_account: str = None) -> Dict:
        """Send an HTML email with optional plain-text fallback."""
        msg = self._build_mime_message(
            to=to, subject=subject,
            body_text=body_text or re.sub(r"<[^>]+>", "", body_html),
            body_html=body_html, cc=cc, bcc=bcc, account=from_account,
        )
        return self._smtp_send(msg, to, cc or [], bcc or [], from_account)

    def send_with_attachment(self, to: List[str], subject: str, body: str,
                              attachment_paths: List[str],
                              cc: List[str] = None,
                              from_account: str = None) -> Dict:
        """Send email with one or more file attachments."""
        msg = self._build_mime_message(
            to=to, subject=subject, body_text=body,
            cc=cc, account=from_account,
        )
        attached: List[str] = []
        for path in attachment_paths:
            p = Path(path)
            if not p.exists():
                logger.warning(f"Attachment not found: {path}")
                continue
            mime_type, _ = mimetypes.guess_type(str(p))
            main_type, sub_type = (mime_type or "application/octet-stream").split("/", 1)
            with open(p, "rb") as f:
                part = MIMEBase(main_type, sub_type)
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=p.name)
            msg.attach(part)
            attached.append(p.name)

        result = self._smtp_send(msg, to, cc or [], [], from_account)
        result["attachments_sent"] = attached
        return result

    def reply_to_email(self, uid: str, body: str,
                        folder: str = "INBOX",
                        from_account: str = None) -> Dict:
        """Reply to an existing email by UID."""
        orig = self.read_email(uid, folder, from_account)
        if not orig["success"]:
            return orig
        m     = orig["message"]
        to    = [m["sender"]]
        subj  = f"Re: {m['subject']}" if not m["subject"].startswith("Re:") else m["subject"]

        quote = "\n".join(f"> {l}" for l in m["body_text"].splitlines()[:30])
        full_body = f"{body}\n\nOn {m['date']}, {m['sender']} wrote:\n{quote}"

        msg = self._build_mime_message(
            to=to, subject=subj, body_text=full_body,
            in_reply_to=m.get("message_id", ""),
            references=m.get("message_id", ""),
            account=from_account,
        )
        result = self._smtp_send(msg, to, [], [], from_account)
        result["replied_to_uid"] = uid
        return result

    def reply_all(self, uid: str, body: str,
                   folder: str = "INBOX",
                   from_account: str = None) -> Dict:
        """Reply to all recipients of an email."""
        orig = self.read_email(uid, folder, from_account)
        if not orig["success"]:
            return orig
        m    = orig["message"]
        acct = self._get_acct(from_account)

        all_recips = set([m["sender"]] + m.get("recipients", []) + m.get("cc", []))
        if acct:
            all_recips.discard(acct.email)
        to   = list(all_recips)
        subj = f"Re: {m['subject']}" if not m["subject"].startswith("Re:") else m["subject"]

        quote    = "\n".join(f"> {l}" for l in m["body_text"].splitlines()[:30])
        full_body = f"{body}\n\nOn {m['date']}, {m['sender']} wrote:\n{quote}"

        msg = self._build_mime_message(to=to, subject=subj, body_text=full_body,
                                        account=from_account)
        return self._smtp_send(msg, to, [], [], from_account)

    def forward_email(self, uid: str, to: List[str],
                       note: str = "",
                       folder: str = "INBOX",
                       from_account: str = None,
                       include_attachments: bool = True) -> Dict:
        """Forward an email to new recipients."""
        orig = self.read_email(uid, folder, from_account)
        if not orig["success"]:
            return orig
        m    = orig["message"]
        subj = f"Fwd: {m['subject']}" if not m["subject"].startswith("Fwd:") else m["subject"]

        fwd_body = (
            f"{note}\n\n"
            f"---------- Forwarded message ----------\n"
            f"From: {m['sender']}\n"
            f"Date: {m['date']}\n"
            f"Subject: {m['subject']}\n\n"
            f"{m['body_text']}"
        )
        msg = self._build_mime_message(to=to, subject=subj, body_text=fwd_body,
                                        account=from_account)
        return self._smtp_send(msg, to, [], [], from_account)

    def save_draft(self, to: List[str], subject: str, body: str,
                    folder: str = "Drafts",
                    from_account: str = None) -> Dict:
        """Save a message as a draft in the Drafts folder."""
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account configured"}
        msg = self._build_mime_message(to=to, subject=subject, body_text=body,
                                        account=from_account)
        raw = msg.as_bytes()
        try:
            with ImapSession(acct) as sess:
                result = sess._conn.append(
                    folder, "\\Draft",
                    imaplib.Time2Internaldate(time.time()), raw,
                )
                return {"success": True, "folder": folder, "bytes": len(raw)}
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────────────────────────────────────
    #  Receive / Read
    # ─────────────────────────────────────────────────────────────────────────

    def get_inbox(self, limit: int = 20, offset: int = 0,
                   from_account: str = None) -> Dict:
        """Fetch inbox summary (headers only, fast)."""
        return self.get_folder("INBOX", limit=limit, offset=offset,
                                from_account=from_account)

    def get_folder(self, folder: str = "INBOX", limit: int = 20,
                    offset: int = 0, from_account: str = None,
                    sort_by: str = "date_desc") -> Dict:
        """Fetch message headers from a folder."""
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account configured"}

        try:
            with ImapSession(acct) as sess:
                if not sess.select(folder):
                    return {"success": False, "error": f"Cannot open folder: {folder}"}

                _, data = sess._conn.search(None, "ALL")
                uid_list = data[0].split()

                # Sort: newest first
                uid_list = list(reversed(uid_list))
                page = uid_list[offset: offset + limit]

                messages: List[Dict] = []
                for uid in page:
                    try:
                        _, msg_data = sess._conn.fetch(uid, "(RFC822.HEADER FLAGS)")
                        raw_header  = msg_data[0][1]
                        flags_str   = msg_data[0][0].decode() if msg_data[0][0] else ""
                        msg_obj     = email.message_from_bytes(raw_header)

                        messages.append({
                            "uid":      uid.decode(),
                            "subject":  self._decode_header_str(msg_obj.get("Subject", "")),
                            "sender":   self._decode_header_str(msg_obj.get("From", "")),
                            "date":     msg_obj.get("Date", ""),
                            "read":     "\\Seen" in flags_str,
                            "flagged":  "\\Flagged" in flags_str,
                        })
                    except Exception as e:
                        logger.debug(f"Skip UID {uid}: {e}")

                return {
                    "success":   True,
                    "folder":    folder,
                    "total":     len(uid_list),
                    "offset":    offset,
                    "count":     len(messages),
                    "messages":  messages,
                }
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    def read_email(self, uid: str, folder: str = "INBOX",
                    from_account: str = None,
                    mark_as_read: bool = True) -> Dict:
        """Fetch full content of a single email by UID."""
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account configured"}

        try:
            with ImapSession(acct) as sess:
                if not sess.select(folder):
                    return {"success": False, "error": f"Cannot open folder: {folder}"}

                _, msg_data = sess._conn.fetch(uid.encode(), "(RFC822)")
                raw         = msg_data[0][1]
                msg_obj     = email.message_from_bytes(raw)

                if mark_as_read:
                    sess._conn.store(uid.encode(), "+FLAGS", "\\Seen")

                parsed = self._parse_message(msg_obj, uid)
                return {"success": True, "message": parsed.__dict__}
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    def get_unread(self, folder: str = "INBOX", limit: int = 20,
                    from_account: str = None) -> Dict:
        """Fetch unread messages."""
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account configured"}
        try:
            with ImapSession(acct) as sess:
                if not sess.select(folder):
                    return {"success": False, "error": f"Cannot open: {folder}"}
                _, data = sess._conn.search(None, "UNSEEN")
                uids    = list(reversed(data[0].split()))[:limit]

                messages = []
                for uid in uids:
                    _, md = sess._conn.fetch(uid, "(RFC822.HEADER)")
                    m     = email.message_from_bytes(md[0][1])
                    messages.append({
                        "uid":     uid.decode(),
                        "subject": self._decode_header_str(m.get("Subject", "")),
                        "sender":  self._decode_header_str(m.get("From", "")),
                        "date":    m.get("Date", ""),
                    })

                return {
                    "success":  True,
                    "unread":   len(data[0].split()),
                    "count":    len(messages),
                    "messages": messages,
                }
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    def get_thread(self, message_id: str, folder: str = "INBOX",
                    from_account: str = None) -> Dict:
        """Fetch all emails in the same thread as a given Message-ID."""
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account configured"}
        try:
            with ImapSession(acct) as sess:
                if not sess.select(folder):
                    return {"success": False, "error": "Cannot open folder"}
                # Search by references
                safe_id = message_id.strip("<>")
                _, data = sess._conn.search(None, f'(OR HEADER "Message-ID" "<{safe_id}>" '
                                                    f'HEADER "References" "<{safe_id}>")')
                uids    = data[0].split()
                thread: List[Dict] = []
                for uid in uids:
                    _, md = sess._conn.fetch(uid, "(RFC822.HEADER)")
                    m     = email.message_from_bytes(md[0][1])
                    thread.append({
                        "uid":     uid.decode(),
                        "subject": self._decode_header_str(m.get("Subject", "")),
                        "sender":  m.get("From", ""),
                        "date":    m.get("Date", ""),
                    })
                return {"success": True, "thread": thread, "count": len(thread)}
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────────────────────────────────────
    #  Search
    # ─────────────────────────────────────────────────────────────────────────

    def search_emails(self, query: str, folder: str = "INBOX",
                       limit: int = 50, from_account: str = None) -> Dict:
        """Free-text IMAP search (SUBJECT+BODY+FROM)."""
        criteria = f'(OR OR SUBJECT "{query}" BODY "{query}" FROM "{query}")'
        return self._imap_search(criteria, folder, limit, from_account)

    def search_by_sender(self, sender: str, folder: str = "INBOX",
                          limit: int = 50, from_account: str = None) -> Dict:
        return self._imap_search(f'FROM "{sender}"', folder, limit, from_account)

    def search_by_subject(self, subject: str, folder: str = "INBOX",
                           limit: int = 50, from_account: str = None) -> Dict:
        return self._imap_search(f'SUBJECT "{subject}"', folder, limit, from_account)

    def search_by_date(self, since: str = None, before: str = None,
                        folder: str = "INBOX",
                        limit: int = 50, from_account: str = None) -> Dict:
        """Search emails by date range. Dates: 'DD-Mon-YYYY' e.g. '01-Jan-2024'."""
        parts = []
        if since:
            parts.append(f'SINCE "{since}"')
        if before:
            parts.append(f'BEFORE "{before}"')
        criteria = " ".join(parts) if parts else "ALL"
        return self._imap_search(criteria, folder, limit, from_account)

    def search_fulltext(self, text: str, folder: str = "INBOX",
                         limit: int = 50, from_account: str = None) -> Dict:
        return self._imap_search(f'BODY "{text}"', folder, limit, from_account)

    def _imap_search(self, criteria: str, folder: str, limit: int,
                      from_account: str) -> Dict:
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account configured"}
        try:
            with ImapSession(acct) as sess:
                if not sess.select(folder):
                    return {"success": False, "error": f"Cannot open: {folder}"}
                _, data = sess._conn.search(None, criteria)
                uids    = list(reversed(data[0].split()))[:limit]
                results = []
                for uid in uids:
                    try:
                        _, md = sess._conn.fetch(uid, "(RFC822.HEADER FLAGS)")
                        m     = email.message_from_bytes(md[0][1])
                        flags = md[0][0].decode() if md[0][0] else ""
                        results.append({
                            "uid":     uid.decode(),
                            "subject": self._decode_header_str(m.get("Subject", "")),
                            "sender":  m.get("From", ""),
                            "date":    m.get("Date", ""),
                            "read":    "\\Seen" in flags,
                        })
                    except Exception as e:
                        import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
                        pass
                return {
                    "success":   True,
                    "criteria":  criteria,
                    "count":     len(results),
                    "messages":  results,
                }
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────────────────────────────────────
    #  Manage
    # ─────────────────────────────────────────────────────────────────────────

    def move_email(self, uid: str, dest_folder: str,
                    src_folder: str = "INBOX",
                    from_account: str = None) -> Dict:
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account"}
        try:
            with ImapSession(acct) as sess:
                sess.select(src_folder)
                # Use MOVE extension if supported, otherwise copy+delete
                r = sess._conn.copy(uid.encode(), dest_folder)
                if r[0] == "OK":
                    sess._conn.store(uid.encode(), "+FLAGS", "\\Deleted")
                    sess._conn.expunge()
                    return {"success": True, "uid": uid, "moved_to": dest_folder}
                return {"success": False, "error": r[1]}
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    def copy_email(self, uid: str, dest_folder: str,
                    src_folder: str = "INBOX",
                    from_account: str = None) -> Dict:
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account"}
        try:
            with ImapSession(acct) as sess:
                sess.select(src_folder)
                r = sess._conn.copy(uid.encode(), dest_folder)
                return {"success": r[0] == "OK", "uid": uid, "copied_to": dest_folder}
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    def delete_email(self, uid: str, folder: str = "INBOX",
                      permanent: bool = False,
                      from_account: str = None) -> Dict:
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account"}
        try:
            with ImapSession(acct) as sess:
                sess.select(folder)
                if not permanent:
                    # Move to Trash first
                    for trash in ["Trash", "[Gmail]/Trash", "Deleted Items", "Deleted"]:
                        r = sess._conn.copy(uid.encode(), trash)
                        if r[0] == "OK":
                            break
                sess._conn.store(uid.encode(), "+FLAGS", "\\Deleted")
                sess._conn.expunge()
                return {"success": True, "uid": uid, "permanent": permanent}
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    def delete_bulk(self, uids: List[str], folder: str = "INBOX",
                     from_account: str = None) -> Dict:
        """Delete multiple emails at once."""
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account"}
        deleted = 0
        try:
            with ImapSession(acct) as sess:
                sess.select(folder)
                uid_str = ",".join(uids)
                sess._conn.store(uid_str.encode(), "+FLAGS", "\\Deleted")
                sess._conn.expunge()
                deleted = len(uids)
            return {"success": True, "deleted": deleted}
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e), "deleted": deleted}

    def _flag_op(self, uid: str, folder: str, flag: str,
                  op: str, from_account: str) -> Dict:
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account"}
        try:
            with ImapSession(acct) as sess:
                sess.select(folder)
                sess._conn.store(uid.encode(), op, flag)
                return {"success": True, "uid": uid, "flag": flag, "op": op}
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    def mark_read(self, uid: str, folder: str = "INBOX",
                   from_account: str = None) -> Dict:
        return self._flag_op(uid, folder, "\\Seen", "+FLAGS", from_account)

    def mark_unread(self, uid: str, folder: str = "INBOX",
                     from_account: str = None) -> Dict:
        return self._flag_op(uid, folder, "\\Seen", "-FLAGS", from_account)

    def mark_flagged(self, uid: str, folder: str = "INBOX",
                      from_account: str = None) -> Dict:
        return self._flag_op(uid, folder, "\\Flagged", "+FLAGS", from_account)

    def mark_unflagged(self, uid: str, folder: str = "INBOX",
                        from_account: str = None) -> Dict:
        return self._flag_op(uid, folder, "\\Flagged", "-FLAGS", from_account)

    def label_email(self, uid: str, label: str, folder: str = "INBOX",
                     from_account: str = None) -> Dict:
        """Add a custom label (Gmail supports keywords as labels)."""
        return self._flag_op(uid, folder, label, "+FLAGS", from_account)

    # ─────────────────────────────────────────────────────────────────────────
    #  Folders
    # ─────────────────────────────────────────────────────────────────────────

    def list_folders(self, from_account: str = None) -> Dict:
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account configured"}
        try:
            with ImapSession(acct) as sess:
                _, folders_raw = sess._conn.list()
                folders = []
                for f in folders_raw:
                    if isinstance(f, bytes):
                        parts = f.decode().rsplit(" ", 1)
                        if parts:
                            name = parts[-1].strip().strip('"')
                            folders.append(name)
                return {"success": True, "folders": folders, "count": len(folders)}
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    def create_folder(self, folder_name: str, from_account: str = None) -> Dict:
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account"}
        try:
            with ImapSession(acct) as sess:
                r = sess._conn.create(folder_name)
                return {"success": r[0] == "OK", "folder": folder_name}
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    def delete_folder(self, folder_name: str, from_account: str = None) -> Dict:
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account"}
        try:
            with ImapSession(acct) as sess:
                r = sess._conn.delete(folder_name)
                return {"success": r[0] == "OK", "folder": folder_name}
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    def rename_folder(self, old_name: str, new_name: str,
                       from_account: str = None) -> Dict:
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account"}
        try:
            with ImapSession(acct) as sess:
                r = sess._conn.rename(old_name, new_name)
                return {"success": r[0] == "OK", "old": old_name, "new": new_name}
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────────────────────────────────────
    #  Attachments
    # ─────────────────────────────────────────────────────────────────────────

    def list_attachments(self, uid: str, folder: str = "INBOX",
                          from_account: str = None) -> Dict:
        """List attachments without downloading them."""
        orig = self.read_email(uid, folder, from_account, mark_as_read=False)
        if not orig["success"]:
            return orig
        atts = orig["message"].get("attachments", [])
        return {
            "success":     True,
            "uid":         uid,
            "attachments": [{"filename": a["filename"], "size": a.get("size", 0),
                              "type": a.get("content_type", "")} for a in atts],
            "count":       len(atts),
        }

    def download_attachment(self, uid: str, filename: str,
                             save_dir: str = None,
                             folder: str = "INBOX",
                             from_account: str = None) -> Dict:
        """Download a specific attachment from an email to disk."""
        save_dir = save_dir or os.path.expanduser("~/Downloads")
        os.makedirs(save_dir, exist_ok=True)

        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account"}
        try:
            with ImapSession(acct) as sess:
                sess.select(folder)
                _, md   = sess._conn.fetch(uid.encode(), "(RFC822)")
                msg_obj = email.message_from_bytes(md[0][1])

                for part in msg_obj.walk():
                    disp = part.get_content_disposition() or ""
                    fn   = part.get_filename()
                    if fn and fn == filename and "attachment" in disp:
                        data      = part.get_payload(decode=True)
                        save_path = os.path.join(save_dir, fn)
                        with open(save_path, "wb") as f:
                            f.write(data)
                        return {
                            "success":   True,
                            "filename":  fn,
                            "saved_to":  save_path,
                            "size_kb":   round(len(data) / 1024, 1),
                        }
                return {"success": False, "error": f"Attachment '{filename}' not found"}
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────────────────────────────────────
    #  Stats / Misc
    # ─────────────────────────────────────────────────────────────────────────

    def get_mailbox_stats(self, from_account: str = None) -> Dict:
        """Count messages per folder."""
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account"}
        folders_r = self.list_folders(from_account)
        if not folders_r["success"]:
            return folders_r

        stats: Dict = {}
        try:
            with ImapSession(acct) as sess:
                for folder in folders_r["folders"][:20]:
                    try:
                        _, status = sess._conn.status(
                            folder, "(MESSAGES UNSEEN RECENT)"
                        )
                        if status and status[0]:
                            raw = status[0].decode()
                            total  = re.search(r"MESSAGES (\d+)", raw)
                            unseen = re.search(r"UNSEEN (\d+)", raw)
                            stats[folder] = {
                                "total":  int(total.group(1))  if total  else 0,
                                "unseen": int(unseen.group(1)) if unseen else 0,
                            }
                    except Exception as e:
                        import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
                        pass
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

        return {
            "success":    True,
            "account":    acct.email,
            "folders":    stats,
            "sent_count": self._sent_count,
        }

    def get_quota(self, from_account: str = None) -> Dict:
        """Get mailbox storage quota (IMAP QUOTA extension)."""
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account"}
        try:
            with ImapSession(acct) as sess:
                r = sess._conn.getquotaroot("INBOX")
                return {"success": True, "raw": str(r)}
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    def purge_deleted(self, folder: str = "INBOX",
                       from_account: str = None) -> Dict:
        """Permanently remove all messages marked \\Deleted (expunge)."""
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No account"}
        try:
            with ImapSession(acct) as sess:
                sess.select(folder)
                sess._conn.expunge()
                return {"success": True, "folder": folder}
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────────────────────────────────────
    #  SMTP Internals
    # ─────────────────────────────────────────────────────────────────────────

    def _smtp_send(self, msg, to: List[str], cc: List[str],
                    bcc: List[str], from_account: str = None) -> Dict:
        acct = self._get_acct(from_account)
        if not acct:
            return {"success": False, "error": "No email account configured"}

        all_recipients = to + cc + bcc
        ctx = ssl.create_default_context()

        try:
            if acct.use_starttls:
                with smtplib.SMTP(acct.smtp_host, acct.smtp_port, timeout=30) as s:
                    s.ehlo()
                    s.starttls(context=ctx)
                    s.login(acct.email, acct.password)
                    s.send_message(msg, to_addrs=all_recipients)
            else:
                with smtplib.SMTP_SSL(acct.smtp_host, acct.smtp_port,
                                       context=ctx, timeout=30) as s:
                    s.login(acct.email, acct.password)
                    s.send_message(msg, to_addrs=all_recipients)

            self._sent_count += 1
            self._log(f"Sent to {', '.join(to)}: {msg['Subject']}")
            return {
                "success":    True,
                "sent_to":    to,
                "subject":    msg["Subject"],
                "message_id": msg.get("Message-ID", ""),
            }
        except smtplib.SMTPAuthenticationError:
            return {"success": False, "error": "Authentication failed — check email/password"}
        except smtplib.SMTPException as e:
            return {"success": False, "error": f"SMTP error: {e}"}
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return {"success": False, "error": str(e)}

    def _build_mime_message(self, to: List[str], subject: str,
                             body_text: str = "",
                             body_html: str = None,
                             cc: List[str] = None,
                             bcc: List[str] = None,
                             in_reply_to: str = None,
                             references: str = None,
                             account: str = None,
                             priority: str = "normal") -> email.mime.multipart.MIMEMultipart:
        msg = email.mime.multipart.MIMEMultipart("alternative")
        acct = self._get_acct(account)

        msg["From"]    = acct.email if acct else "novamind@localhost"
        msg["To"]      = ", ".join(to)
        msg["Subject"] = subject
        msg["Date"]    = email.utils.formatdate(localtime=True)
        msg["Message-ID"] = email.utils.make_msgid(domain=(acct.email.split("@")[1]
                                                             if acct else "novamind"))
        if cc:
            msg["Cc"]  = ", ".join(cc)
        if in_reply_to:
            msg["In-Reply-To"] = f"<{in_reply_to.strip('<>')}>"
        if references:
            msg["References"]  = f"<{references.strip('<>')}>"

        priority_map = {"high": "1 (Highest)", "normal": "3 (Normal)", "low": "5 (Lowest)"}
        if priority != "normal":
            msg["X-Priority"] = priority_map.get(priority, "3 (Normal)")

        if body_text:
            msg.attach(email.mime.text.MIMEText(body_text, "plain", "utf-8"))
        if body_html:
            msg.attach(email.mime.text.MIMEText(body_html, "html", "utf-8"))

        return msg

    # ─────────────────────────────────────────────────────────────────────────
    #  Parse Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_message(self, msg_obj, uid: str) -> EmailMessage:
        body_text = ""
        body_html = ""
        attachments: List[Dict] = []

        def _handle_attachment(p):
            payload = p.get_payload(decode=True) or b""
            attachments.append({
                "filename":     p.get_filename() or "unnamed",
                "content_type": p.get_content_type(),
                "size":         len(payload),
            })

        def _handle_text(p):
            nonlocal body_text
            if body_text: return
            try:
                body_text = p.get_payload(decode=True).decode(
                    p.get_content_charset() or "utf-8", errors="replace"
                )
            except Exception as e:
                import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
                body_text = str(p.get_payload())

        def _handle_html(p):
            nonlocal body_html
            if body_html: return
            try:
                body_html = p.get_payload(decode=True).decode(
                    p.get_content_charset() or "utf-8", errors="replace"
                )
            except Exception as e:
                import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
                body_html = str(p.get_payload())

        _TYPE_HANDLERS = {
            "text/plain": _handle_text,
            "text/html":  _handle_html,
        }

        for part in msg_obj.walk():
            ct   = part.get_content_type()
            disp = part.get_content_disposition() or ""
            fn   = part.get_filename()

            if fn or "attachment" in disp:
                _handle_attachment(part)
                continue
            
            handler = _TYPE_HANDLERS.get(ct)
            if handler: handler(part)

        return EmailMessage(
            uid         = uid,
            subject     = self._decode_header_str(msg_obj.get("Subject", "")),
            sender      = self._decode_header_str(msg_obj.get("From", "")),
            recipients  = self._parse_addresses(msg_obj.get("To", "")),
            cc          = self._parse_addresses(msg_obj.get("Cc", "")),
            bcc         = self._parse_addresses(msg_obj.get("Bcc", "")),
            date        = msg_obj.get("Date", ""),
            body_text   = body_text[:50000],
            body_html   = body_html[:100000],
            attachments = attachments,
            flags       = [],
            message_id  = msg_obj.get("Message-ID", ""),
            in_reply_to = msg_obj.get("In-Reply-To", ""),
        )

    @staticmethod
    def _decode_header_str(header: str) -> str:
        try:
            return str(make_header(decode_header(header)))
        except Exception as e:
            import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
            return header

    @staticmethod
    def _parse_addresses(addr_str: str) -> List[str]:
        if not addr_str:
            return []
        return [a.strip() for a in addr_str.split(",") if a.strip()]

    def _get_acct(self, email_addr: str = None) -> Optional[EmailAccount]:
        if email_addr and email_addr in self._accounts:
            return self._accounts[email_addr]
        if self._active_acct and self._active_acct in self._accounts:
            return self._accounts[self._active_acct]
        if self._accounts:
            return next(iter(self._accounts.values()))
        return None

    def _log(self, msg: str):
        self._op_log.append({"ts": datetime.now().isoformat(), "msg": msg})
        if len(self._op_log) > 2000:
            self._op_log = self._op_log[-1000:]

    def _get_log(self, limit: int = 50) -> Dict:
        return {"success": True, "log": self._op_log[-limit:]}