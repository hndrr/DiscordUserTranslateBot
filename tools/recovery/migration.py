"""One-time setup, invoked only by the user-operated masked-password form."""
import argparse,json,os,re,shutil,stat,sys,uuid
from pathlib import Path
import auto_envelope as a
import automatic_backup as w
import recovery_core as r

PLAN_KEYS={'format','version','env_path','auth_path','existing_backup_path','destination_root','library_file_id','library_version'}


def validate_plan(plan):
 if type(plan)is not dict or set(plan)!=PLAN_KEYS or plan['format']!='discord-autobackup-setup-plan' or type(plan['version'])is not int or plan['version']!=1:
  raise r.RecoveryError('Invalid setup plan.')
 for name in ('env_path','auth_path','destination_root'):
  if type(plan[name])is not str or not Path(plan[name]).is_absolute():raise r.RecoveryError('Setup paths must be explicit and absolute.')
  r._path_parts(plan[name])
 if plan['existing_backup_path'] is not None:
  if type(plan['existing_backup_path'])is not str or not Path(plan['existing_backup_path']).is_absolute():raise r.RecoveryError('Existing backup path must be absolute or null for first setup.')
  r._path_parts(plan['existing_backup_path'])
 if plan['library_file_id'] is None and plan['library_version'] is None and plan['existing_backup_path'] is None:return plan
 if type(plan['library_file_id'])is not str or not re.fullmatch(r'libfile_[A-Za-z0-9]+',plan['library_file_id']) or type(plan['library_version'])is not int or plan['library_version']<0:
  raise r.RecoveryError('Invalid authorized Library identity/version.')
 return plan


def load_plan(path):return validate_plan(r._parse(r.read_bounded(path,8192),8192))


def setup_state(plan,password):
 plan=validate_plan(plan);r._password(password)
 destination=Path(plan['destination_root']);parent,basename=r._parent(destination,private=True)
 temporary='.autobackup-setup-'+uuid.uuid4().hex
 stage=destination.parent/temporary
 made=False
 try:
  r._absent(parent,basename)
  if plan['existing_backup_path'] is not None:
   existing=r.read_bounded(plan['existing_backup_path'],r.MAX_PACKAGE)
   parsed=r._parse(existing,r.MAX_PACKAGE)
   if type(parsed)is not dict or parsed.get('format')!=r.FORMAT or type(parsed.get('version'))is not int or parsed.get('version')!=2:
    raise r.RecoveryError('Migration requires the existing version-2 recovery backup.')
   # Existing users verify their old password. First-time setup skips v2 entirely.
   verified_old=r.decrypt(existing,password)
   del verified_old
  recipient=a.create_recipient(password);pin=a.recipient_digest(recipient)
  config={'format':'discord-autobackup-config','version':1,'env_path':plan['env_path'],'auth_path':plan['auth_path'],'recipient_sha256':pin}
  current,_=w.capture_consistent(config)
  probe=a.encrypt_snapshot(current,recipient,pin)
  if a.decrypt_snapshot(probe,password)!=current:raise r.RecoveryError('Initial recovery self-check failed.')
  del current,probe
  os.mkdir(temporary,0o700,dir_fd=parent);made=True
  fd=w.private_directory(stage)
  try:
   r._write(fd,'recipient.json',recipient)
   os.mkdir('outbox',0o700,dir_fd=fd)
   os.fsync(fd)
  finally:os.close(fd)
  w.atomic_json(stage,'watcher-config.json',config)
  if plan['library_file_id'] is not None:w.atomic_json(stage,'bridge-state.json',{'format':'discord-autobackup-bridge-state','version':1,'library_file_id':plan['library_file_id'],'library_version':plan['library_version'],'last_uploaded_snapshot_id':None,'last_uploaded_sequence':0,'recipient_sha256':pin})
  manifest,_=w.publish_snapshot(stage)
  # Verify the actual published initial bytes, not just a preflight buffer.
  snapshot=r.read_bounded(stage/'outbox'/manifest['file_name'],r.MAX_PACKAGE)
  restored=a.decrypt_snapshot(snapshot,password)
  if set(restored)!={'.env','codex/auth.json'}:raise r.RecoveryError('Initial recovery self-check failed.')
  del restored
  # Pin the first upload independently of latest.json: later snapshots must
  # never be mistaken for the ciphertext sent by the initial Library create.
  fd=w.private_directory(stage)
  try:
   r._write(fd,'initial-snapshot.json',r._json(manifest)+b'\n')
   os.mkdir('initial-upload',0o700,dir_fd=fd)
   upload_fd=w.private_directory(stage/'initial-upload')
   try:
    r._write(upload_fd,'discord-backup.encrypted.json',snapshot)
    os.fsync(upload_fd)
   finally:os.close(upload_fd)
   os.fsync(fd)
  finally:os.close(fd)
  r._rename_new(parent,temporary,basename);made=False
  durable=r._sync_published(parent)
  return {'status':'setup_ready_for_watcher_and_library_bridge' if plan['library_file_id'] is not None else 'setup_ready_for_initial_library_binding','state_directory':str(destination),'recipient_sha256':pin,'snapshot_id':manifest['snapshot_id'],'durability_confirmed':durable}
 finally:
  os.close(parent)
  if made:
   # This newly created private stage contains public/protected keys and
   # ciphertext only, never plaintext source files or the recovery password.
   shutil.rmtree(stage)


