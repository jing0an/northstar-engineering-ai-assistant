"""SQLite implementations of the A2.3 identity repository contracts."""
from __future__ import annotations
import sqlite3
from datetime import datetime,timezone
from pathlib import Path
from uuid import UUID
from .models import Project, ProjectMembership,User
from .repositories import ProjectMembershipRepository,ProjectRepository,UserRepository
from .store import AuthStore
class AuthError(Exception): pass
class UserAlreadyExistsError(AuthError): pass
class MembershipAlreadyExistsError(AuthError): pass
class ProjectAlreadyExistsError(AuthError): pass
class SQLiteUserRepository:
 def __init__(self,store:AuthStore|str|Path|None=None):self.store=store if isinstance(store,AuthStore) else AuthStore(store)
 @staticmethod
 def _utc(value:datetime)->str:
  if value.tzinfo is None or value.utcoffset() is None:raise ValueError("timestamp must be timezone-aware")
  return value.astimezone(timezone.utc).isoformat()
 @staticmethod
 def _from_row(row):
  return User(user_id=UUID(row["user_id"]),username=row["username"],email=row["email"],password_hash=row["password_hash"],email_verified=bool(row["email_verified"]),status=row["status"],created_at=datetime.fromisoformat(row["created_at"]),updated_at=datetime.fromisoformat(row["updated_at"]))
 def create(self,user:User)->User:
  try:
   with self.store.transaction() as c:c.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?,?)",(str(user.user_id),user.username,user.email,user.password_hash,int(user.email_verified),user.status.value,self._utc(user.created_at),self._utc(user.updated_at)))
  except sqlite3.IntegrityError as error:raise UserAlreadyExistsError("User identity already exists") from error
  return user
 def _get(self,column,value):
  with self.store.transaction() as c:row=c.execute(f"SELECT * FROM users WHERE {column} = ?",(value,)).fetchone()
  return self._from_row(row) if row else None
 def get_by_id(self,user_id:UUID)->User|None:
  try:value=str(UUID(str(user_id)))
  except (ValueError,TypeError):return None
  return self._get("user_id",value)
 def get_by_username(self,username:str)->User|None:
  if not isinstance(username,str) or not username.strip():return None
  return self._get("username",username.strip())
 def get_by_email(self,email:str)->User|None:
  if not isinstance(email,str) or not email.strip():return None
  return self._get("email",email.strip().casefold())
 def close(self):self.store.close()
class SQLiteProjectMembershipRepository:
 def __init__(self,store:AuthStore|str|Path|None=None):self.store=store if isinstance(store,AuthStore) else AuthStore(store)
 @staticmethod
 def _utc(value):return value.astimezone(timezone.utc).isoformat()
 @staticmethod
 def _from_row(row):return ProjectMembership(membership_id=UUID(row["membership_id"]),user_id=UUID(row["user_id"]),project_id=row["project_id"],role=row["role"],created_at=datetime.fromisoformat(row["created_at"]))
 def add(self,membership):
  try:
   with self.store.transaction() as c:c.execute("INSERT INTO project_memberships VALUES (?,?,?,?,?)",(str(membership.membership_id),str(membership.user_id),membership.project_id,membership.role.value,self._utc(membership.created_at)))
  except sqlite3.IntegrityError as error:raise MembershipAlreadyExistsError("Project membership already exists") from error
  return membership
 def list_for_user(self,user_id):
  with self.store.transaction() as c:rows=c.execute("SELECT * FROM project_memberships WHERE user_id=? ORDER BY created_at,membership_id",(str(user_id),)).fetchall()
  return [self._from_row(row) for row in rows]
 def has_access(self,user_id,project_id):
  if not isinstance(project_id,str) or not project_id.strip():return False
  with self.store.transaction() as c:return c.execute("SELECT 1 FROM project_memberships WHERE user_id=? AND project_id=?",(str(user_id),project_id.strip())).fetchone() is not None
 def close(self):self.store.close()


class SQLiteProjectRepository:
 def __init__(self,store:AuthStore|str|Path|None=None):self.store=store if isinstance(store,AuthStore) else AuthStore(store)
 @staticmethod
 def _utc(value:datetime)->str:
  if value.tzinfo is None or value.utcoffset() is None:raise ValueError("timestamp must be timezone-aware")
  return value.astimezone(timezone.utc).isoformat()
 @staticmethod
 def _from_row(row):
  return Project(project_id=row["project_id"],name=row["name"],status=row["status"],owner_user_id=UUID(row["owner_user_id"]),created_at=datetime.fromisoformat(row["created_at"]),updated_at=datetime.fromisoformat(row["updated_at"]))
 def create(self,project:Project)->Project:
  try:
   with self.store.transaction() as c:
    c.execute("INSERT INTO projects VALUES (?,?,?,?,?,?)",(project.project_id,project.name,project.status.value,str(project.owner_user_id),self._utc(project.created_at),self._utc(project.updated_at)))
  except sqlite3.IntegrityError as error:
   raise ProjectAlreadyExistsError("Project already exists") from error
  return project
 def create_with_owner(self,project:Project,membership:ProjectMembership)->Project:
  if membership.project_id != project.project_id or membership.user_id != project.owner_user_id:
   raise ValueError("owner membership must match project owner")
  try:
   with self.store.transaction() as c:
    c.execute("INSERT INTO projects VALUES (?,?,?,?,?,?)",(project.project_id,project.name,project.status.value,str(project.owner_user_id),self._utc(project.created_at),self._utc(project.updated_at)))
    c.execute("INSERT INTO project_memberships VALUES (?,?,?,?,?)",(str(membership.membership_id),str(membership.user_id),membership.project_id,membership.role.value,self._utc(membership.created_at)))
  except sqlite3.IntegrityError as error:
   message = str(error)
   if "project_memberships" in message:
    raise MembershipAlreadyExistsError("Project membership already exists") from error
   if "projects" in message:
    raise ProjectAlreadyExistsError("Project already exists") from error
   raise AuthError("Project could not be created") from error
  return project
 def get_by_id(self,project_id:str)->Project|None:
  if not isinstance(project_id,str) or not project_id.strip(): return None
  with self.store.transaction() as c: row=c.execute("SELECT * FROM projects WHERE project_id=?",(project_id.strip(),)).fetchone()
  return self._from_row(row) if row else None
 def list_for_user(self,user_id:UUID)->list[Project]:
  with self.store.transaction() as c:
   rows=c.execute("SELECT p.* FROM projects p JOIN project_memberships pm ON pm.project_id=p.project_id WHERE pm.user_id=? ORDER BY p.created_at,p.project_id",(str(user_id),)).fetchall()
  return [self._from_row(row) for row in rows]
 def close(self):self.store.close()

