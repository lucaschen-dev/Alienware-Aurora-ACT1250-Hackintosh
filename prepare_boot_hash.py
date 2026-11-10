"""Prepare an enrollment-only copy matching OC's documented image preprocessing.

Never write the source Preboot file or any hard-disk EFI.  No trust store writes.
Only the exact tested macOS 25G332 booter is accepted. Other builds fail closed.
The existing OpenCore is not rebuilt or replaced.
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

if not __debug__:
    raise RuntimeError('Do not run this verifier with Python optimization enabled')
parser = argparse.ArgumentParser(description='Prepare an enrollment-only copy for the exact tested 25G332 booter. No EFI/NVRAM writes.')
parser.add_argument('input', type=Path, help='Read-only copy of your original Apple boot.efi')
parser.add_argument('--oc-source', required=True, type=Path, help='Official OpenCorePkg 1.0.8 source tree')
parser.add_argument('--output-directory', required=True, type=Path, help='New directory; must not already exist')
args = parser.parse_args()
BASE = args.output_directory
if BASE.exists():
    raise RuntimeError('Output directory already exists; choose a new directory')
SOURCE_TREE = args.oc_source
ORIGINAL = args.input
EXPECTED_ORIGINAL = '016ccd2dde70411ed45b2603d14a5917cc1ce9bda866f086421e8d8e4f22a6cc'

def u16(d, offset): return struct.unpack_from('<H', d, offset)[0]
def u32(d, offset): return struct.unpack_from('<I', d, offset)[0]

def parse(d):
    assert d[:2] == b'MZ'
    pe = u32(d, 60)
    assert d[pe:pe+4] == b'PE\0\0'
    opt = pe+24
    assert u16(d, opt) == 0x20b
    table = opt+u16(d, pe+20)
    sections = []
    for i in range(u16(d, pe+6)):
        pos = table+i*40
        name, vs, va, size, off, rel, lin, nr, nl, flags = struct.unpack_from('<8sIIIIIIHHI', d, pos)
        assert off+size <= len(d)
        sections.append(dict(name=name.rstrip(b'\0').decode(), virtualSize=vs,
            virtualAddress=va, rawSize=size, rawOffset=off, flags=flags,
            headerOffset=pos, contentSHA256=hashlib.sha256(d[off:off+size]).hexdigest()))
    return pe, opt, table, u32(d,opt+60), sections

def shim_digest(d):
    """Exactly the generate_hash() section order and unsigned-tail rule in shim 15.8."""
    pe,opt,table,headers,sections=parse(d)
    secdir=opt+112+4*8
    certoff,certsize=struct.unpack_from('<II', d, secdir)
    h=hashlib.sha256()
    h.update(d[:opt+64]);h.update(d[opt+68:secdir]);h.update(d[secdir+8:headers])
    total=headers
    for sec in sorted(sections,key=lambda s:s['rawOffset']):
        if sec['rawSize']:
            h.update(d[sec['rawOffset']:sec['rawOffset']+sec['rawSize']])
            total+=sec['rawSize']
    if len(d)>total and certsize:
        size=len(d)-certsize-total
        assert size>=0 and total+size==certoff
        h.update(d[total:total+size])
    # shim 15.8 deliberately does not hash trailing data for an unsigned image.
    return h.hexdigest()

data=ORIGINAL.read_bytes()
assert len(data)==723512 and hashlib.sha256(data).hexdigest()==EXPECTED_ORIGINAL
pe,opt,table,headers,sections=parse(data)
secdir=opt+112+4*8
signed_size,info_size=struct.unpack_from('<II',data,secdir)
assert signed_size==722952 and info_size==8
certoff,certsize=struct.unpack_from('<II',data,signed_size)
assert certsize==552 and certoff+certsize==len(data)
assert u32(data,certoff)==certsize and u16(data,certoff+6)==0x0ef1
assert data[certoff+8:certoff+24].hex()=='51bce7453c91ac4296a210712ffbeba7'
assert data[certoff+24:certoff+40].hex()=='147471a716c677499420844712a735bf'
modulus=data[certoff+40:certoff+296]
signature=data[certoff+296:certoff+552]

# Use only a modulus already present in the official OC Apple key database.
keysource=(SOURCE_TREE/'Library/OcAppleKeysLib/OcAppleKeysLib.c').read_text()
known=[]
for block in keysource.split('// N')[1:]:
    block=block.split('// R^2 mod N')[0]
    known.append(bytes(int(x,16) for x in re.findall(r'0x([0-9a-fA-F]{2})\b',block)))
assert modulus in known, 'Apple public modulus is not in the official OC database'

# Reproduce PeCoffHashAppleImage and verify PKCS#1 v1.5 RSA-2048/SHA-256.
signed_bytes=data[:64]+data[pe:opt+64]+data[opt+68:secdir]+data[secdir+8:signed_size]
apple_hash=hashlib.sha256(signed_bytes).digest()
decoded=pow(int.from_bytes(signature,'little'),65537,int.from_bytes(modulus,'little')).to_bytes(256,'big')
digest_info=bytes.fromhex('3031300d060960864801650304020105000420')+apple_hash
expected=b'\0\1'+b'\xff'*(256-len(digest_info)-3)+b'\0'+digest_info
assert decoded==expected, 'Original Apple EFI RSA signature verification failed'

# PeCoffSanitiseAppleImage: zero DOS stub/checksum/security directory, drop signature.
patched=bytearray(data[:signed_size])
patched[64:pe]=b'\0'*(pe-64)
patched[opt+64:opt+68]=b'\0'*4
patched[secdir:secdir+8]=b'\0'*8
fixups=[]
for sec in sections:
    if sec['flags'] & 0xa0000000 == 0xa0000000:
        struct.pack_into('<I',patched,sec['headerOffset']+36,sec['flags'] & ~0x20000000)
        fixups.append(sec['name'])
assert fixups==['.data']
after=parse(patched)[4]
assert all(a['contentSHA256']==b['contentSHA256'] for a,b in zip(sections,after))
assert all(a['virtualAddress']==b['virtualAddress'] and a['virtualSize']==b['virtualSize']
           and a['rawOffset']==b['rawOffset'] and a['rawSize']==b['rawSize']
           for a,b in zip(sections,after))
target=BASE/'MOK-boot-26.7.2.efi'
BASE.mkdir(parents=True, exist_ok=False)
target.write_bytes(patched)
digest=shim_digest(patched)

# Negative control: a changed executable byte must no longer match the enrolled digest.
changed=bytearray(patched);changed[sections[0]['rawOffset']+256]^=1
assert shim_digest(changed)!=digest
result=dict(revision='apple-booter-owner-hash-v4', originalFileSHA256=EXPECTED_ORIGINAL,
    originalAppleRSASignatureValid=True, appleModulusInOfficialOcDatabase=True,
    originalSize=len(data), processedSize=len(patched), fixupSections=fixups,
    processedFileSHA256=hashlib.sha256(patched).hexdigest(), shim15_8SHA256=digest,
    executableAndDataSectionBytesUnchanged=True, changedCodeNegativeControlRejected=True,
    enrollmentCopyOnly=True, inputModified=False,
    hardDiskEFIWrites=False, originalPrebootFileWrites=False, trustStoreWrites=False,
    sourceVersionLimit='Offline reproduction refers to official OC 1.0.8. Verify the actual loader behavior independently.',
    outputHardwareTested=False,
    updateLimit='This hash only covers this processed booter version. A macOS update may require a new enrollment.',
    firmwareLimit='Some firmware may also verify the original disk path through Security1, which is not resolved by the processed-buffer hash.')
(BASE/'boot-hash-preparation.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
