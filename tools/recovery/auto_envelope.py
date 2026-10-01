"""Synthetic-stage v3 envelope encryption; never stores a plaintext recovery key.

The public recipient permits encryption, not sender authentication. Trust the
protected outbox/Library write channel; pin the recipient bundle independently.
"""
import datetime as dt
import hashlib
import os
import re
import uuid
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import recovery_core as r

RECIPIENT_FORMAT = 'discord-translate-encrypt-only-recipient'
ALGORITHM = 'AES-256-GCM+RSA-3072-OAEP-SHA256'
MAX_RECIPIENT = 16 * 1024
RECIPIENT_KEYS = {'format','version','algorithm','public_key','public_key_sha256','recovery_series_id','recovery'}
RECOVERY_KEYS = {'format','version','algorithm','kdf','salt','nonce','public_key_sha256','recovery_series_id','encrypted_private_key'}
SNAPSHOT_KEYS = {'format','version','algorithm','recipient','created_at','snapshot_id','sequence','wrapped_key','nonce','ciphertext_and_tag'}


def _oaep():
    return padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)


def _public_bytes(key):
    return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def _fingerprint(raw):
    return hashlib.sha256(raw).hexdigest()


def _validate_recipient(bundle):
    if type(bundle) is not dict or set(bundle) != RECIPIENT_KEYS:
        raise r.RecoveryError('Invalid encrypt-only recipient structure.')
    if bundle['format'] != RECIPIENT_FORMAT or type(bundle['version']) is not int or bundle['version'] != 1 or bundle['algorithm'] != 'RSA-3072-OAEP-SHA256':
        raise r.RecoveryError('Unsupported encrypt-only recipient.')
    public_raw = r._unb64(bundle['public_key'], 1024)
    if bundle['public_key_sha256'] != _fingerprint(public_raw):
        raise r.RecoveryError('Recipient public key fingerprint mismatch.')
    try:
        public = serialization.load_der_public_key(public_raw)
    except (ValueError, TypeError):
        raise r.RecoveryError('Invalid recipient public key.') from None
    if not isinstance(public,rsa.RSAPublicKey) or public.key_size != 3072 or public.public_numbers().e != 65537 or _public_bytes(public) != public_raw:
        raise r.RecoveryError('Unsupported recipient public key.')
    try:
        series=uuid.UUID(bundle['recovery_series_id'])
        if series.version!=4 or str(series)!=bundle['recovery_series_id']: raise ValueError()
    except (ValueError,TypeError,AttributeError):
        raise r.RecoveryError('Invalid recovery series identity.') from None
    recovery = bundle['recovery']
    if type(recovery) is not dict or set(recovery) != RECOVERY_KEYS:
        raise r.RecoveryError('Invalid protected recovery key structure.')
    if recovery['format'] != 'discord-translate-recovery-key' or type(recovery['version']) is not int or recovery['version'] != 1 or recovery['algorithm'] != 'AES-256-GCM':
        raise r.RecoveryError('Unsupported protected recovery key.')
    if type(recovery['kdf']) is not dict or r._json(recovery['kdf']) != r._json(r.KDF) or recovery['public_key_sha256'] != bundle['public_key_sha256'] or recovery['recovery_series_id'] != bundle['recovery_series_id']:
        raise r.RecoveryError('Invalid recovery key parameters or fingerprint.')
    if len(r._unb64(recovery['salt'],16)) != 16 or len(r._unb64(recovery['nonce'],12)) != 12 or len(r._unb64(recovery['encrypted_private_key'],4096)) < 17:
        raise r.RecoveryError('Invalid protected recovery key field length.')
    return public


def create_recipient(password):
    """For user-operated setup only. Tests pass fresh, synthetic passwords."""
    r._password(password)
    private = rsa.generate_private_key(public_exponent=65537,key_size=3072)
    public_raw = _public_bytes(private.public_key())
    fingerprint = _fingerprint(public_raw)
    series = str(uuid.uuid4())
    salt,nonce = os.urandom(16),os.urandom(12)
    header = {'format':'discord-translate-recovery-key','version':1,'algorithm':'AES-256-GCM','kdf':dict(r.KDF),'salt':r._b64(salt),'nonce':r._b64(nonce),'public_key_sha256':fingerprint,'recovery_series_id':series}
    private_raw = private.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    protected = AESGCM(r._key(password,salt)).encrypt(nonce,private_raw,r._json(header))
    bundle = {'format':RECIPIENT_FORMAT,'version':1,'algorithm':'RSA-3072-OAEP-SHA256','public_key':r._b64(public_raw),'public_key_sha256':fingerprint,'recovery_series_id':series,'recovery':{**header,'encrypted_private_key':r._b64(protected)}}
    return r._json(bundle) + b'\n'


def recipient_digest(recipient):
    bundle = r._parse(recipient,MAX_RECIPIENT)
    _validate_recipient(bundle)
    return _fingerprint(r._json(bundle))


