"""
memory/store.py — Per-user persistent chat history with named sessions.

Storage layout (in config.MEMORY_DIR):
  {uid}_idx.json        — session index: {active_id, sessions: [{id, name, created_at, last_used}]}
  {uid}_{sid}.json      — message history for that session

Legacy migration: existing {uid}.json is automatically imported as "Session 1".

Sessions survive bot restarts — all data is written to disk immediately.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


class MemoryStore:
    def __init__(self) -> None:
        self._dir = config.MEMORY_DIR

    # ── Internal paths ─────────────────────────────────────────────────────

    def _idx_path(self, uid: str) -> Path:
        return self._dir / f"{uid}_idx.json"

    def _hist_path(self, uid: str, sid: str) -> Path:
        return self._dir / f"{uid}_{sid}.json"

    def _legacy_path(self, uid: str) -> Path:
        return self._dir / f"{uid}.json"

    # ── Index helpers ──────────────────────────────────────────────────────

    def _load_index(self, uid: str) -> dict:
        p = self._idx_path(uid)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass

        # Migrate legacy single-file history
        legacy = self._legacy_path(uid)
        if legacy.exists():
            sid = self._new_sid()
            index = {
                "active": sid,
                "sessions": [{"id": sid, "name": "Session 1",
                               "created_at": _ts(), "last_used": _ts()}],
            }
            try:
                hist = json.loads(legacy.read_text(encoding="utf-8"))
                self._hist_path(uid, sid).write_text(
                    json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                legacy.unlink()
                logger.info(f"MemoryStore: migrated legacy history for user {uid}")
            except Exception:
                pass
            self._save_index(uid, index)
            return index

        # Brand-new user
        return self._create_default_index(uid)

    def _create_default_index(self, uid: str) -> dict:
        sid = self._new_sid()
        index = {
            "active": sid,
            "sessions": [{"id": sid, "name": "Session 1",
                           "created_at": _ts(), "last_used": _ts()}],
        }
        self._save_index(uid, index)
        return index

    def _save_index(self, uid: str, index: dict) -> None:
        try:
            self._idx_path(uid).write_text(
                json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"MemoryStore: failed to save index for {uid}: {e}")

    @staticmethod
    def _new_sid() -> str:
        return uuid.uuid4().hex[:8]

    def _active_sid(self, uid: str) -> str:
        return self._load_index(uid)["active"]

    def _normalize_uid(self, user_id: int | str) -> str:
        return str(user_id)

    # ── Public session API ─────────────────────────────────────────────────

    def list_sessions(self, user_id: int | str) -> tuple[list[dict], str]:
        """Returns (sessions_list, active_session_id)."""
        uid = self._normalize_uid(user_id)
        idx = self._load_index(uid)
        return idx["sessions"], idx["active"]

    def active_session_name(self, user_id: int | str) -> str:
        uid = self._normalize_uid(user_id)
        idx = self._load_index(uid)
        for s in idx["sessions"]:
            if s["id"] == idx["active"]:
                return s["name"]
        return "?"

    def new_session(self, user_id: int | str, name: str | None = None) -> str:
        """Create a new session and make it active. Returns the session name."""
        uid = self._normalize_uid(user_id)
        idx = self._load_index(uid)
        sid = self._new_sid()
        if not name:
            name = f"Session {len(idx['sessions']) + 1}"
        # Deduplicate name
        existing = {s["name"] for s in idx["sessions"]}
        base, n = name, 2
        while name in existing:
            name = f"{base} ({n})"
            n += 1
        idx["sessions"].append({"id": sid, "name": name,
                                 "created_at": _ts(), "last_used": _ts()})
        idx["active"] = sid
        self._save_index(uid, idx)
        logger.info(f"MemoryStore: created session '{name}' for user {uid}")
        return name

    def switch_session(self, user_id: int | str, ref: str) -> str | None:
        """Switch to session by name or 1-based number. Returns name, or None if not found."""
        uid = self._normalize_uid(user_id)
        idx = self._load_index(uid)
        sessions = idx["sessions"]
        target = None
        if ref.isdigit():
            i = int(ref) - 1
            if 0 <= i < len(sessions):
                target = sessions[i]
        if target is None:
            ref_l = ref.lower()
            for s in sessions:
                if s["name"].lower() == ref_l:
                    target = s
                    break
        if target is None:
            return None
        idx["active"] = target["id"]
        target["last_used"] = _ts()
        self._save_index(uid, idx)
        return target["name"]

    def rename_session(self, user_id: int | str, new_name: str) -> str:
        """Rename the active session. Returns the final (deduplicated) name."""
        uid = self._normalize_uid(user_id)
        idx = self._load_index(uid)
        active_id = idx["active"]
        existing = {s["name"] for s in idx["sessions"] if s["id"] != active_id}
        base, n = new_name, 2
        while new_name in existing:
            new_name = f"{base} ({n})"
            n += 1
        for s in idx["sessions"]:
            if s["id"] == active_id:
                s["name"] = new_name
                break
        self._save_index(uid, idx)
        return new_name

    def delete_session(self, user_id: int | str, ref: str) -> str | None:
        """Delete session by name or number. Cannot delete the only session.
        Returns deleted session name, or None if not found / only one session."""
        uid = self._normalize_uid(user_id)
        idx = self._load_index(uid)
        sessions = idx["sessions"]
        if len(sessions) <= 1:
            return None
        target = None
        if ref.isdigit():
            i = int(ref) - 1
            if 0 <= i < len(sessions):
                target = sessions[i]
        if target is None:
            ref_l = ref.lower()
            for s in sessions:
                if s["name"].lower() == ref_l:
                    target = s
                    break
        if target is None:
            return None
        h = self._hist_path(uid, target["id"])
        if h.exists():
            h.unlink()
        idx["sessions"] = [s for s in sessions if s["id"] != target["id"]]
        if idx["active"] == target["id"]:
            idx["active"] = idx["sessions"][0]["id"]
        self._save_index(uid, idx)
        logger.info(f"MemoryStore: deleted session '{target['name']}' for user {uid}")
        return target["name"]

    # ── History API (operates on the active session) ───────────────────────

    def get(self, user_id: int | str) -> list[dict]:
        """Return message history for the active session."""
        uid = self._normalize_uid(user_id)
        p = self._hist_path(uid, self._active_sid(uid))
        if not p.exists():
            return []
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"MemoryStore: failed to read {p}: {e}")
            return []

    def append(self, user_id: int | str, role: str, content: str) -> None:
        """Append a message to the active session and persist."""
        uid = self._normalize_uid(user_id)
        sid = self._active_sid(uid)
        history = self.get(uid)
        history.append({"role": role, "content": content})
        if len(history) > config.MAX_HISTORY:
            history = history[-config.MAX_HISTORY:]
        try:
            self._hist_path(uid, sid).write_text(
                json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"MemoryStore: failed to save history: {e}")
        # Update last_used timestamp
        idx = self._load_index(uid)
        for s in idx["sessions"]:
            if s["id"] == sid:
                s["last_used"] = _ts()
                break
        self._save_index(uid, idx)

    def clear(self, user_id: int | str) -> str:
        """Clear history of the active session (keeps the session). Returns session name."""
        uid = self._normalize_uid(user_id)
        sid = self._active_sid(uid)
        p = self._hist_path(uid, sid)
        if p.exists():
            p.unlink()
        name = self.active_session_name(uid)
        logger.info(f"MemoryStore: cleared history for user {uid} session '{name}'")
        return name
