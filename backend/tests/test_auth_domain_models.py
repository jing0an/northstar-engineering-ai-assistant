import unittest
from datetime import datetime,timezone
from uuid import UUID
from pydantic import ValidationError
from app.auth import ProjectMembership,ProjectRole,User,UserStatus
class AuthDomainModelTest(unittest.TestCase):
 def make(self,**overrides):
  values={"username":"Engineer","email":"Engineer@Example.COM","password_hash":"$argon2id$v=19$hash"};values.update(overrides);return User(**values)
 def test_uuid_and_normalized_identity(self):
  user=self.make();self.assertIsInstance(user.user_id,UUID);self.assertEqual(user.email,"engineer@example.com");self.assertEqual(user.status,UserStatus.PENDING);self.assertEqual(user.created_at.tzinfo,timezone.utc)
 def test_plaintext_password_is_not_a_field(self):
  with self.assertRaises(ValidationError):self.make(password="secret")
  with self.assertRaises(ValidationError):self.make(password_hash=" ")
 def test_status_email_and_timestamp_validation(self):
  self.assertEqual(self.make(status="active").status,UserStatus.ACTIVE)
  with self.assertRaises(ValidationError):self.make(status="unknown")
  with self.assertRaises(ValidationError):self.make(email="not-an-email")
  a=datetime(2026,1,1,tzinfo=timezone.utc);b=datetime(2026,1,2,tzinfo=timezone.utc)
  with self.assertRaises(ValidationError):self.make(created_at=b,updated_at=a)
  with self.assertRaises(ValidationError):self.make(created_at=datetime(2026,1,1),updated_at=b)
 def test_membership_preserves_legacy_project_id(self):
  u=self.make();m=ProjectMembership(user_id=u.user_id,project_id=" BJ-KC-2024-01 ",role="owner");self.assertEqual(m.project_id,"BJ-KC-2024-01");self.assertEqual(m.role,ProjectRole.OWNER)
  with self.assertRaises(ValidationError):ProjectMembership(user_id=u.user_id,project_id="../other")
 def test_membership_requires_identifiers(self):
  with self.assertRaises(ValidationError):ProjectMembership(project_id="project-a")
  with self.assertRaises(ValidationError):ProjectMembership(user_id=self.make().user_id,project_id=" ")
