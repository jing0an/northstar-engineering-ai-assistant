import os
import tempfile,unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.auth import AuthStore,MockEmailProvider,PBKDF2PasswordHasher,SQLiteUserRepository,VerificationCodeRepository,VerificationCodeService
import app.api.routes.auth as auth_route
class RegisterApiTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db_path=self.tmp.name+'/auth.sqlite3';self.store=AuthStore(self.db_path);self.mail=MockEmailProvider();self.verification=VerificationCodeService(VerificationCodeRepository(self.store),email_provider=self.mail);self.repo=SQLiteUserRepository(self.store);self.patcher=patch.object(auth_route,'_new_services',side_effect=self.services);self.patcher.start();self.client=TestClient(app)
 def tearDown(self):self.patcher.stop();self.store.close();self.tmp.cleanup()
 def services(self):
  store=AuthStore(self.db_path);mail=MockEmailProvider();return store,SQLiteUserRepository(store),VerificationCodeService(VerificationCodeRepository(store),email_provider=mail)
 def issue(self,email):self.verification.issue(email);return self.mail.sent[-1][1]
 def test_register_success_consumes_code_and_returns_safe_user(self):
  code=self.issue('User@Example.com');r=self.client.post('/api/auth/register',json={'username':'alice','email':'USER@example.com','password':'correct horse','verification_code':code});self.assertEqual(r.status_code,201);body=r.json();self.assertEqual(body['email'],'user@example.com');self.assertTrue(body['email_verified']);self.assertEqual(body['status'],'active');self.assertNotIn('password',body);self.assertNotIn('password_hash',body);self.assertNotIn('verification_code',body);u=self.repo.get_by_email('user@example.com');self.assertIsNotNone(u);self.assertNotEqual(u.password_hash,'correct horse');self.assertIsNone(self.verification.repository.current('user@example.com',__import__('app.auth',fromlist=['VerificationPurpose']).VerificationPurpose.REGISTRATION,__import__('datetime').datetime.now(__import__('datetime').timezone.utc)))
 def test_invalid_code_and_duplicate_user(self):
  r=self.client.post('/api/auth/register',json={'username':'alice','email':'a@example.com','password':'correct horse','verification_code':'000000'});self.assertEqual(r.status_code,400)
  code=self.issue('a@example.com');self.client.post('/api/auth/register',json={'username':'alice','email':'a@example.com','password':'correct horse','verification_code':code});code2=self.issue('b@example.com');r=self.client.post('/api/auth/register',json={'username':'alice','email':'b@example.com','password':'correct horse','verification_code':code2});self.assertEqual(r.status_code,409)
 def test_no_membership_is_created(self):
  code=self.issue('x@example.com');r=self.client.post('/api/auth/register',json={'username':'x','email':'x@example.com','password':'correct horse','verification_code':code});self.assertEqual(r.status_code,201);rows=self.store._connection.execute('SELECT * FROM project_memberships').fetchall();self.assertEqual(rows,[])
 def test_required_fields(self):
  for field in ('username','email','password'):
   payload={'username':'a','email':'a@example.com','password':'correct horse','verification_code':'000000'};payload.pop(field);self.assertEqual(self.client.post('/api/auth/register',json=payload).status_code,422)
 def test_register_without_verification_code_can_login(self):
  response=self.client.post('/api/auth/register',json={'username':'new-user','email':'new@example.com','password':'correct horse'})
  self.assertEqual(response.status_code,201)
  user=self.repo.get_by_username('new-user')
  self.assertIsNotNone(user)
  self.assertNotEqual(user.password_hash,'correct horse')
  with patch.dict(os.environ,{'ACCESS_TOKEN_SECRET':'test-secret-for-register-'+'x'*32}):
   login=self.client.post('/api/auth/login',json={'identifier':'new-user','password':'correct horse'})
  self.assertEqual(login.status_code,200)
  self.assertTrue(login.json()['access_token'])
 def test_duplicate_email_is_rejected(self):
  first=self.client.post('/api/auth/register',json={'username':'first','email':'same@example.com','password':'correct horse'})
  self.assertEqual(first.status_code,201)
  duplicate=self.client.post('/api/auth/register',json={'username':'second','email':'SAME@example.com','password':'correct horse'})
  self.assertEqual(duplicate.status_code,409)
  self.assertIsNone(self.repo.get_by_username('second'))
 def test_short_password_is_rejected(self):
  response=self.client.post('/api/auth/register',json={'username':'short','email':'short@example.com','password':'short'})
  self.assertEqual(response.status_code,422)
  self.assertIsNone(self.repo.get_by_username('short'))
 def test_route_uses_injected_isolated_services(self):
  code=self.issue('isolated@example.com')
  with patch('app.api.routes.auth._new_services',side_effect=self.services):
   r=self.client.post('/api/auth/register',json={'username':'iso','email':'isolated@example.com','password':'correct horse','verification_code':code})
  self.assertEqual(r.status_code,201)
if __name__=='__main__':unittest.main()



