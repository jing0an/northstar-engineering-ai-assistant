from __future__ import annotations
import base64,hashlib,hmac,secrets
from datetime import datetime,timedelta,timezone
from uuid import UUID
from .models import EmailVerificationCode,VerificationPurpose,VerificationStatus
class EmailVerificationError(Exception): pass
class VerificationRateLimitedError(EmailVerificationError): pass
class VerificationInvalidError(EmailVerificationError): pass
class EmailProvider:
 def send_verification_code(self,email:str,code:str)->None: raise NotImplementedError
class MockEmailProvider(EmailProvider):
 def __init__(self):self.sent=[]
 def send_verification_code(self,email,code):self.sent.append((email,code))
class VerificationCodeRepository:
 def __init__(self,store):self.store=store
 @staticmethod
 def _iso(v):return v.astimezone(timezone.utc).isoformat()
 @staticmethod
 def _from(r):return EmailVerificationCode(verification_id=UUID(r['verification_id']),email=r['email'],purpose=r['purpose'],code_hash=r['code_hash'],expires_at=datetime.fromisoformat(r['expires_at']),created_at=datetime.fromisoformat(r['created_at']),consumed_at=datetime.fromisoformat(r['consumed_at']) if r['consumed_at'] else None,failed_attempts=r['failed_attempts'],status=r['status'])
 def invalidate_active(self,email,purpose):
  with self.store.transaction() as c:c.execute("UPDATE email_verification_codes SET status='expired' WHERE email=? AND purpose=? AND status='active'",(email.casefold(),purpose.value))
 def create(self,item):
  with self.store.transaction() as c:c.execute("INSERT INTO email_verification_codes VALUES (?,?,?,?,?,?,?,?,?)",(str(item.verification_id),item.email,item.purpose.value,item.code_hash,self._iso(item.expires_at),self._iso(item.created_at),None,item.failed_attempts,item.status.value))
  return item
 def current(self,email,purpose,now):
  with self.store.transaction() as c:r=c.execute("SELECT * FROM email_verification_codes WHERE email=? AND purpose=? AND status='active' ORDER BY created_at DESC LIMIT 1",(email.casefold(),purpose.value)).fetchone()
  if not r:return None
  item=self._from(r)
  if item.expires_at<=now:
   with self.store.transaction() as c:c.execute("UPDATE email_verification_codes SET status='expired' WHERE verification_id=?",(str(item.verification_id),))
   return None
  return item
 def mark_consumed(self,vid,when):
  with self.store.transaction() as c:c.execute("UPDATE email_verification_codes SET status='consumed',consumed_at=? WHERE verification_id=? AND status='active'",(self._iso(when),str(vid)))
 def fail(self,vid,attempts):
  status='locked' if attempts>=5 else 'active'
  with self.store.transaction() as c:c.execute("UPDATE email_verification_codes SET failed_attempts=?,status=? WHERE verification_id=? AND status='active'",(attempts,status,str(vid)))
class _CodeHasher:
 iterations=120000
 def hash(self,code):
  salt=secrets.token_bytes(16)
  digest=hashlib.pbkdf2_hmac("sha256",code.encode("utf-8"),salt,self.iterations,dklen=32)
  return "pbkdf2_sha256$%d$%s$%s"%(self.iterations,base64.urlsafe_b64encode(salt).decode("ascii"),base64.urlsafe_b64encode(digest).decode("ascii"))
 def verify(self,code,digest):
  try:
   algorithm,rounds,salt_text,expected_text=digest.split("$",3)
   if algorithm!="pbkdf2_sha256":return False
   salt=base64.urlsafe_b64decode(salt_text.encode("ascii"));expected=base64.urlsafe_b64decode(expected_text.encode("ascii"))
   actual=hashlib.pbkdf2_hmac("sha256",code.encode("utf-8"),salt,int(rounds),dklen=len(expected))
   return hmac.compare_digest(actual,expected)
  except (ValueError,TypeError,UnicodeError):return False
class VerificationCodeService:
 def __init__(self,repository,hasher=None,email_provider=None,ttl_seconds=600,cooldown_seconds=60,max_attempts=5):self.repository=repository;self.hasher=hasher or _CodeHasher();self.email_provider=email_provider or MockEmailProvider();self.ttl_seconds=ttl_seconds;self.cooldown_seconds=cooldown_seconds;self.max_attempts=max_attempts
 @staticmethod
 def _email(email):
  value=email.strip().casefold()
  if not value or not all(value.count(x)==1 for x in '@') or '.' not in value.split('@')[-1]:raise ValueError('email must be valid')
  return value
 def issue(self,email,purpose=VerificationPurpose.REGISTRATION,now=None):
  email=self._email(email);purpose=VerificationPurpose(purpose);now=now or datetime.now(timezone.utc);existing=self.repository.current(email,purpose,now)
  if existing and (now-existing.created_at).total_seconds()<self.cooldown_seconds:raise VerificationRateLimitedError('verification requests are temporarily limited')
  self.repository.invalidate_active(email,purpose);code=f'{secrets.randbelow(1000000):06d}';item=EmailVerificationCode(email=email,purpose=purpose,code_hash=self.hasher.hash(code),expires_at=now+timedelta(seconds=self.ttl_seconds),created_at=now);self.repository.create(item);self.email_provider.send_verification_code(email,code);return item
 def verify(self,email,code,purpose=VerificationPurpose.REGISTRATION,now=None):
  email=self._email(email);purpose=VerificationPurpose(purpose);now=now or datetime.now(timezone.utc);item=self.repository.current(email,purpose,now)
  if not item:raise VerificationInvalidError('verification code is invalid')
  if not isinstance(code,str) or len(code.strip())!=6 or not code.strip().isdigit() or not hmac.compare_digest(code,code.strip()):self._fail(item);raise VerificationInvalidError('verification code is invalid')
  if not self.hasher.verify(code.strip(),item.code_hash):self._fail(item);raise VerificationInvalidError('verification code is invalid')
  self.repository.mark_consumed(item.verification_id,now);return True
 def _fail(self,item):self.repository.fail(item.verification_id,item.failed_attempts+1)



