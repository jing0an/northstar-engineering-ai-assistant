"""JWT access-token service with explicit environment configuration."""
from __future__ import annotations
import os
from datetime import datetime,timedelta,timezone
from uuid import UUID,uuid4
import jwt
from jwt import ExpiredSignatureError,InvalidTokenError
class TokenConfigurationError(RuntimeError): pass
class AccessTokenError(ValueError): pass
class AccessTokenService:
 algorithm="HS256"; token_type="access"
 def __init__(self,secret=None,expire_minutes=None):
  self.secret=secret or os.getenv("ACCESS_TOKEN_SECRET")
  if not self.secret or len(self.secret)<32:raise TokenConfigurationError("ACCESS_TOKEN_SECRET must be set to a sufficiently strong secret")
  raw=expire_minutes if expire_minutes is not None else os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES","60")
  try:self.expire_minutes=int(raw)
  except (TypeError,ValueError) as error:raise TokenConfigurationError("ACCESS_TOKEN_EXPIRE_MINUTES must be a positive integer") from error
  if self.expire_minutes<=0:raise TokenConfigurationError("ACCESS_TOKEN_EXPIRE_MINUTES must be a positive integer")
 def create_access_token(self,user_id:UUID|str)->str:
  try:subject=str(UUID(str(user_id)))
  except (ValueError,TypeError) as error:raise ValueError("user_id must be a valid UUID") from error
  now=datetime.now(timezone.utc)
  claims={"sub":subject,"iat":now,"exp":now+timedelta(minutes=self.expire_minutes),"jti":str(uuid4()),"typ":self.token_type}
  return jwt.encode(claims,self.secret,algorithm=self.algorithm)
 def decode_access_token(self,token:str)->dict[str,object]:
  if not isinstance(token,str) or not token.strip():raise AccessTokenError("Invalid access token")
  try:
   claims=jwt.decode(token,self.secret,algorithms=[self.algorithm],options={"require":["sub","iat","exp","jti","typ"]})
  except ExpiredSignatureError as error:raise AccessTokenError("Invalid access token") from error
  except InvalidTokenError as error:raise AccessTokenError("Invalid access token") from error
  if claims.get("typ")!=self.token_type:raise AccessTokenError("Invalid access token")
  try:UUID(str(claims["sub"]))
  except (KeyError,ValueError,TypeError) as error:raise AccessTokenError("Invalid access token") from error
  if not isinstance(claims.get("jti"),str) or not claims["jti"]:raise AccessTokenError("Invalid access token")
  return claims
 verify_access_token=decode_access_token
