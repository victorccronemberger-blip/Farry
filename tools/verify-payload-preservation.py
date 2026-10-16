"""Compare distribution payloads; only Authenticode changes are permitted."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile

OWN_EXECUTABLES = {'QMoney.exe', 'QMoneyUpdater.exe', 'runtime/QMoneyService.exe'}


def unsigned_image(data):
    image = bytearray(data)
    if image[:2] != b'MZ':
        raise ValueError('Expected a Windows executable')
    pe = struct.unpack_from('<I', image, 0x3c)[0]
    if image[pe:pe + 4] != b'PE\0\0':
        raise ValueError('Invalid PE header')
    optional = pe + 24
    magic = struct.unpack_from('<H', image, optional)[0]
    if magic not in (0x10b, 0x20b):
        raise ValueError('Unsupported executable format')
    security = optional + (112 if magic == 0x20b else 96) + 4 * 8
    certificate_offset, certificate_size = struct.unpack_from('<II', image, security)
    image[optional + 64:optional + 68] = b'\0' * 4
    image[security:security + 8] = b'\0' * 8
    if certificate_size:
        if certificate_offset + certificate_size != len(image):
            raise ValueError('Unexpected data after Authenticode certificate')
        del image[certificate_offset:]
    # Authenticode aligns the unsigned image to an eight-byte boundary.
    image.extend(b'\0' * ((-len(image)) % 8))
    return image


def compare(source, target):
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(target) as after:
        old_names, new_names = before.namelist(), after.namelist()
        if len(set(old_names)) != len(old_names) or len(set(new_names)) != len(new_names) or set(old_names) != set(new_names):
            raise ValueError('Payload file lists differ or contain duplicates')
        for name in old_names:
            if name in OWN_EXECUTABLES:
                if unsigned_image(before.read(name)) != unsigned_image(after.read(name)):
                    raise ValueError('Executable code changed: ' + name)
            else:
                with before.open(name) as left, after.open(name) as right:
                    if hashlib.file_digest(left, 'sha256').digest() != hashlib.file_digest(right, 'sha256').digest():
                        raise ValueError('Payload content changed: ' + name)
    return {'passed': True, 'payload_files': len(old_names), 'signed_executables': sorted(OWN_EXECUTABLES),
            'other_files': 'byte-for-byte identical', 'executable_code': 'unchanged; only Authenticode metadata added'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.source, args.target)
    args.report.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
