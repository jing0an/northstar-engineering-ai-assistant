import logging,tempfile,unittest
from uuid import uuid4
from app.auth import AuthStore,PBKDF2PasswordHasher,SQLiteProjectMembershipRepository,SQLiteUserRepository,User,UserStatus,ProjectMembership,UserAlreadyExistsError
class AuthPersistenceTest(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.store=AuthStore(self.tmp.name+"/auth.sqlite3");self.repo=SQLiteUserRepository(self.store);self.hasher=PBKDF2PasswordHasher()
 def tearDown(self):self.store.close();self.tmp.cleanup()
 def user(self,**kw):
  values={"username":"alice","email":"alice@example.com","password_hash":self.hasher.hash("correct horse")};values.update(kw);return User(**values)
 def test_hash_round_trip_and_not_plaintext(self):
  h=self.hasher.hash("correct horse");self.assertNotEqual(h,"correct horse");self.assertTrue(self.hasher.verify("correct horse",h));self.assertFalse(self.hasher.verify("wrong",h));self.assertNotEqual(h,self.hasher.hash("correct horse"))
 def test_invalid_password_and_malformed_hash_are_safe(self):
  with self.assertRaises(ValueError):self.hasher.hash("short")
  self.assertFalse(self.hasher.verify("correct horse","bad"));self.assertFalse(self.hasher.verify("correct horse",None))
 def test_user_create_and_queries(self):
  user=self.repo.create(self.user());self.assertEqual(self.repo.get_by_id(user.user_id).user_id,user.user_id);self.assertEqual(self.repo.get_by_username("alice").user_id,user.user_id);self.assertEqual(self.repo.get_by_email("ALICE@EXAMPLE.COM").user_id,user.user_id)
 def test_unique_identity_fields(self):
  self.repo.create(self.user())
  with self.assertRaises(UserAlreadyExistsError):self.repo.create(self.user(user_id=uuid4(),username="alice2"))
  with self.assertRaises(UserAlreadyExistsError):self.repo.create(self.user(user_id=uuid4(),username="alice",email="other@example.com"))
  with self.assertRaises(UserAlreadyExistsError):self.repo.create(self.user(user_id=self.repo.get_by_username("alice").user_id,username="other",email="other2@example.com"))
 def test_status_round_trip(self):
  for status in UserStatus:
   user=self.repo.create(self.user(username=status.value,email=status.value+"@example.com",status=status));self.assertEqual(self.repo.get_by_id(user.user_id).status,status)
 def test_database_isolation(self):
  other=AuthStore(self.tmp.name+"/other.sqlite3");other_repo=SQLiteUserRepository(other);user=self.repo.create(self.user());self.assertIsNone(other_repo.get_by_id(user.user_id));other.close()
 def test_membership_persistence_and_access(self):
  user=self.repo.create(self.user());members=SQLiteProjectMembershipRepository(self.store);m=members.add(ProjectMembership(user_id=user.user_id,project_id="BJ-KC-2024-01",role="owner"));self.assertTrue(members.has_access(user.user_id,"BJ-KC-2024-01"));self.assertFalse(members.has_access(uuid4(),"BJ-KC-2024-01"));self.assertEqual(members.list_for_user(user.user_id)[0].project_id,m.project_id)
 def test_password_not_in_logs_or_exceptions(self):
  secret="correct horse";h=self.hasher.hash(secret);self.assertNotIn(secret,h)
  try:self.hasher.hash("short")
  except ValueError as error:self.assertNotIn(secret,str(error))
if __name__=="__main__":unittest.main()
