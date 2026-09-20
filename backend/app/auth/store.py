"""Isolated SQLite storage for identity, memberships, and verification codes."""
from __future__ import annotations
import sqlite3,threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
DEFAULT_DATABASE_PATH=Path(__file__).resolve().parents[2]/"storage"/"auth"/"auth.sqlite3"
class AuthStore:
 def __init__(self,database_path:str|Path|None=None):
  self.database_path=str(database_path or DEFAULT_DATABASE_PATH)
  if self.database_path!=":memory:":Path(self.database_path).parent.mkdir(parents=True,exist_ok=True)
  self._lock=threading.RLock();self._connection=sqlite3.connect(self.database_path,check_same_thread=False);self._connection.row_factory=sqlite3.Row;self._connection.execute("PRAGMA foreign_keys=ON");self._initialize_schema()
 def _initialize_schema(self):
  with self._lock,self._connection:
   self._connection.executescript("""
    CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, email TEXT UNIQUE, password_hash TEXT NOT NULL, email_verified INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL, owner_user_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(owner_user_id) REFERENCES users(user_id));
    CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_user_id);
    CREATE TABLE IF NOT EXISTS project_memberships (membership_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_id TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(user_id,project_id), FOREIGN KEY(user_id) REFERENCES users(user_id));
    CREATE INDEX IF NOT EXISTS idx_memberships_user ON project_memberships(user_id);
    CREATE TABLE IF NOT EXISTS email_verification_codes (verification_id TEXT PRIMARY KEY,email TEXT NOT NULL,purpose TEXT NOT NULL,code_hash TEXT NOT NULL,expires_at TEXT NOT NULL,created_at TEXT NOT NULL,consumed_at TEXT,failed_attempts INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_verification_email ON email_verification_codes(email,purpose,status);
   """)
   columns={row["name"] for row in self._connection.execute("PRAGMA table_info(users)").fetchall()}
   if "email_verified" not in columns:self._connection.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
 @contextmanager
 def transaction(self)->Iterator[sqlite3.Connection]:
  with self._lock:
   try:yield self._connection;self._connection.commit()
   except Exception:self._connection.rollback();raise
 def close(self):
  with self._lock:self._connection.close()
 def __enter__(self):return self
 def __exit__(self,*args):self.close()
