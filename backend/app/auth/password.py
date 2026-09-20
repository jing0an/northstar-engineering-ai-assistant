"""Dependency-free password hashing service."""
from __future__ import annotations
import base64,hashlib,hmac,os
from abc import ABC,abstractmethod
class PasswordHasher(ABC):
 @abstractmethod
 def hash(self,password:str)->str: ...
 @abstractmethod
 def verify(self,password:str,password_hash:str)->bool: ...
class PBKDF2PasswordHasher(PasswordHasher):
 algorithm="pbkdf2_sha256"; iterations=310000; salt_bytes=16; digest_bytes=32; min_length=8
 def _password_bytes(self,password:str)->bytes:
  if not isinstance(password,str) or len(password)<self.min_length or not password.strip(): raise ValueError("password must be at least 8 characters")
  return password.encode("utf-8")
 def hash(self,password:str)->str:
  raw=self._password_bytes(password); salt=os.urandom(self.salt_bytes); digest=hashlib.pbkdf2_hmac("sha256",raw,salt,self.iterations,dklen=self.digest_bytes)
  return f"{self.algorithm}${self.iterations}${base64.urlsafe_b64encode(salt).decode('ascii')}${base64.urlsafe_b64encode(digest).decode('ascii')}"
 def verify(self,password:str,password_hash:str)->bool:
  if not isinstance(password,str) or not password or not isinstance(password_hash,str): return False
  try:
   algorithm,iterations,salt_text,digest_text=password_hash.split("$",3)
   if algorithm!=self.algorithm: return False
   rounds=int(iterations)
   if rounds<=0: return False
   salt=base64.urlsafe_b64decode(salt_text.encode("ascii")); expected=base64.urlsafe_b64decode(digest_text.encode("ascii"))
   actual=hashlib.pbkdf2_hmac("sha256",password.encode("utf-8"),salt,rounds,dklen=len(expected))
   return hmac.compare_digest(actual,expected)
  except (ValueError,TypeError,UnicodeError): return False
