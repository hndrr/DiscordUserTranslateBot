"""Local encrypt-only snapshot writer. No network, login or Library credentials."""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import subprocess
import sys
import time
import uuid
import auto_envelope as a
import recovery_core as r

CONFIG_KEYS={'format','version','env_path','auth_path','recipient_sha256'}
MANIFEST_KEYS={'format','version','snapshot_id','sequence','created_at','file_name','size_bytes','sha256','recipient_sha256'}


def utc_now(): return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def private_directory(path):
 fd=r._directory(path)
 info=os.fstat(fd)
 if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077:
  os.close(fd);raise r.RecoveryError('Automatic backup directory must be owner-only.')
 return fd


def atomic_json(directory,name,value):
 if name not in {'latest.json','watcher-config.json','bridge-state.json','health.json'}:
  raise r.RecoveryError('Unsupported control file.')
 fd=private_directory(directory);temporary='.control-'+uuid.uuid4().hex
 try:
  r._write(fd,temporary,r._json(value)+b'\n')
  os.replace(temporary,name,src_dir_fd=fd,dst_dir_fd=fd)
  os.fsync(fd)
 finally:
  try:os.unlink(temporary,dir_fd=fd)
  except FileNotFoundError:pass
  finally:os.close(fd)


@contextlib.contextmanager
def writer_lock(directory):
 parent=private_directory(directory);fd=None
 try:
  fd=os.open('.writer.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=parent)
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077:
   raise r.RecoveryError('Unsafe writer lock.')
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise r.RecoveryError('Another snapshot writer is running.') from None
  yield
 finally:
  if fd is not None:os.close(fd)
  os.close(parent)


def validate_config(value):
 if type(value)is not dict or set(value)!=CONFIG_KEYS or value['format']!='discord-autobackup-config' or type(value['version'])is not int or value['version']!=1:
  raise r.RecoveryError('Invalid automatic backup configuration.')
 for name in ('env_path','auth_path'):
  if type(value[name])is not str or not Path(value[name]).is_absolute():raise r.RecoveryError('Explicit absolute source paths are required.')
  r._path_parts(value[name])
 if type(value['recipient_sha256'])is not str or len(value['recipient_sha256'])!=64 or any(c not in '0123456789abcdef' for c in value['recipient_sha256']):
  raise r.RecoveryError('Invalid pinned recipient digest.')
 return value


def load_config(root):return validate_config(r._parse(r.read_bounded(Path(root)/'watcher-config.json',8192),8192))


def _stamp(info):return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def source_stamps(config):
 stamps=[]
 for name in ('env_path','auth_path'):
  parent,base=r._parent(config[name])
  try:
   info=os.stat(base,dir_fd=parent,follow_symlinks=False)
   if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1:raise r.RecoveryError('Unsafe source file.')
   stamps.append(_stamp(info))
  finally:os.close(parent)
 return tuple(stamps)


def _capture(config):
 # Source identity is checked before and after reading, including pathname inode
 # replacement. Then the entire source set is reopened and compared by caller.
 before=source_stamps(config)
 files={'.env':r.read_bounded(config['env_path'],r.LIMITS['.env']),
        'codex/auth.json':r.read_bounded(config['auth_path'],r.LIMITS['codex/auth.json'])}
 after=source_stamps(config)
 if before!=after:raise r.RecoveryError('Sources changed during snapshot capture.')
 auth=r._parse(files['codex/auth.json'],r.LIMITS['codex/auth.json'])
 if type(auth)is not dict or not auth:raise r.RecoveryError('Configured auth source is not a nonempty JSON object.')
 return files,after


def capture_consistent(config):
 first,one=_capture(config)
 second,two=_capture(config)
 if one!=two or first!=second or source_stamps(config)!=two:
  raise r.RecoveryError('Sources changed during snapshot capture.')
 return second,two


def read_manifest(outbox,pin):
 value=r._parse(r.read_bounded(Path(outbox)/'latest.json',8192),8192)
 if type(value)is not dict or set(value)!=MANIFEST_KEYS or value['format']!='discord-autobackup-manifest' or type(value['version'])is not int or value['version']!=1:
  raise r.RecoveryError('Invalid outbox manifest.')
 try:
  ident=uuid.UUID(value['snapshot_id'])
  if ident.version!=4 or str(ident)!=value['snapshot_id']:raise ValueError()
 except (ValueError,TypeError,AttributeError):raise r.RecoveryError('Invalid snapshot identity.') from None
 if value['file_name']!='snapshot-'+value['snapshot_id']+'.encrypted.json' or value['recipient_sha256']!=pin:
  raise r.RecoveryError('Unexpected snapshot filename or recipient.')
 if type(value['sequence'])is not int or not 1<=value['sequence']<=2**53-1 or type(value['size_bytes'])is not int or not 1<=value['size_bytes']<=r.MAX_PACKAGE:
  raise r.RecoveryError('Invalid snapshot sequence or size.')
 if type(value['created_at'])is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z',value['created_at']):raise r.RecoveryError('Invalid snapshot timestamp.')
 try:dt.datetime.strptime(value['created_at'],'%Y-%m-%dT%H:%M:%SZ')
 except ValueError:raise r.RecoveryError('Invalid snapshot timestamp.') from None
 if type(value['sha256'])is not str or len(value['sha256'])!=64 or any(c not in '0123456789abcdef' for c in value['sha256']):raise r.RecoveryError('Invalid ciphertext digest.')
 return value


def publish_snapshot(root):
 root=Path(root);config=load_config(root);outbox=root/'outbox'
 with writer_lock(outbox):
  recipient=r.read_bounded(root/'recipient.json',a.MAX_RECIPIENT)
  if a.recipient_digest(recipient)!=config['recipient_sha256']:raise r.RecoveryError('Pinned recipient bundle mismatch; refusing backup.')
  try:previous=read_manifest(outbox,config['recipient_sha256']);sequence=previous['sequence']+1
  except FileNotFoundError:sequence=1
  fd=private_directory(outbox)
  try:
   if sum(name.startswith('snapshot-') and name.endswith('.encrypted.json') for name in os.listdir(fd))>=256:
    raise r.RecoveryError('Outbox retention limit reached; operator review is required.')
   files,signature=capture_consistent(config)
   raw=a.encrypt_snapshot(files,recipient,config['recipient_sha256'],sequence=sequence)
   package=a.validate_snapshot(raw,config['recipient_sha256']);name='snapshot-'+package['snapshot_id']+'.encrypted.json'
   temporary='.snapshot-temp-'+uuid.uuid4().hex
   try:
    r._write(fd,temporary,raw);r._rename_new(fd,temporary,name);os.fsync(fd)
   finally:
    try:os.unlink(temporary,dir_fd=fd)
    except FileNotFoundError:pass
   manifest={'format':'discord-autobackup-manifest','version':1,'snapshot_id':package['snapshot_id'],'sequence':sequence,'created_at':package['created_at'],'file_name':name,'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'recipient_sha256':config['recipient_sha256']}
   atomic_json(outbox,'latest.json',manifest)
   return manifest,signature
  finally:os.close(fd)


def _watch_loop(root,interval=5.0):
 # Metadata-only polls; plaintext exists only during a changed snapshot capture.
 root=Path(root);config=load_config(root)
 candidate=None;published=None;last_status=None
 while True:
  try:
   current=source_stamps(config)
   if current==candidate and current!=published:
    check=private_directory(root/'outbox')
    try:full=sum(name.startswith('snapshot-') and name.endswith('.encrypted.json') for name in os.listdir(check))>=256
    finally:os.close(check)
    if full:
     atomic_json(root,'health.json',{'status':'outbox_capacity_reached','updated_at':utc_now()})
     if last_status!='outbox_capacity_reached':print('outbox_capacity_reached',flush=True)
     last_status='outbox_capacity_reached';candidate=current;time.sleep(interval);continue
    operation=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--state-dir',str(root),'--once'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env={'PATH':'/usr/bin:/bin'},timeout=60,check=False)
    if operation.returncode==0:
     published=current;status='encrypted_snapshot_pending_upload'
    else:status='snapshot_blocked'
   else:status='watching'
   candidate=current
  except (r.RecoveryError,OSError,ValueError,subprocess.SubprocessError):
   candidate=None;status='snapshot_blocked'
  if status!=last_status:
   atomic_json(root,'health.json',{'status':status,'updated_at':utc_now()})
   print(status,flush=True);last_status=status
  time.sleep(interval)


def watch(root,interval=5.0):
 # One long-running watcher per state root; outbox uses a separate write lock.
 with writer_lock(root):
  _watch_loop(root,interval)


if __name__=='__main__':
 parser=argparse.ArgumentParser(description='Local encrypt-only watcher; no network access.')
 parser.add_argument('--state-dir',required=True)
 parser.add_argument('--once',action='store_true')
 args=parser.parse_args()
 try:
  if args.once:
   manifest,_=publish_snapshot(args.state_dir)
   print(json.dumps({'status':'encrypted_snapshot_pending_upload','snapshot_id':manifest['snapshot_id'],'sequence':manifest['sequence']}))
  else:watch(args.state_dir)
 except KeyboardInterrupt:raise SystemExit(0)
 except Exception:raise SystemExit('Automatic backup operation failed; no secret diagnostics emitted.')
