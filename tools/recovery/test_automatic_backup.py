"""Synthetic setup and refresh tests; no real runtime files or account actions."""
from pathlib import Path
import copy,json,os,secrets,stat,subprocess,sys,tempfile,unittest
from unittest.mock import patch
import auto_envelope as a
import automatic_backup as w
import migration as m
import recovery_core as r

class WatcherTests(unittest.TestCase):
 def test_health_publication_retries_without_stopping_snapshot_handling(self):
  for error in (OSError,r.RecoveryError):
   with self.subTest(error=error.__name__),tempfile.TemporaryDirectory(prefix='DUMMY-only-watcher-') as directory:
    root=Path(directory);(root/'outbox').mkdir(mode=0o700)
    original=w.atomic_json;attempts=[];written=[]
    def publish_health(path,name,value):
     self.assertEqual((path,name),(root,'health.json'))
     status=value['status'];attempts.append(status)
     if status=='snapshot_blocked' and attempts.count(status)==1:
      raise error('synthetic health publication failure')
     original(path,name,value);written.append(status)
    operations=[subprocess.CompletedProcess([],code) for code in (1,1,0)]
    with patch.object(w,'load_config',return_value={}),patch.object(w,'source_stamps',return_value=('DUMMY-stamp',)) as polls,patch.object(w.subprocess,'run',side_effect=operations) as snapshot,patch.object(w,'atomic_json',side_effect=publish_health),patch.object(w.time,'sleep',side_effect=[None,None,None,None,KeyboardInterrupt]) as sleep,patch('builtins.print') as output:
     with self.assertRaises(KeyboardInterrupt):w._watch_loop(root,interval=0.01)
    self.assertEqual(polls.call_count,5)
    self.assertEqual(snapshot.call_count,3)
    self.assertEqual(sleep.call_count,5)
    self.assertEqual(attempts,['watching','snapshot_blocked','snapshot_blocked','encrypted_snapshot_pending_upload','watching'])
    self.assertEqual(written,['watching','snapshot_blocked','encrypted_snapshot_pending_upload','watching'])
    self.assertEqual([call.args[0] for call in output.call_args_list],written)
    self.assertEqual(json.loads((root/'health.json').read_bytes())['status'],'watching')

 def test_unexpected_health_publication_error_propagates(self):
  with patch.object(w,'load_config',return_value={}),patch.object(w,'source_stamps',return_value=('DUMMY-stamp',)),patch.object(w,'atomic_json',side_effect=RuntimeError('synthetic unexpected error')),patch.object(w.time,'sleep') as sleep:
   with self.assertRaisesRegex(RuntimeError,'synthetic unexpected error'):w._watch_loop(Path('/DUMMY-only-watcher'),interval=0.01)
  sleep.assert_not_called()

class SnapshotTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.password=secrets.token_urlsafe(32)
  cls.recipient=a.create_recipient(cls.password)
  cls.pin=a.recipient_digest(cls.recipient)
 @classmethod
 def config(cls,env,auth):return {'format':'discord-autobackup-config','version':1,'env_path':str(env),'auth_path':str(auth),'recipient_sha256':cls.pin}
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='DUMMY-only-auto-');self.root=Path(self.temp.name)
  self.env=self.root/'DUMMY-env';self.auth=self.root/'DUMMY-auth';self.state=self.root/'state'
  self.env.write_bytes(b'DUMMY_ONLY=1\n');self.auth.write_bytes(b'{"dummy_only":true,"revision":1}\n')
  self.state.mkdir(mode=0o700);(self.state/'outbox').mkdir(mode=0o700)
  (self.state/'recipient.json').write_bytes(self.recipient)
  self.cfg=self.config(self.env,self.auth);w.atomic_json(self.state,'watcher-config.json',self.cfg)
 def tearDown(self):self.temp.cleanup()
 def test_initial_and_refreshed_snapshots_restore(self):
  first,_=w.publish_snapshot(self.state)
  self.auth.write_bytes(b'{"dummy_only":true,"revision":2}\n')
  second,_=w.publish_snapshot(self.state)
  self.assertEqual((first['sequence'],second['sequence']),(1,2))
  self.assertNotEqual(first['file_name'],second['file_name'])
  latest=w.read_manifest(self.state/'outbox',self.pin);self.assertEqual(latest,second)
  raw=(self.state/'outbox'/second['file_name']).read_bytes()
  self.assertEqual(r.decrypt(raw,self.password)['codex/auth.json'],self.auth.read_bytes())
  target=self.root/'restored';r.restore(self.state/'outbox'/second['file_name'],target,self.password)
  self.assertEqual((target/'codex/auth.json').read_bytes(),self.auth.read_bytes())
  self.assertEqual(stat.S_IMODE((target/'codex/auth.json').stat().st_mode),0o600)
 def test_missing_configured_auth_blocks_without_downgrade(self):
  self.auth.unlink()
  with self.assertRaises(FileNotFoundError):w.publish_snapshot(self.state)
  self.assertFalse((self.state/'outbox/latest.json').exists())
 def test_invalid_auth_json_blocks(self):
  for data in (b'{}',b'[]',b'not json'):
   self.auth.write_bytes(data)
   with self.assertRaises(r.RecoveryError):w.publish_snapshot(self.state)
 def test_source_symlink_blocks(self):
  self.auth.unlink();self.auth.symlink_to(self.env)
  with self.assertRaises(r.RecoveryError):w.publish_snapshot(self.state)
 def test_atomic_path_replacement_during_capture_blocks(self):
  original=r.read_bounded;calls=0
  def swapping(path,limit):
   nonlocal calls
   raw=original(path,limit)
   if Path(path)==self.auth:
    calls+=1
    if calls==1:
     replacement=self.root/'DUMMY-new';replacement.write_bytes(b'{"dummy_only":true,"revision":2}')
     os.replace(replacement,self.auth)
   return raw
  with patch.object(r,'read_bounded',side_effect=swapping),self.assertRaises(r.RecoveryError):w.capture_consistent(self.cfg)
 def test_whole_set_content_change_between_reads_blocks(self):
  original=w._capture;calls=0
  def changing(config):
   nonlocal calls
   files,stamps=original(config);calls+=1
   if calls==1:self.env.write_bytes(b'DUMMY_CHANGED=1\n')
   return files,stamps
  with patch.object(w,'_capture',side_effect=changing),self.assertRaises(r.RecoveryError):w.capture_consistent(self.cfg)
 def test_manifest_failure_leaves_only_immutable_ciphertext(self):
  with patch.object(w,'atomic_json',side_effect=OSError('synthetic publication failure')),self.assertRaises(OSError):w.publish_snapshot(self.state)
  self.assertFalse((self.state/'outbox/latest.json').exists())
  found=list((self.state/'outbox').glob('snapshot-*.encrypted.json'));self.assertEqual(len(found),1)
  self.assertEqual(a.decrypt_snapshot(found[0].read_bytes(),self.password)['.env'],self.env.read_bytes())
 def test_single_writer_lock(self):
  with w.writer_lock(self.state/'outbox'):
   with self.assertRaises(r.RecoveryError):w.publish_snapshot(self.state)
 def test_recipient_pin_change_blocks(self):
  cfg={**self.cfg,'recipient_sha256':'0'*64};w.atomic_json(self.state,'watcher-config.json',cfg)
  with self.assertRaises(r.RecoveryError):w.publish_snapshot(self.state)
 def test_symlink_outbox_blocks(self):
  (self.state/'outbox').rmdir();(self.state/'outbox').symlink_to(self.root,target_is_directory=True)
  with self.assertRaises(OSError):w.publish_snapshot(self.state)
 def test_one_time_migration_with_existing_password(self):
  legacy=self.root/'DUMMY-existing-v2.enc';legacy.write_bytes(r.encrypt({'.env':self.env.read_bytes(),'codex/auth.json':self.auth.read_bytes()},self.password))
  destination=self.root/'setup'
  plan={'format':'discord-autobackup-setup-plan','version':1,'env_path':str(self.env),'auth_path':str(self.auth),'existing_backup_path':str(legacy),'destination_root':str(destination),'library_file_id':'libfile_DUMMYTESTONLY','library_version':0}
  result=m.setup_state(plan,self.password)
  self.assertTrue(result['durability_confirmed'])
  manifest=w.read_manifest(destination/'outbox',result['recipient_sha256'])
  raw=(destination/'outbox'/manifest['file_name']).read_bytes()
  self.assertEqual(r.decrypt(raw,self.password)['codex/auth.json'],self.auth.read_bytes())
  for file in destination.rglob('*'):
   if file.is_file():self.assertNotIn(self.password.encode(),file.read_bytes())
  with self.assertRaises(r.RecoveryError):m.setup_state(plan,self.password)
 def test_first_setup_goes_directly_to_v3_without_v2(self):
  destination=self.root/'direct-v3'
  plan={'format':'discord-autobackup-setup-plan','version':1,'env_path':str(self.env),'auth_path':str(self.auth),'existing_backup_path':None,'destination_root':str(destination),'library_file_id':'libfile_DUMMYTESTONLY','library_version':0}
  with patch.object(r,'decrypt',side_effect=AssertionError('first setup must not use v2')):
   result=m.setup_state(plan,self.password)
  manifest=w.read_manifest(destination/'outbox',result['recipient_sha256'])
  raw=(destination/'outbox'/manifest['file_name']).read_bytes()
  self.assertEqual(json.loads(raw)['version'],3)
  self.assertEqual(a.decrypt_snapshot(raw,self.password)['.env'],self.env.read_bytes())
 def test_first_setup_can_bind_first_created_library_version_zero(self):
  import transport
  destination=self.root/'direct-unbound'
  plan={'format':'discord-autobackup-setup-plan','version':1,'env_path':str(self.env),'auth_path':str(self.auth),'existing_backup_path':None,'destination_root':str(destination),'library_file_id':None,'library_version':None}
  result=m.setup_state(plan,self.password)
  self.assertEqual(result['status'],'setup_ready_for_initial_library_binding')
  self.assertFalse((destination/'bridge-state.json').exists())
  manifest=w.read_manifest(destination/'outbox',result['recipient_sha256'])
  prepared=m.prepare_created_library(destination)
  self.assertEqual(prepared['snapshot_id'],manifest['snapshot_id'])
  self.assertEqual(Path(prepared['file']).name,'discord-backup.encrypted.json')
  response={'operation':'create_library_file','status':'succeeded','library_file_id':'libfile_DUMMYTESTONLY','current_version_number':0,'file_size_bytes':manifest['size_bytes']}
  confirmation=m.bind_created_library(destination,response)
  self.assertEqual(confirmation['library_version'],0)
  self.assertEqual(transport.prepare(destination)['status'],'noop')
  with self.assertRaises(r.RecoveryError):m.bind_created_library(destination,response)
 def test_first_setup_rejects_unconfirmed_library_create(self):
  destination=self.root/'direct-unbound-reject'
  plan={'format':'discord-autobackup-setup-plan','version':1,'env_path':str(self.env),'auth_path':str(self.auth),'existing_backup_path':None,'destination_root':str(destination),'library_file_id':None,'library_version':None}
  m.setup_state(plan,self.password)
  with self.assertRaises(r.RecoveryError):m.bind_created_library(destination,{'status':'failed'})
  self.assertFalse((destination/'bridge-state.json').exists())
 def test_wrong_migration_password_creates_nothing(self):
  legacy=self.root/'DUMMY-v2.enc';legacy.write_bytes(r.encrypt({'.env':b'DUMMY=1'},self.password))
  destination=self.root/'setup'
  plan={'format':'discord-autobackup-setup-plan','version':1,'env_path':str(self.env),'auth_path':str(self.auth),'existing_backup_path':str(legacy),'destination_root':str(destination),'library_file_id':'libfile_DUMMYTESTONLY','library_version':0}
  with self.assertRaises(r.RecoveryError):m.setup_state(plan,secrets.token_urlsafe(32))
  self.assertFalse(destination.exists())

 def unbound_setup(self):
  destination=self.root/'direct-first-upload'
  plan={'format':'discord-autobackup-setup-plan','version':1,'env_path':str(self.env),'auth_path':str(self.auth),'existing_backup_path':None,'destination_root':str(destination),'library_file_id':None,'library_version':None}
  m.setup_state(plan,self.password)
  prepared=m.prepare_created_library(destination)
  response={'operation':'create_library_file','status':'succeeded','library_file_id':'libfile_DUMMYTESTONLY','current_version_number':0,'file_size_bytes':prepared['size_bytes']}
  return destination,prepared,response

 def test_initial_binding_pins_original_when_latest_advances(self):
  import transport
  destination,prepared,response=self.unbound_setup()
  self.auth.write_bytes(b'{"dummy_only":true,"revision":2}\n')
  newer,_=w.publish_snapshot(destination)
  self.assertEqual(newer['size_bytes'],prepared['size_bytes'])
  self.assertNotEqual(newer['snapshot_id'],prepared['snapshot_id'])
  bound=m.bind_created_library(destination,response)
  self.assertEqual(bound['snapshot_id'],prepared['snapshot_id'])
  pending=transport.prepare(destination)
  self.assertEqual(pending['status'],'ready')
  self.assertEqual(pending['snapshot_id'],newer['snapshot_id'])

 def test_initial_ciphertext_tampering_blocks_binding(self):
  destination,prepared,response=self.unbound_setup()
  path=Path(prepared['file']);data=path.read_bytes();path.write_bytes(data[:-2]+b'xx')
  with self.assertRaises(r.RecoveryError):m.bind_created_library(destination,response)
  self.assertFalse((destination/'bridge-state.json').exists())

 def test_initial_manifest_tampering_blocks_binding(self):
  destination,prepared,response=self.unbound_setup()
  manifest=json.loads((destination/'initial-snapshot.json').read_bytes());manifest['sha256']='0'*64
  (destination/'initial-snapshot.json').write_bytes(r._json(manifest))
  with self.assertRaises(r.RecoveryError):m.bind_created_library(destination,response)
  self.assertFalse((destination/'bridge-state.json').exists())

 def test_initial_error_flags_and_wrong_metadata_block_binding(self):
  destination,prepared,response=self.unbound_setup()
  for change in ({'isError':True},{'isError':0},{'error':''},{'errors':[]},{'error':'synthetic failure'},{'errors':['synthetic failure']},{'current_version_number':True},{'current_version_number':-1},{'current_version_number':1},{'file_size_bytes':True}):
   with self.subTest(change=change),self.assertRaises(r.RecoveryError):m.bind_created_library(destination,{**response,**change})
  self.assertFalse((destination/'bridge-state.json').exists())

 def test_initial_binding_cli_accepts_only_bounded_create_response(self):
  destination,prepared,response=self.unbound_setup()
  script=str(Path(m.__file__))
  result=subprocess.run([sys.executable,script,'prepare-created',str(destination)],capture_output=True,text=True,check=True)
  self.assertEqual(json.loads(result.stdout),prepared)
  oversized=subprocess.run([sys.executable,script,'bind-created',str(destination)],input=b'x'*(1024*1024+1),capture_output=True)
  self.assertEqual(oversized.returncode,2)
  self.assertFalse((destination/'bridge-state.json').exists())
  bound=subprocess.run([sys.executable,script,'bind-created',str(destination)],input=r._json(response),capture_output=True,check=True)
  self.assertEqual(json.loads(bound.stdout)['snapshot_id'],prepared['snapshot_id'])

if __name__=='__main__':unittest.main(verbosity=2)