def _initial_upload(root):
 from transport import _manifest,_verify_ciphertext,UPLOAD_BASENAME
 config=w.load_config(root)
 manifest=_manifest(r._parse(r.read_bounded(root/'initial-snapshot.json',16384),16384))
 path=root/'initial-upload'/UPLOAD_BASENAME
 fd=w.private_directory(path.parent)
 try:raw=r.read_bounded(path,r.MAX_PACKAGE)
 finally:os.close(fd)
 _verify_ciphertext(raw,manifest,config['recipient_sha256'])
 return manifest,path


def prepare_created_library(state_root):
 """Return the fixed first ciphertext for an externally authorized create."""
 root=Path(*r._path_parts(state_root))
 with w.writer_lock(root):
  if (root/'bridge-state.json').exists() or (root/'upload-receipt.json').exists():
   raise r.RecoveryError('Library binding already exists; no changes made.')
  manifest,path=_initial_upload(root)
  return {'status':'ready_for_initial_create','file':str(path),**{k:manifest[k] for k in ('snapshot_id','sequence','sha256','size_bytes')}}


def bind_created_library(state_root,response):
 """Bind a direct v3 setup to its confirmed first Library create, no decryption.

 Caller passes unchanged create structuredContent after the approved ciphertext
 upload. No content/permission action is performed by this local helper.
 """
 from transport import _state,_receipt
 root=Path(*r._path_parts(state_root))
 with w.writer_lock(root):
  if (root/'bridge-state.json').exists() or (root/'upload-receipt.json').exists():
   raise r.RecoveryError('Library binding already exists; no changes made.')
  manifest,_=_initial_upload(root)
  if type(response)is not dict or response.get('isError',False) is not False or response.get('error') is not None or response.get('errors') is not None or response.get('operation')!='create_library_file' or response.get('status')!='succeeded' or type(response.get('current_version_number'))is not int or response['current_version_number']!=0 or type(response.get('file_size_bytes'))is not int or response['file_size_bytes']!=manifest['size_bytes'] or type(response.get('library_file_id'))is not str or not re.fullmatch(r'libfile_[A-Za-z0-9]+',response['library_file_id']):
   raise r.RecoveryError('Initial Library create was not confirmed; no binding written.')
  state=_state({'format':'discord-autobackup-bridge-state','version':1,'library_file_id':response['library_file_id'],'library_version':0,'last_uploaded_snapshot_id':manifest['snapshot_id'],'last_uploaded_sequence':manifest['sequence'],'recipient_sha256':manifest['recipient_sha256']})
  receipt=_receipt({'format':'discord-autobackup-upload-receipt','version':1,'request_id':str(uuid.uuid4()),'library_file_id':response['library_file_id'],'library_version':0,**{k:manifest[k] for k in ('snapshot_id','sequence','created_at','size_bytes','sha256','recipient_sha256')},'confirmed_at':w.utc_now()})
  fd=w.private_directory(root)
  try:
   r._write(fd,'upload-receipt.json',r._json(receipt)+b'\n')
   r._write(fd,'bridge-state.json',r._json(state)+b'\n')
   os.fsync(fd)
  finally:os.close(fd)
  return {'status':'initial_library_binding_confirmed','library_file_id':response['library_file_id'],'library_version':0,'snapshot_id':manifest['snapshot_id']}


def main(argv=None):
 parser=argparse.ArgumentParser(description='Ciphertext-only first Library binding; no password input.')
 parser.add_argument('action',choices=('prepare-created','bind-created'))
 parser.add_argument('state_root');args=parser.parse_args(argv)
 try:
  if args.action=='prepare-created':result=prepare_created_library(args.state_root)
  else:
   raw=sys.stdin.buffer.read(1024*1024+1)
   result=bind_created_library(args.state_root,r._parse(raw,1024*1024))
  print(r._json(result).decode('ascii'));return 0
 except (r.RecoveryError,OSError):
  print('{"status":"blocked","error":"Initial Library binding did not complete; preserve state and reconcile the exact create before retrying."}',file=sys.stderr)
  return 2


if __name__=='__main__':raise SystemExit(main())
