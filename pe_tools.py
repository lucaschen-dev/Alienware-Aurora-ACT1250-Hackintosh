"""Offline PE32+ tools for the specific shim 15.8 investigation in SECURE_BOOT.md.

This is a small, deliberately restricted parser, not a firmware verifier.
`normalize` accepts only unsigned, aligned images without an unknown overlay.
It writes a NEW file; it never signs, installs, enrolls, or changes firmware.
Digest ordering is based on rhboot/shim 15.8 pe.c generate_hash().
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess


def require(condition, message):
    if not condition:
        raise ValueError(message)


def u16(data, offset):
    return struct.unpack_from('<H', data, offset)[0]


def u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def parse(data):
    require(len(data) >= 64 and data[:2] == b'MZ', 'Missing DOS header')
    pe = u32(data, 60)
    require(64 <= pe <= len(data) - 24, 'Invalid PE offset')
    require(data[pe:pe + 4] == b'PE\0\0', 'Missing PE signature')
    require(u16(data, pe + 4) == 0x8664, 'Only x86_64 images are supported')
    optional = pe + 24
    optional_size = u16(data, pe + 20)
    require(optional_size >= 152 and optional + optional_size <= len(data),
            'Truncated optional header')
    require(u16(data, optional) == 0x20b, 'Only PE32+ images are supported')
    require(u32(data, optional + 108) >= 5, 'Missing security directory slot')
    security = optional + 112 + 4 * 8
    headers = u32(data, optional + 60)
    count = u16(data, pe + 6)
    table = optional + optional_size
    require(count > 0 and table + count * 40 <= headers <= len(data),
            'Invalid section table or SizeOfHeaders')
    cert_offset, cert_size = struct.unpack_from('<II', data, security)
    require(bool(cert_offset) == bool(cert_size), 'Partial certificate directory')
    if cert_size:
        require(cert_offset >= headers and cert_offset + cert_size == len(data),
                'Only a single terminal Authenticode table is supported; Apple signatures use a different format')
    end = cert_offset if cert_size else len(data)
    sections = []
    for i in range(count):
        position = table + i * 40
        name, vs, va, size, offset, reloc, lines, nr, nl, flags = struct.unpack_from(
            '<8sIIIIIIHHI', data, position)
        require(offset + size <= end, 'Section extends outside image data')
        if size:
            require(offset >= headers, 'Raw section overlaps headers')
        sections.append({
            'name': name.rstrip(b'\0').decode('ascii', errors='backslashreplace'),
            'virtualSize': vs, 'virtualAddress': va, 'rawSize': size,
            'rawOffset': offset, 'flags': flags,
            'contentSHA256': hashlib.sha256(data[offset:offset + size]).hexdigest()
        })
    cursor = headers
    gaps = []
    for section in sorted((s for s in sections if s['rawSize']),
                          key=lambda s: s['rawOffset']):
        offset, size = section['rawOffset'], section['rawSize']
        require(offset >= cursor, 'Overlapping raw sections')
        if offset > cursor:
            gaps.append({'offset': cursor, 'size': offset - cursor})
        cursor = offset + size
    require(cursor <= end, 'Invalid image end')
    return {
        'pe': pe, 'optional': optional, 'table': table, 'headers': headers,
        'security': security, 'certOffset': cert_offset, 'certSize': cert_size,
        'sections': sections, 'gaps': gaps, 'rawEnd': cursor, 'dataEnd': end
    }


def shim_digest(data, context=None):
    x = context or parse(data)
    optional, security = x['optional'], x['security']
    h = hashlib.sha256()
    h.update(data[:optional + 64])
    h.update(data[optional + 68:security])
    h.update(data[security + 8:x['headers']])
    total = x['headers']
    for section in sorted(x['sections'], key=lambda s: s['rawOffset']):
        if section['rawSize']:
            h.update(data[section['rawOffset']:section['rawOffset'] + section['rawSize']])
            total += section['rawSize']
    # Match this shim version's signed-image tail rule, including its start
    # at the COUNT of bytes hashed, not the highest raw section end.
    if len(data) > total and x['certSize']:
        amount = len(data) - x['certSize'] - total
        require(amount >= 0 and total + amount == x['certOffset'],
                'Unsupported certificate/tail layout')
        h.update(data[total:total + amount])
    # Unsigned trailing bytes are not hashed by this path in shim 15.8.
    return h.hexdigest()


def report(data, x=None):
    x = x or parse(data)
    return {
        'fileBytes': len(data), 'wholeFileSHA256': hashlib.sha256(data).hexdigest(),
        'shim15_8SHA256': shim_digest(data, x),
        'certificateTableBytes': x['certSize'], 'rawGaps': x['gaps'],
        'overlayBytesBeforeCertificate': x['dataEnd'] - x['rawEnd'],
        'sections': x['sections']
    }


def normalize(data):
    x = parse(data)
    require(x['certSize'] == 0, 'Remove the existing signature from a WORKING COPY first')
    require(x['rawEnd'] == len(data), 'Unknown overlay; stop and analyze it separately')
    require(x['gaps'], 'No raw gaps need normalization')
    optional, table = x['optional'], x['table']
    section_align, file_align = struct.unpack_from('<II', data, optional + 32)
    for alignment in (section_align, file_align):
        require(alignment > 0 and alignment & (alignment - 1) == 0,
                'Unsupported non-power-of-two alignment')
    require(section_align >= file_align, 'Unsupported alignment relationship')
    require(all(s['rawOffset'] % file_align == 0 and s['rawSize'] % file_align == 0
                for s in x['sections'] if s['rawSize']), 'Unaligned raw section')
    require(all(g['offset'] % file_align == 0 and g['size'] % file_align == 0
                for g in x['gaps']), 'Unaligned raw gap')
    count = len(x['sections'])
    require(count + len(x['gaps']) <= 96, 'Too many sections for this restricted helper')
    start = table + count * 40
    end = table + (count + len(x['gaps'])) * 40
    first_raw = min(s['rawOffset'] for s in x['sections'] if s['rawSize'])
    require(end <= min(x['headers'], first_raw), 'No header space for added sections')
    require(not any(data[start:end]), 'New section headers would overwrite occupied bytes')
    existing_names = {s['name'] for s in x['sections']}
    require(not any('.sgap' + str(i) in existing_names for i in range(len(x['gaps']))),
            'Metadata section name collision')
    align = lambda n, a: (n + a - 1) // a * a
    virtual = align(max(s['virtualAddress'] + max(s['virtualSize'], s['rawSize'])
                        for s in x['sections']), section_align)
    result = bytearray(data)
    for i, gap in enumerate(x['gaps']):
        size, offset = gap['size'], gap['offset']
        require(virtual + size <= 0xffffffff, 'Virtual address overflow')
        struct.pack_into('<8sIIIIIIHHI', result, start + i * 40,
                         ('.sgap' + str(i)).encode().ljust(8, b'\0'),
                         size, virtual, size, offset, 0, 0, 0, 0, 0x42000040)
        virtual = align(virtual + size, section_align)
    require(virtual <= 0xffffffff, 'SizeOfImage overflow')
    initialized = u32(data, optional + 8) + sum(g['size'] for g in x['gaps'])
    require(initialized <= 0xffffffff, 'Initialized data size overflow')
    struct.pack_into('<H', result, x['pe'] + 6, count + len(x['gaps']))
    struct.pack_into('<I', result, optional + 56, max(u32(data, optional + 56), virtual))
    struct.pack_into('<I', result, optional + 8, initialized)
    struct.pack_into('<I', result, optional + 64, 0)
    after = parse(result)
    require(after['sections'][:count] == x['sections'], 'Original section invariant failed')
    require(not after['gaps'], 'Raw gaps remain')
    require(all(s['flags'] & 0x20000000 == 0 for s in after['sections'][count:]),
            'Added metadata unexpectedly executable')
    return bytes(result), x['gaps']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    digest = commands.add_parser('digest', help='Read-only PE layout and shim 15.8 digest')
    digest.add_argument('input', type=Path)
    normal = commands.add_parser('normalize', help='Add non-executable metadata for aligned gaps')
    normal.add_argument('input', type=Path)
    normal.add_argument('output', type=Path, help='New file; must not exist')
    verify = commands.add_parser('verify', help='Compare verified Authenticode digest with shim digest')
    verify.add_argument('input', type=Path)
    verify.add_argument('--cert', type=Path, required=True)
    verify.add_argument('--osslsigncode', default='osslsigncode')
    args = parser.parse_args()
    data = args.input.read_bytes()
    if args.command == 'normalize':
        result, gaps = normalize(data)
        with args.output.open('xb') as output:
            output.write(result)
        print(json.dumps({'coveredRawGaps': gaps, 'originalSectionsUnchanged': True,
                          'addedSectionsExecutable': False, 'result': report(result)}, indent=2))
        return 0
    result = report(data)
    if args.command == 'verify':
        executable = shutil.which(args.osslsigncode)
        require(executable, 'osslsigncode was not found')
        process = subprocess.run([executable, 'verify', '-CAfile', str(args.cert),
                                  '-in', str(args.input)], capture_output=True, text=True)
        output = process.stdout + process.stderr
        require(process.returncode == 0, 'Authenticode/certificate verification failed: ' + output)
        found = re.search(r'Current message digest\s*:\s*([0-9A-Fa-f]{64})\b', output)
        require(found, 'Could not extract SHA-256 digest from osslsigncode output')
        result['authenticodeVerified'] = True
        result['signedDigest'] = found.group(1).lower()
        result['signedDigestMatchesShim'] = result['signedDigest'] == result['shim15_8SHA256']
        print(json.dumps(result, indent=2))
        return 0 if result['signedDigestMatchesShim'] else 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, struct.error) as error:
        raise SystemExit('Stopped: ' + str(error))
