import tempfile,unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.auth import AuthStore,PBKDF2PasswordHasher,SQLiteUserRepository
import app.api.routes.auth as auth_route

class LoginApiTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.db_path=self.tmp.name+'/auth.sqlite3'
  self.store=AuthStore(self.db_path)
  self.repo=SQLiteUserRepository(self.store)
  self.patcher=patch.object(auth_route,'_new_services',side_effect=self.services)
  self.patcher.start()
  self.client=TestClient(app)

 def tearDown(self):
  self.patcher.stop()
  self.store.close()
  self.tmp.cleanup()

 def services(self):
  store=AuthStore(self.db_path)
  return store,SQLiteUserRepository(store),None

 def create_user(self,username='alice',email='alice@example.com',password='correct horse',email_verified=True,status='active'):
  from app.auth import User,UserStatus
  from datetime import datetime,timezone
  user=User(
   user_id=__import__('uuid').uuid4(),
   username=username,
   email=email,
   password_hash=PBKDF2PasswordHasher().hash(password),
   status=UserStatus(status),
   email_verified=email_verified,
   created_at=datetime.now(timezone.utc),
   updated_at=datetime.now(timezone.utc),
  )
  self.repo.create(user)
  return user

 def test_login_by_username_returns_access_token(self):
  self.create_user()
  with patch.dict('os.environ',{'ACCESS_TOKEN_SECRET':'test-secret-for-login-'+'x'*32}):
   r=self.client.post('/api/auth/login',json={'identifier':'alice','password':'correct horse'})
  self.assertEqual(r.status_code,200)
  body=r.json()
  self.assertTrue(body['access_token'])
  self.assertEqual(body['token_type'],'bearer')
  self.assertGreater(body['expires_in'],0)

 def test_login_by_email_returns_access_token(self):
  self.create_user()
  with patch.dict('os.environ',{'ACCESS_TOKEN_SECRET':'test-secret-for-login-'+'x'*32}):
   r=self.client.post('/api/auth/login',json={'identifier':'ALICE@EXAMPLE.COM','password':'correct horse'})
  self.assertEqual(r.status_code,200)
  self.assertTrue(r.json()['access_token'])

 def test_wrong_password_returns_401(self):
  self.create_user()
  r=self.client.post('/api/auth/login',json={'identifier':'alice','password':'wrong password'})
  self.assertEqual(r.status_code,401)

 def test_unknown_user_returns_401(self):
  r=self.client.post('/api/auth/login',json={'identifier':'nobody','password':'wrong password'})
  self.assertEqual(r.status_code,401)

 def test_unverified_user_returns_401(self):
  self.create_user(email_verified=False)
  r=self.client.post('/api/auth/login',json={'identifier':'alice','password':'correct horse'})
  self.assertEqual(r.status_code,401)

 def test_disabled_user_returns_401(self):
  self.create_user(status='disabled')
  r=self.client.post('/api/auth/login',json={'identifier':'alice','password':'correct horse'})
  self.assertEqual(r.status_code,401)

 def test_missing_required_fields_returns_422(self):
  self.assertEqual(self.client.post('/api/auth/login',json={'password':'correct horse'}).status_code,422)
  self.assertEqual(self.client.post('/api/auth/login',json={'identifier':'alice'}).status_code,422)

if __name__=='__main__':
 unittest.main()
