"""Public synthetic data only; fresh runtime-only test password and keys."""
import copy,json,secrets,unittest
from unittest.mock import patch
import auto_envelope as a
import recovery_core as r

class EnvelopeTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.password=secrets.token_urlsafe(32)
  cls.recipient=a.create_recipient(cls.password)
  cls.pin=a.recipient_digest(cls.recipient)
  cls.files={'.env':b'DUMMY_ONLY=1\n','codex/auth.json':b'{"dummy_only":true,"revision":1}\n'}
  cls.raw=a.encrypt_snapshot(cls.files,cls.recipient,cls.pin)
  cls.package=json.loads(cls.raw)
 def test_roundtrip(self):
  self.assertEqual(a.decrypt_snapshot(self.raw,self.password),self.files)
 def test_no_password_required_for_updated_auth(self):
  updated={**self.files,'codex/auth.json':b'{"dummy_only":true,"revision":2}\n'}
  with patch.object(a,'create_recipient',side_effect=AssertionError('must not create keys')):
   raw=a.encrypt_snapshot(updated,self.recipient,self.pin,sequence=2)
  self.assertEqual(a.decrypt_snapshot(raw,self.password),updated)
  newer=json.loads(raw)
  for name in ('nonce','wrapped_key','snapshot_id','ciphertext_and_tag'):
   self.assertNotEqual(newer[name],self.package[name])
  self.assertEqual(newer['recipient'],self.package['recipient'])
 def test_wrong_password(self):
  with self.assertRaises(r.RecoveryError):a.decrypt_snapshot(self.raw,secrets.token_urlsafe(32))
 def test_recipient_pin_substitution(self):
  replacement=a.create_recipient(secrets.token_urlsafe(32))
  with self.assertRaises(r.RecoveryError):a.encrypt_snapshot(self.files,replacement,self.pin)
 def test_every_header_mutation_rejected(self):
  cases={'format':'other','version':True,'algorithm':'other','created_at':'2025-01-01T00:00:00Z','snapshot_id':'00000000-0000-4000-8000-000000000000','sequence':2,'nonce':r._b64(bytes(12)),'wrapped_key':r._b64(bytes(384))}
  for name,value in cases.items():
   with self.subTest(field=name),self.assertRaises(r.RecoveryError):a.decrypt_snapshot(r._json({**self.package,name:value}),self.password)
 def test_ciphertext_and_wrapper_tampering(self):
  for mode in ('ciphertext','wrapper'):
   changed=copy.deepcopy(self.package)
   target=changed if mode=='ciphertext' else changed['recipient']['recovery']
   field='ciphertext_and_tag' if mode=='ciphertext' else 'encrypted_private_key'
   value=bytearray(r._unb64(target[field],r.MAX_PACKAGE));value[0]^=1;target[field]=r._b64(bytes(value))
   with self.assertRaises(r.RecoveryError):a.decrypt_snapshot(r._json(changed),self.password)
 def test_invalid_costs_rejected_before_kdf(self):
  changed=copy.deepcopy(self.package);changed['recipient']['recovery']['kdf']['n']=2**30
  with patch.object(r,'Scrypt',side_effect=AssertionError('must not derive')),self.assertRaises(r.RecoveryError):a.decrypt_snapshot(r._json(changed),self.password)
 def test_no_plaintext_or_password_in_package(self):
  self.assertNotIn(self.password.encode(),self.raw)
  for value in self.files.values():self.assertNotIn(value,self.raw)
 def test_bounds_duplicate_keys_unknown_fields(self):
  for raw in (self.raw[:-1][:-1]+b',"version":3}',b'x'*(r.MAX_PACKAGE+1),self.raw[:100],r._json({**self.package,'extra':True})):
   with self.assertRaises(r.RecoveryError):a.validate_snapshot(raw)
 def test_path_allowlist(self):
  with self.assertRaises(r.RecoveryError):a.encrypt_snapshot({**self.files,'../auth.json':b'x'},self.recipient,self.pin)
 def test_bool_sequence_rejected(self):
  with self.assertRaises(r.RecoveryError):a.encrypt_snapshot(self.files,self.recipient,self.pin,True)
 def test_recovery_series_substitution(self):
  changed=copy.deepcopy(self.package);changed['recipient']['recovery_series_id']='00000000-0000-4000-8000-000000000000'
  with self.assertRaises(r.RecoveryError):a.decrypt_snapshot(r._json(changed),self.password)

if __name__=='__main__':unittest.main(verbosity=2)
