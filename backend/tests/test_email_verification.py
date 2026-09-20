import tempfile,unittest
from datetime import datetime,timezone,timedelta
from app.auth import AuthStore,MockEmailProvider,VerificationCodeRepository,VerificationCodeService,VerificationInvalidError,VerificationRateLimitedError,VerificationStatus
class VerificationTest(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.store=AuthStore(self.tmp.name+'/auth.sqlite3');self.mail=MockEmailProvider();self.repo=VerificationCodeRepository(self.store);self.service=VerificationCodeService(self.repo,email_provider=self.mail)
 def tearDown(self):self.store.close();self.tmp.cleanup()
 def test_generation_and_hash_storage(self):
  item=self.service.issue('User@Example.com',now=datetime(2026,1,1,tzinfo=timezone.utc));self.assertEqual(item.email,'user@example.com');self.assertEqual(len(self.mail.sent[0][1]),6);self.assertTrue(self.mail.sent[0][1].isdigit());self.assertNotIn(self.mail.sent[0][1],item.code_hash)
  with self.store.transaction() as c:row=c.execute('SELECT code_hash FROM email_verification_codes').fetchone();self.assertNotEqual(row['code_hash'],self.mail.sent[0][1])
 def test_correct_code_consumes_once(self):
  now=datetime(2026,1,1,tzinfo=timezone.utc);self.service.issue('a@example.com',now=now);code=self.mail.sent[-1][1];self.assertTrue(self.service.verify('A@EXAMPLE.COM',code,now=now+timedelta(seconds=1)))
  with self.assertRaises(VerificationInvalidError):self.service.verify('a@example.com',code,now=now+timedelta(seconds=2))
 def test_wrong_code_locks_after_five(self):
  now=datetime(2026,1,1,tzinfo=timezone.utc);self.service.issue('a@example.com',now=now)
  for _ in range(5):
   with self.assertRaises(VerificationInvalidError):self.service.verify('a@example.com','000000',now=now+timedelta(seconds=1))
  with self.store.transaction() as c:status=c.execute("SELECT status FROM email_verification_codes").fetchone()['status'];self.assertEqual(status,'locked')
 def test_expired_and_cooldown_and_old_code(self):
  now=datetime(2026,1,1,tzinfo=timezone.utc);self.service.issue('a@example.com',now=now)
  with self.assertRaises(VerificationRateLimitedError):self.service.issue('A@EXAMPLE.COM',now=now+timedelta(seconds=30))
  old=self.mail.sent[-1][1];new_time=now+timedelta(seconds=61);self.service.issue('a@example.com',now=new_time);new=self.mail.sent[-1][1]
  with self.assertRaises(VerificationInvalidError):self.service.verify('a@example.com',old,now=new_time)
  self.assertTrue(self.service.verify('a@example.com',new,now=new_time))
 def test_different_emails_are_isolated_and_utc(self):
  now=datetime(2026,1,1,tzinfo=timezone.utc);a=self.service.issue('a@example.com',now=now);b=self.service.issue('b@example.com',now=now);self.assertNotEqual(a.verification_id,b.verification_id);self.assertEqual(a.created_at.tzinfo,timezone.utc)
 def test_errors_do_not_contain_code(self):
  now=datetime(2026,1,1,tzinfo=timezone.utc);self.service.issue('a@example.com',now=now)
  try:self.service.verify('a@example.com','111111',now=now)
  except VerificationInvalidError as error:self.assertNotIn('111111',str(error))
if __name__=='__main__':unittest.main()
