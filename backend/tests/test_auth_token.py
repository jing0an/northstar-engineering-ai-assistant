import os,unittest
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import jwt
from app.auth.token import AccessTokenError,AccessTokenService,TokenConfigurationError
SECRET='a'*48
class TokenServiceTest(unittest.TestCase):
 def setUp(self):self.service=AccessTokenService(secret=SECRET,expire_minutes=60);self.user_id=uuid4()
 def test_create_decode_claims_and_no_sensitive_data(self):
  token=self.service.create_access_token(self.user_id);claims=self.service.decode_access_token(token);self.assertEqual(claims['sub'],str(self.user_id));self.assertEqual(claims['typ'],'access');self.assertIn('iat',claims);self.assertIn('exp',claims);self.assertIn('jti',claims);self.assertNotIn('password',claims);self.assertNotIn('password_hash',claims);self.assertNotIn('code',claims);self.assertNotIn('BJ-KC-2024-01',token)
 def test_expiration_tampering_and_wrong_secret_fail(self):
  expired=jwt.encode({'sub':str(self.user_id),'iat':datetime.now(timezone.utc)-timedelta(hours=2),'exp':datetime.now(timezone.utc)-timedelta(hours=1),'jti':'x','typ':'access'},SECRET,algorithm='HS256')
  with self.assertRaises(AccessTokenError):self.service.decode_access_token(expired)
  token=self.service.create_access_token(self.user_id);tampered=token[:-1]+('a' if token[-1]!='a' else 'b')
  with self.assertRaises(AccessTokenError):self.service.decode_access_token(tampered)
  wrong=jwt.encode({'sub':str(self.user_id),'iat':datetime.now(timezone.utc),'exp':datetime.now(timezone.utc)+timedelta(minutes=1),'jti':'x','typ':'access'},'b'*48,algorithm='HS256')
  with self.assertRaises(AccessTokenError):self.service.decode_access_token(wrong)
 def test_missing_subject_invalid_format_and_type_fail(self):
  base={'iat':datetime.now(timezone.utc),'exp':datetime.now(timezone.utc)+timedelta(minutes=1),'jti':'x','typ':'access'}
  for claims in (base,{**base,'sub':'not-a-uuid'},{**base,'sub':str(self.user_id),'typ':'refresh'}):
   with self.assertRaises(AccessTokenError):self.service.decode_access_token(jwt.encode(claims,SECRET,algorithm='HS256'))
  with self.assertRaises(AccessTokenError):self.service.decode_access_token('not.a.token')
 def test_secret_required_and_expiry_env(self):
  old=os.environ.pop('ACCESS_TOKEN_SECRET',None)
  try:
   with self.assertRaises(TokenConfigurationError):AccessTokenService()
  finally:
   if old is not None:os.environ['ACCESS_TOKEN_SECRET']=old
  old=os.environ.get('ACCESS_TOKEN_EXPIRE_MINUTES');os.environ['ACCESS_TOKEN_EXPIRE_MINUTES']='5'
  try:self.assertEqual(AccessTokenService(secret=SECRET).expire_minutes,5)
  finally:
   if old is None:os.environ.pop('ACCESS_TOKEN_EXPIRE_MINUTES',None)
   else:os.environ['ACCESS_TOKEN_EXPIRE_MINUTES']=old
if __name__=='__main__':unittest.main()
