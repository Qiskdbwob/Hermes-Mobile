"""Mobile Memory Provider - SQLite-based with encryption support"""

import base64
import hashlib
import json
import logging
import os
import platform
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

# Memory Harness v1: memory classes and their default TTL. A None TTL means the
# memory never expires on its own. Candidate/pending entries are short-lived by
# design (they must be confirmed or dropped).
MEMORY_TYPES = ("user_profile", "stable_fact", "learned_pattern", "episodic")
MEMORY_STATUSES = (
    "candidate",
    "pending_confirmation",
    "active",
    "superseded",
    "expired",
    "rejected",
)
MEMORY_TTL_DAYS: Dict[str, Optional[int]] = {
    "user_profile": None,
    "stable_fact": None,
    "learned_pattern": 90,
    "episodic": 30,
    "candidate": 7,
    "pending_confirmation": 14,
}

# Bounded-decrypt window for session search: how many recent messages per
# candidate session get decrypted and scanned (see docs/memory-harness-v2-gap.md).
_SEARCH_WINDOW = 25


class MobileMemoryProvider:
    """SQLite-based memory provider for mobile with optional encryption"""

    def __init__(
        self,
        db_path: Path,
        encrypt: bool = True,
        encryption_key: Optional[str] = None,
    ):
        self.db_path = Path(db_path)
        self.encrypt = encrypt
        self._conn: Optional[sqlite3.Connection] = None
        self._fernet: Optional[Fernet] = None
        self._legacy_fernet: Optional[Fernet] = None

        if encrypt:
            self._init_encryption(encryption_key)

        self._init_db()

    @staticmethod
    def _derive_fernet_key(secret: str) -> bytes:
        """Derive a Fernet key for explicit secrets and legacy migrations."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"hermes_mobile_salt",
            iterations=100000,
        )
        return base64.urlsafe_b64encode(kdf.derive(secret.encode()))

    def _load_or_create_device_key(self) -> bytes:
        """Return a stable random key stored inside the app's private data sandbox."""
        key_path = self.db_path.with_suffix(f"{self.db_path.suffix}.key")
        key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            key = key_path.read_bytes().strip()
            Fernet(key)  # validate before trusting persisted bytes
            return key
        except FileNotFoundError:
            pass
        except (ValueError, TypeError):
            logger.error("Invalid memory key file at %s; preserving it for recovery", key_path)
            key_path.replace(key_path.with_suffix(f"{key_path.suffix}.invalid"))

        generated = Fernet.generate_key()
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return key_path.read_bytes().strip()
        with os.fdopen(fd, "wb") as key_file:
            key_file.write(generated)
            key_file.flush()
            os.fsync(key_file.fileno())
        return generated

    def _init_encryption(self, key: Optional[str]):
        """Initialize stable encryption, retaining legacy device-key decryption."""
        if key:
            self._fernet = Fernet(self._derive_fernet_key(key))
            return

        self._fernet = Fernet(self._load_or_create_device_key())
        legacy_device_id = platform.node() + platform.machine()
        if legacy_device_id:
            self._legacy_fernet = Fernet(self._derive_fernet_key(legacy_device_id))

    def _encrypt(self, data: str) -> str:
        """Encrypt data"""
        if not self._fernet:
            return data
        return self._fernet.encrypt(data.encode()).decode()

    def _decrypt(self, data: str) -> str:
        """Decrypt data"""
        if not self._fernet:
            return data
        try:
            return self._fernet.decrypt(data.encode()).decode()
        except InvalidToken:
            if self._legacy_fernet is not None:
                try:
                    return self._legacy_fernet.decrypt(data.encode()).decode()
                except InvalidToken:
                    pass
            return data
        except Exception:
            logger.exception("Unexpected memory decryption failure")
            return data

    def _init_db(self):
        """Initialize database schema"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        cursor = self._conn.cursor()

        # Conversations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_calls TEXT,
                tool_call_id TEXT,
                name TEXT,
                timestamp TEXT NOT NULL,
                message_id TEXT NOT NULL
            )
        """)

        # Memory entries table (for long-term memory)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_entries (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT
            )
        """)

        # Skills memory table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS skill_memory (
                id TEXT PRIMARY KEY,
                skill_name TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT
            )
        """)

        # Key/value memory table (backing the agent's memory tool store/retrieve)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kv_memory (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT
            )
        """)

        # Memory Harness v1 tables (additive; legacy tables stay untouched).
        # content/evidence_text are encrypted like every other private column;
        # normalized_hash is a plaintext SHA-256 of the normalized content so
        # dedup works without FTS on ciphertext (see docs/memory-harness-v2-gap).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_items (
                id TEXT PRIMARY KEY,
                memory_type TEXT NOT NULL,
                scope_type TEXT NOT NULL DEFAULT 'global',
                scope_id TEXT,
                content TEXT NOT NULL,
                normalized_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                confidence REAL NOT NULL DEFAULT 0.5,
                importance REAL NOT NULL DEFAULT 0.5,
                sensitivity REAL NOT NULL DEFAULT 0.0,
                source_type TEXT NOT NULL DEFAULT 'agent_inference',
                source_session_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                supersedes_id TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_evidence (
                id TEXT PRIMARY KEY,
                memory_id TEXT NOT NULL,
                evidence_type TEXT NOT NULL,
                session_id TEXT,
                evidence_text TEXT,
                confidence REAL NOT NULL DEFAULT 0.5,
                verified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_summaries (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                summary_version INTEGER NOT NULL DEFAULT 1,
                token_estimate INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Create indexes
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_session ON memory_entries(session_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_created ON memory_entries(created_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_skill_memory_skill ON skill_memory(skill_name)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_items_status ON memory_items(status, memory_type)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_items_hash ON memory_items(normalized_hash)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_items_scope ON memory_items(scope_type, scope_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_items_expiry ON memory_items(expires_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_evidence_memory ON memory_evidence(memory_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_summaries_session ON session_summaries(session_id)"
        )

        self._conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection"""
        if self._conn is None:
            self._init_db()
        return self._conn

    async def save_conversation(self, session_id: str, messages: List[Any]):
        """Save conversation messages"""
        conn = self._get_conn()
        cursor = conn.cursor()

        for msg in messages:
            # Check if message already exists
            cursor.execute(
                "SELECT 1 FROM conversations WHERE message_id = ?",
                (msg.id,),
            )
            if cursor.fetchone():
                continue

            tool_calls_json = None
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_calls_json = json.dumps([tc.to_dict() for tc in msg.tool_calls])

            content = msg.content
            if self.encrypt:
                content = self._encrypt(content)
                # Tool results can carry sensitive data (file contents, shell
                # output, web pages); encrypt them too, not just the message
                # content. Old plaintext rows still decrypt as no-ops.
                if tool_calls_json:
                    tool_calls_json = self._encrypt(tool_calls_json)

            cursor.execute(
                """
                INSERT INTO conversations (id, session_id, role, content, tool_calls, tool_call_id, name, timestamp, message_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    str(uuid.uuid4()),
                    session_id,
                    msg.role,
                    content,
                    tool_calls_json,
                    msg.tool_call_id,
                    msg.name,
                    msg.timestamp.isoformat(),
                    msg.id,
                ),
            )

        conn.commit()

    async def get_conversation(self, session_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get conversation history"""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM conversations
            WHERE session_id = ?
            ORDER BY timestamp ASC
            LIMIT ?
        """,
            (session_id, limit),
        )

        messages = []
        for row in cursor.fetchall():
            content = row["content"]
            if self.encrypt:
                content = self._decrypt(content)

            raw_tool_calls = row["tool_calls"]
            if raw_tool_calls and self.encrypt:
                # _decrypt() returns input unchanged on failure, so legacy
                # plaintext rows (and old encrypted rows) both parse fine.
                raw_tool_calls = self._decrypt(raw_tool_calls)

            msg = {
                "role": row["role"],
                "content": content,
                "tool_calls": json.loads(raw_tool_calls) if raw_tool_calls else [],
                "tool_call_id": row["tool_call_id"],
                "name": row["name"],
                "timestamp": row["timestamp"],
                "id": row["message_id"],
            }
            messages.append(msg)

        return messages

    async def list_conversations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List conversation session summaries, most recently active first.

        Each summary carries the session id, message count, last activity
        timestamp and a preview of the latest message (decrypted).
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT session_id, COUNT(*) AS message_count, MAX(timestamp) AS last_at
            FROM conversations
            GROUP BY session_id
            ORDER BY last_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        summaries = []
        for row in cursor.fetchall():
            sid = row["session_id"]
            cursor.execute(
                "SELECT content FROM conversations WHERE session_id = ? ORDER BY timestamp DESC LIMIT 1",
                (sid,),
            )
            last = cursor.fetchone()
            preview = ""
            if last is not None and last["content"]:
                preview = self._decrypt(last["content"]) if self.encrypt else last["content"]
                preview = " ".join(preview.split())[:120]
            summaries.append(
                {
                    "id": sid,
                    "message_count": int(row["message_count"]),
                    "timestamp": row["last_at"],
                    "preview": preview,
                }
            )
        return summaries

    async def list_memory_entries(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List long-term memory entries, newest first, excluding expired."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, session_id, content, created_at, expires_at
            FROM memory_entries
            WHERE expires_at IS NULL OR expires_at > ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (datetime.now().isoformat(), limit),
        )
        entries = []
        for row in cursor.fetchall():
            content = self._decrypt(row["content"]) if self.encrypt else row["content"]
            entries.append(
                {
                    "id": row["id"],
                    "session_id": row["session_id"],
                    "content": content,
                    "created_at": row["created_at"],
                    "expires_at": row["expires_at"],
                }
            )
        return entries

    async def list_skill_memory(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List skill memory entries, newest first, excluding expired."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT skill_name, key, value, created_at, expires_at
            FROM skill_memory
            WHERE expires_at IS NULL OR expires_at > ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (datetime.now().isoformat(), limit),
        )
        entries = []
        for row in cursor.fetchall():
            stored = self._decrypt(row["value"]) if self.encrypt else row["value"]
            try:
                value = json.loads(stored)
            except (json.JSONDecodeError, TypeError):
                value = stored
            entries.append(
                {
                    "skill_name": row["skill_name"],
                    "key": row["key"],
                    "value": value,
                    "created_at": row["created_at"],
                }
            )
        return entries

    async def add_memory_entry(
        self,
        session_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        ttl_days: Optional[int] = None,
    ):
        """Add a long-term memory entry"""
        conn = self._get_conn()
        cursor = conn.cursor()

        entry_id = str(uuid.uuid4())
        created_at = datetime.now().isoformat()
        expires_at = None

        if ttl_days:
            expires_at = (datetime.now() + timedelta(days=ttl_days)).isoformat()

        stored_content = self._encrypt(content) if self.encrypt else content
        metadata_json = json.dumps(metadata) if metadata else None

        cursor.execute(
            """
            INSERT INTO memory_entries (id, session_id, content, metadata, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (entry_id, session_id, stored_content, metadata_json, created_at, expires_at),
        )

        conn.commit()

    async def get_relevant_context(self, query: str, limit: int = 5) -> str:
        """Get relevant memory context for a query (simple keyword matching)"""
        conn = self._get_conn()
        cursor = conn.cursor()

        # Simple keyword search - in production, use embeddings
        keywords = query.lower().split()

        cursor.execute(
            """
            SELECT content, created_at FROM memory_entries
            WHERE expires_at IS NULL OR expires_at > ?
            ORDER BY created_at DESC
            LIMIT ?
        """,
            (datetime.now().isoformat(), limit * 3),
        )

        entries = []
        for row in cursor.fetchall():
            content = self._decrypt(row["content"]) if self.encrypt else row["content"]
            # Simple relevance scoring
            score = sum(1 for kw in keywords if kw in content.lower())
            if score > 0:
                entries.append((score, content))

        # Sort by relevance
        entries.sort(key=lambda x: x[0], reverse=True)

        if not entries:
            return ""

        context_parts = [
            f"[Memory {i + 1}] {content}" for i, (_, content) in enumerate(entries[:limit])
        ]
        return "\n\n".join(context_parts)

    async def store_memory(self, key: str, value: str, ttl_days: Optional[int] = None) -> None:
        """Store a key/value entry in long-term memory (upsert by key)."""
        now = datetime.now().isoformat()
        expires_at = None
        if ttl_days:
            expires_at = (datetime.now() + timedelta(days=ttl_days)).isoformat()
        stored_value = self._encrypt(value) if self.encrypt else value
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO kv_memory (key, value, created_at, updated_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at,
                expires_at = excluded.expires_at
            """,
            (key, stored_value, now, now, expires_at),
        )
        conn.commit()

    async def get_memory(self, key: str) -> Optional[str]:
        """Return the value stored under *key*, or None if absent/expired."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT value, expires_at FROM kv_memory WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row is None:
            return None
        expires_at = row["expires_at"]
        if expires_at and expires_at <= datetime.now().isoformat():
            return None
        return self._decrypt(row["value"]) if self.encrypt else row["value"]

    async def list_memory(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List recent key/value memory entries, newest first."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT key, value, created_at, updated_at FROM kv_memory
            WHERE expires_at IS NULL OR expires_at > ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (datetime.now().isoformat(), limit),
        )
        entries = []
        for row in cursor.fetchall():
            value = self._decrypt(row["value"]) if self.encrypt else row["value"]
            entries.append(
                {
                    "key": row["key"],
                    "value": value,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return entries

    async def delete_memory(self, key: str) -> bool:
        """Delete the entry stored under *key*. Returns True if it existed."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM kv_memory WHERE key = ?", (key,))
        conn.commit()
        return cursor.rowcount > 0

    async def search_memory(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search memory entries"""
        conn = self._get_conn()
        cursor = conn.cursor()

        keywords = query.lower().split()

        cursor.execute(
            """
            SELECT id, content, metadata, created_at FROM memory_entries
            WHERE expires_at IS NULL OR expires_at > ?
            ORDER BY created_at DESC
            LIMIT ?
        """,
            (datetime.now().isoformat(), limit * 3),
        )

        results = []
        for row in cursor.fetchall():
            content = self._decrypt(row["content"]) if self.encrypt else row["content"]
            score = sum(1 for kw in keywords if kw in content.lower())
            if score > 0:
                results.append(
                    {
                        "id": row["id"],
                        "content": content,
                        "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                        "created_at": row["created_at"],
                        "score": score,
                    }
                )

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    async def search_sessions(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search conversation sessions by content.

        Uses SQL LIKE for plaintext. For encrypted data it decrypts a bounded
        window of recent messages per candidate session (bounded-decrypt, see
        docs/memory-harness-v2-gap.md) so matches buried earlier in a session
        are still found without decrypting the whole database, then ranks the
        matching sessions by keyword-hit count.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        keywords = query.lower().split()
        if not keywords:
            return []

        if self.encrypt:
            cursor.execute(
                "SELECT session_id, MAX(timestamp) AS last_at FROM conversations "
                "GROUP BY session_id ORDER BY last_at DESC LIMIT ?",
                (limit * 10,),
            )
            results = []
            for sid_row in cursor.fetchall():
                sid = sid_row["session_id"]
                cursor.execute(
                    "SELECT content, timestamp FROM conversations WHERE session_id = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (sid, _SEARCH_WINDOW),
                )
                rows = cursor.fetchall()
                if not rows:
                    continue
                hits = 0
                title = "Untitled"
                preview = ""
                last_at = rows[0]["timestamp"]
                for row in rows:
                    content = self._decrypt(row["content"])
                    if not preview:
                        preview = content
                        title = content[:80] if content else "Untitled"
                    hits += sum(1 for kw in keywords if kw in content.lower())
                if hits:
                    results.append(
                        {
                            "id": sid,
                            "title": title,
                            "preview": preview,
                            "timestamp": last_at,
                            "score": hits,
                        }
                    )
            results.sort(key=lambda r: r["score"], reverse=True)
            return results[:limit]

        like_conditions = " OR ".join("LOWER(c.content) LIKE ?" for _ in keywords)
        params = [f"%{kw}%" for kw in keywords]

        cursor.execute(
            f"""
            SELECT c.session_id, c.content, c.timestamp
            FROM conversations c
            WHERE {like_conditions}
            ORDER BY c.timestamp DESC
            LIMIT ?
            """,
            (*params, limit * 5),
        )

        seen = {}
        for row in cursor.fetchall():
            sid = row["session_id"]
            if sid in seen:
                continue
            content = row["content"]
            seen[sid] = {
                "id": sid,
                "title": content[:80] if content else "Untitled",
                "preview": content,
                "timestamp": row["timestamp"],
            }

        return list(seen.values())[:limit]

    async def set_skill_memory(
        self, skill_name: str, key: str, value: Any, ttl_days: Optional[int] = None
    ):
        """Set skill-specific memory"""
        conn = self._get_conn()
        cursor = conn.cursor()

        expires_at = None
        if ttl_days:
            expires_at = (datetime.now() + timedelta(days=ttl_days)).isoformat()

        stored_value = json.dumps(value)
        if self.encrypt:
            stored_value = self._encrypt(stored_value)

        cursor.execute(
            """
            INSERT OR REPLACE INTO skill_memory (id, skill_name, key, value, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                f"{skill_name}:{key}",
                skill_name,
                key,
                stored_value,
                datetime.now().isoformat(),
                expires_at,
            ),
        )

        conn.commit()

    async def get_skill_memory(self, skill_name: str, key: str) -> Optional[Any]:
        """Get skill-specific memory"""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT value FROM skill_memory
            WHERE skill_name = ? AND key = ?
            AND (expires_at IS NULL OR expires_at > ?)
        """,
            (skill_name, key, datetime.now().isoformat()),
        )

        row = cursor.fetchone()
        if not row:
            return None

        value = row["value"]
        if self.encrypt:
            value = self._decrypt(value)

        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    async def cleanup_expired(self):
        """Clean up expired memory entries"""
        conn = self._get_conn()
        cursor = conn.cursor()

        now = datetime.now().isoformat()

        cursor.execute(
            "DELETE FROM memory_entries WHERE expires_at IS NOT NULL AND expires_at < ?", (now,)
        )
        cursor.execute(
            "DELETE FROM skill_memory WHERE expires_at IS NOT NULL AND expires_at < ?", (now,)
        )
        cursor.execute(
            "DELETE FROM memory_items WHERE expires_at IS NOT NULL AND expires_at < ?", (now,)
        )
        # The kv_memory table backs the agent's memory tool; reads already hide
        # expired rows, but the rows themselves were never physically pruned,
        # so TTL'd entries leaked forever and the DB grew unbounded.
        cursor.execute(
            "DELETE FROM kv_memory WHERE expires_at IS NOT NULL AND expires_at < ?", (now,)
        )

        conn.commit()

    async def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics"""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as count FROM conversations")
        conv_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM memory_entries")
        mem_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM skill_memory")
        skill_mem_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(DISTINCT session_id) as count FROM conversations")
        session_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM memory_items")
        memory_item_count = cursor.fetchone()["count"]

        cursor.execute(
            "SELECT COUNT(*) as count FROM memory_items "
            "WHERE status IN ('candidate', 'pending_confirmation')"
        )
        pending_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM memory_evidence")
        evidence_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM session_summaries")
        summary_count = cursor.fetchone()["count"]

        return {
            "conversations": conv_count,
            "memory_entries": mem_count,
            "skill_memory_entries": skill_mem_count,
            "sessions": session_count,
            "memory_items": memory_item_count,
            "memory_evidence": evidence_count,
            "session_summaries": summary_count,
            "pending_memories": pending_count,
            "db_size_bytes": self.db_path.stat().st_size if self.db_path.exists() else 0,
        }

    # ------------------------------------------------------------------
    # Memory Harness v1 — memory_items / memory_evidence / session_summaries
    # (additive API; legacy methods above remain the compatibility surface)
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize content for dedup: lowercase, collapse whitespace, strip punctuation."""
        normalized = " ".join(str(text or "").lower().split())
        return normalized.rstrip(".,!?;:")

    @staticmethod
    def _normalized_hash(text: str) -> str:
        """Stable plaintext hash of the normalized content, used for O(1) dedup.

        The hash itself is not reversible, so it does not leak the memory
        content the way a plaintext copy would; on-device v1 accepts this
        trade-off so dedup never requires FTS on ciphertext.
        """
        return hashlib.sha256(MobileMemoryProvider._normalize_text(text).encode()).hexdigest()

    async def insert_memory_item(
        self,
        *,
        content: str,
        memory_type: str = "stable_fact",
        scope_type: str = "global",
        scope_id: Optional[str] = None,
        status: str = "active",
        confidence: float = 0.8,
        importance: float = 0.5,
        sensitivity: float = 0.0,
        source_type: str = "agent_inference",
        source_session_id: Optional[str] = None,
        ttl_days: Optional[int] = None,
        supersedes_id: Optional[str] = None,
    ) -> str:
        """Insert a memory item; returns its id."""
        conn = self._get_conn()
        cursor = conn.cursor()
        item_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        expires_at = None
        if ttl_days:
            expires_at = (datetime.now() + timedelta(days=ttl_days)).isoformat()
        stored = self._encrypt(content) if self.encrypt else content
        cursor.execute(
            """
            INSERT INTO memory_items (
                id, memory_type, scope_type, scope_id, content, normalized_hash,
                status, confidence, importance, sensitivity, source_type,
                source_session_id, created_at, updated_at, expires_at, supersedes_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                memory_type,
                scope_type,
                scope_id,
                stored,
                self._normalized_hash(content),
                status,
                confidence,
                importance,
                sensitivity,
                source_type,
                source_session_id,
                now,
                now,
                expires_at,
                supersedes_id,
            ),
        )
        conn.commit()
        return item_id

    async def find_duplicate_memory(
        self,
        content: str,
        scope_type: str = "global",
        scope_id: Optional[str] = None,
        statuses: tuple = ("active",),
    ) -> Optional[Dict[str, Any]]:
        """Return an existing memory with the same normalized content + scope."""
        conn = self._get_conn()
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in statuses)
        cursor.execute(
            f"""
            SELECT id, content FROM memory_items
            WHERE normalized_hash = ? AND scope_type = ? AND status IN ({placeholders})
            ORDER BY created_at DESC LIMIT 1
            """,
            (self._normalized_hash(content), scope_type, *statuses),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "content": self._decrypt(row["content"]) if self.encrypt else row["content"],
        }

    async def add_memory_evidence(
        self,
        memory_id: str,
        evidence_type: str,
        session_id: Optional[str] = None,
        evidence_text: Optional[str] = None,
        confidence: float = 0.5,
        verified: int = 0,
    ) -> None:
        """Attach a provenance record to a memory item."""
        conn = self._get_conn()
        cursor = conn.cursor()
        stored = self._encrypt(evidence_text) if (evidence_text and self.encrypt) else evidence_text
        cursor.execute(
            """
            INSERT INTO memory_evidence (
                id, memory_id, evidence_type, session_id, evidence_text,
                confidence, verified, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                memory_id,
                evidence_type,
                session_id,
                stored,
                confidence,
                int(verified),
                datetime.now().isoformat(),
            ),
        )
        conn.commit()

    async def get_memory_evidence(
        self,
        memory_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return provenance records for a memory item, newest first."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, memory_id, evidence_type, session_id, evidence_text,
                   confidence, verified, created_at
            FROM memory_evidence
            WHERE memory_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (memory_id, limit),
        )
        records = []
        for row in cursor.fetchall():
            records.append(
                {
                    "id": row["id"],
                    "memory_id": row["memory_id"],
                    "evidence_type": row["evidence_type"],
                    "session_id": row["session_id"],
                    "evidence_text": (
                        self._decrypt(row["evidence_text"])
                        if (row["evidence_text"] and self.encrypt)
                        else row["evidence_text"]
                    ),
                    "confidence": row["confidence"],
                    "verified": row["verified"],
                    "created_at": row["created_at"],
                }
            )
        return records

    async def list_memory_items(
        self,
        *,
        statuses: tuple = ("active",),
        memory_types: Optional[tuple] = None,
        limit: int = 200,
        include_expired: bool = False,
    ) -> List[Dict[str, Any]]:
        """List memory items, newest first, optionally filtered by status/type.

        ``include_expired`` disables the expiry filter so archived rows
        (superseded/expired/rejected) stay visible in management UIs.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        status_ph = ",".join("?" for _ in statuses)
        params: list = []
        expiry_clause = ""
        if not include_expired:
            expiry_clause = "(expires_at IS NULL OR expires_at > ?) AND "
            params.append(datetime.now().isoformat())
        params.extend(statuses)
        type_clause = ""
        if memory_types:
            type_ph = ",".join("?" for _ in memory_types)
            type_clause = f" AND memory_type IN ({type_ph})"
            params.extend(memory_types)
        cursor.execute(
            f"""
            SELECT * FROM memory_items
            WHERE {expiry_clause}status IN ({status_ph}){type_clause}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (*params, limit),
        )
        items = []
        for row in cursor.fetchall():
            items.append(
                {
                    "id": row["id"],
                    "memory_type": row["memory_type"],
                    "scope_type": row["scope_type"],
                    "scope_id": row["scope_id"],
                    "content": self._decrypt(row["content"]) if self.encrypt else row["content"],
                    "status": row["status"],
                    "confidence": row["confidence"],
                    "importance": row["importance"],
                    "sensitivity": row["sensitivity"],
                    "source_type": row["source_type"],
                    "source_session_id": row["source_session_id"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "expires_at": row["expires_at"],
                    "supersedes_id": row["supersedes_id"],
                }
            )
        return items

    async def list_pending_memories(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List candidates awaiting confirmation."""
        return await self.list_memory_items(
            statuses=("candidate", "pending_confirmation"),
            limit=limit,
        )

    async def update_memory_status(self, memory_id: str, status: str) -> bool:
        """Move a memory item to a new status. Returns True if it existed."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE memory_items SET status = ?, updated_at = ? WHERE id = ?",
            (status, datetime.now().isoformat(), memory_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    async def delete_memory_item(self, memory_id: str) -> bool:
        """Hard-delete a memory item together with its evidence records."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM memory_evidence WHERE memory_id = ?", (memory_id,))
        cursor.execute("DELETE FROM memory_items WHERE id = ?", (memory_id,))
        conn.commit()
        return cursor.rowcount > 0

    async def supersede_memory(self, old_id: str, new_id: str) -> bool:
        """Mark an old memory as superseded by a newer one."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE memory_items SET status = 'superseded', supersedes_id = ?, updated_at = ? "
            "WHERE id = ?",
            (new_id, datetime.now().isoformat(), old_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    async def get_session_summary(self, session_id: str) -> Optional[str]:
        """Return the latest persisted summary for a session, if any."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT summary FROM session_summaries WHERE session_id = ? "
            "ORDER BY summary_version DESC LIMIT 1",
            (session_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._decrypt(row["summary"]) if self.encrypt else row["summary"]

    async def upsert_session_summary(
        self,
        session_id: str,
        summary: str,
        token_estimate: Optional[int] = None,
    ) -> None:
        """Persist the latest session summary (version-incremented upsert)."""
        conn = self._get_conn()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        stored = self._encrypt(summary) if self.encrypt else summary
        cursor.execute(
            "SELECT id, summary_version FROM session_summaries WHERE session_id = ? "
            "ORDER BY summary_version DESC LIMIT 1",
            (session_id,),
        )
        row = cursor.fetchone()
        if row is None:
            cursor.execute(
                """
                INSERT INTO session_summaries (
                    id, session_id, summary, summary_version, token_estimate, created_at, updated_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?)
                """,
                (str(uuid.uuid4()), session_id, stored, token_estimate, now, now),
            )
        else:
            cursor.execute(
                "UPDATE session_summaries SET summary = ?, summary_version = ?, "
                "token_estimate = ?, updated_at = ? WHERE id = ?",
                (stored, int(row["summary_version"]) + 1, token_estimate, now, row["id"]),
            )
        conn.commit()

    async def consolidate_memories(self) -> Dict[str, int]:
        """Lightweight consolidation: expire stale entries and drop unconfirmed
        candidates past their TTL. Runs on demand at lifecycle points (session
        start, cleanup cron) — never as a background daemon.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        expired = 0
        dropped_candidates = 0

        # 1. Expire memory_items whose expires_at passed (status kept for audit).
        #    Skip rows already expired so updated_at is not bumped every run —
        #    otherwise the prune below (aged from expires_at) would never match.
        cursor.execute(
            "UPDATE memory_items SET status = 'expired', updated_at = ? "
            "WHERE expires_at IS NOT NULL AND expires_at < ? AND status != 'expired'",
            (now, now),
        )
        expired = cursor.rowcount

        # 2. Drop unconfirmed candidates/pending older than their TTL.
        for status in ("candidate", "pending_confirmation"):
            ttl = MEMORY_TTL_DAYS.get(status)
            if not ttl:
                continue
            cutoff = (datetime.now() - timedelta(days=ttl)).isoformat()
            cursor.execute(
                "UPDATE memory_items SET status = 'rejected', updated_at = ? "
                "WHERE status = ? AND created_at < ?",
                (now, status, cutoff),
            )
            dropped_candidates += cursor.rowcount

        # 3. Prune archived rows after the 90-day audit grace. Expired rows are
        #    aged from their expires_at (their updated_at is bumped at expiry
        #    time), superseded/rejected from their updated_at.
        prune_cutoff = (datetime.now() - timedelta(days=90)).isoformat()
        cursor.execute(
            "DELETE FROM memory_items "
            "WHERE (status = 'expired' AND expires_at < ?) "
            "OR (status IN ('superseded','rejected') AND updated_at < ?)",
            (prune_cutoff, prune_cutoff),
        )
        pruned = cursor.rowcount
        conn.commit()
        return {"expired": expired, "dropped_candidates": dropped_candidates, "pruned": pruned}

    def close(self):
        """Close database connection"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def clear_all(self):
        """Delete all conversations, memory and session data."""
        conn = self._get_conn()
        with conn:
            for table in (
                "conversations",
                "memory_entries",
                "skill_memory",
                "memory_items",
                "memory_evidence",
                "session_summaries",
            ):
                conn.execute(f"DELETE FROM {table}")
        conn.commit()

    def __del__(self):
        self.close()