def encrypt_snapshot(files,recipient,expected_recipient_digest,sequence=1):
    """No password, private key, or Library credential is accepted here."""
    r._files(files)
    if type(sequence)is not int or not 1<=sequence<=2**53-1:
        raise r.RecoveryError('Invalid snapshot sequence.')
    bundle = r._parse(recipient,MAX_RECIPIENT)
    public = _validate_recipient(bundle)
    if type(expected_recipient_digest) is not str or not re.fullmatch('[0-9a-f]{64}',expected_recipient_digest) or _fingerprint(r._json(bundle)) != expected_recipient_digest:
        raise r.RecoveryError('Pinned recipient bundle mismatch; refusing backup.')
    data_key,nonce = AESGCM.generate_key(bit_length=256),os.urandom(12)
    header = {'format':r.FORMAT,'version':3,'algorithm':ALGORITHM,'recipient':bundle,'created_at':dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),'snapshot_id':str(uuid.uuid4()),'sequence':sequence,'wrapped_key':r._b64(public.encrypt(data_key,_oaep())),'nonce':r._b64(nonce)}
    payload = r._json({'payload_version':1,'files':{name:r._b64(value) for name,value in files.items()}})
    ciphertext = AESGCM(data_key).encrypt(nonce,payload,r._json(header))
    return r._json({**header,'ciphertext_and_tag':r._b64(ciphertext)}) + b'\n'


def validate_snapshot(raw,expected_recipient_digest=None):
    """Structural/ciphertext validation only; does not prove plaintext validity."""
    package = r._parse(raw,r.MAX_PACKAGE)
    if type(package) is not dict or set(package) != SNAPSHOT_KEYS or package['format'] != r.FORMAT or type(package['version']) is not int or package['version'] != 3 or package['algorithm'] != ALGORITHM:
        raise r.RecoveryError('Unsupported snapshot structure or version.')
    _validate_recipient(package['recipient'])
    if type(package['sequence'])is not int or not 1<=package['sequence']<=2**53-1:
        raise r.RecoveryError('Invalid snapshot sequence.')
    if expected_recipient_digest is not None and _fingerprint(r._json(package['recipient'])) != expected_recipient_digest:
        raise r.RecoveryError('Pinned recipient bundle mismatch; refusing backup.')
    try:
        if type(package['created_at']) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z',package['created_at']):
            raise ValueError()
        dt.datetime.strptime(package['created_at'],'%Y-%m-%dT%H:%M:%SZ')
        value=uuid.UUID(package['snapshot_id'])
        if value.version != 4 or str(value) != package['snapshot_id']: raise ValueError()
    except (ValueError,TypeError,AttributeError):
        raise r.RecoveryError('Invalid snapshot metadata.') from None
    if len(r._unb64(package['wrapped_key'],384)) != 384 or len(r._unb64(package['nonce'],12)) != 12 or len(r._unb64(package['ciphertext_and_tag'],r.MAX_PAYLOAD+16)) < 17:
        raise r.RecoveryError('Invalid snapshot ciphertext field length.')
    return package


def decrypt_snapshot(raw,password):
    package=validate_snapshot(raw)
    bundle=package['recipient']; recovery=bundle['recovery']
    recovery_header={k:v for k,v in recovery.items() if k!='encrypted_private_key'}
    try:
        private_raw=AESGCM(r._key(password,r._unb64(recovery['salt'],16))).decrypt(r._unb64(recovery['nonce'],12),r._unb64(recovery['encrypted_private_key'],4096),r._json(recovery_header))
        private=serialization.load_der_private_key(private_raw,password=None)
        if not isinstance(private,rsa.RSAPrivateKey) or private.key_size!=3072 or _public_bytes(private.public_key())!=r._unb64(bundle['public_key'],1024):
            raise ValueError()
        data_key=private.decrypt(r._unb64(package['wrapped_key'],384),_oaep())
        if len(data_key)!=32: raise ValueError()
        header={k:v for k,v in package.items() if k!='ciphertext_and_tag'}
        payload=AESGCM(data_key).decrypt(r._unb64(package['nonce'],12),r._unb64(package['ciphertext_and_tag'],r.MAX_PAYLOAD+16),r._json(header))
    except (InvalidTag,ValueError,TypeError):
        raise r.RecoveryError('Wrong recovery passphrase or damaged snapshot. Nothing was restored.') from None
    data=r._parse(payload,r.MAX_PAYLOAD)
    if type(data)is not dict or set(data)!={'payload_version','files'} or type(data['payload_version'])is not int or data['payload_version']!=1:
        raise r.RecoveryError('Invalid recovered payload.')
    files=data['files']
    if type(files)is not dict or '.env' not in files or not files.keys()<=r.LIMITS.keys():
        raise r.RecoveryError('Only .env and optional dedicated codex/auth.json are allowed.')
    return r._files({name:r._unb64(value,r.LIMITS[name]) for name,value in files.items()})
