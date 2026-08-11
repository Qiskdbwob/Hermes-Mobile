"""Mobile Memory Provider - SQLite-based with encryption support"""

import base64
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

        Uses SQL LIKE for plaintext, Python filtering for encrypted data.
        Returns a list of session summaries matching the query.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        keywords = query.lower().split()

        if self.encrypt:
            cursor.execute(
                "SELECT DISTINCT session_id FROM conversations ORDER BY timestamp DESC LIMIT ?",
                (limit * 10,),
            )
            results = []
            for sid_row in cursor.fetchall():
                sid = sid_row["session_id"]
                cursor.execute(
                    "SELECT content, timestamp FROM conversations WHERE session_id = ? ORDER BY timestamp DESC LIMIT 1",
                    (sid,),
                )
                row = cursor.fetchone()
                if not row:
                    continue
                content = self._decrypt(row["content"])
                if any(kw in content.lower() for kw in keywords):
                    results.append(
                        {
                            "id": sid,
                            "title": content[:80] if content else "Untitled",
                            "preview": content,
                            "timestamp": row["timestamp"],
                        }
                    )
                    if len(results) >= limit:
                        break
            return results

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

        return {
            "conversations": conv_count,
            "memory_entries": mem_count,
            "skill_memory_entries": skill_mem_count,
            "sessions": session_count,
            "db_size_bytes": self.db_path.stat().st_size if self.db_path.exists() else 0,
        }

    def close(self):
        """Close database connection"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def clear_all(self):
        """Delete all conversations, memory entries and skill memory."""
        conn = self._get_conn()
        with conn:
            for table in ("conversations", "memory_entries", "skill_memory"):
                conn.execute(f"DELETE FROM {table}")
        conn.commit()

    def __del__(self):
        self.close()
