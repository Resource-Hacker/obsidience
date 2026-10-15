#!/usr/bin/env python3
"""Pack an extension directory into a CRX3 file signed with an RSA PEM key.

No browser process is involved. Format follows Chromium
components/crx_file/crx3.proto and crx_verifier.cc (148.0.7778.288):
  "Cr24" | u32le 3 | u32le header_len | CrxFileHeader | zip
  signature = RSA-PKCS1v15-SHA256 over
  "CRX3 SignedData\\x00" | u32le len(signed_data) | signed_data | zip
  crx_id = first 16 bytes of SHA-256(DER SubjectPublicKeyInfo).

Usage: pack_crx3.py EXT_DIR KEY.pem OUT.crx
Prints the extension ID.
"""
import hashlib
import io
import os
import struct
import sys
import zipfile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def field_bytes(num, data):
    # protobuf wire type 2 (length-delimited)
    return varint((num << 3) | 2) + varint(len(data)) + data


def ext_id(spki_der):
    h = hashlib.sha256(spki_der).hexdigest()[:32]
    return h.translate(str.maketrans("0123456789abcdef", "abcdefghijklmnop"))


def zip_dir(path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(path):
            dirs.sort()
            for name in sorted(files):
                full = os.path.join(root, name)
                rel = os.path.relpath(full, path)
                info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                with open(full, "rb") as f:
                    z.writestr(info, f.read())
    return buf.getvalue()


def main():
    ext_dir, key_path, out_path = sys.argv[1:4]
    with open(key_path, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    crx_id = hashlib.sha256(spki).digest()[:16]
    signed_data = field_bytes(1, crx_id)  # SignedData { crx_id = 1 }
    archive = zip_dir(ext_dir)
    to_sign = (b"CRX3 SignedData\x00" + struct.pack("<I", len(signed_data))
               + signed_data + archive)
    sig = key.sign(to_sign, padding.PKCS1v15(), hashes.SHA256())
    proof = field_bytes(1, spki) + field_bytes(2, sig)  # AsymmetricKeyProof
    header = field_bytes(2, proof) + field_bytes(10000, signed_data)
    with open(out_path, "wb") as f:
        f.write(b"Cr24" + struct.pack("<II", 3, len(header)) + header + archive)
    print(ext_id(spki))


if __name__ == "__main__":
    main()
