"""Write an unencrypted twin of an AMS2 .bff pak.

Every region PCarsTools decrypts (file table, extended info table, each file's
data) is decrypted in place; sizes and offsets stay identical, and the header's
encryption byte is set to 0 (None). Ported from Nenkai/PCarsTools.
"""
import re, struct, sys, zlib
from pathlib import Path

HEADER_SIZE = 0x130
ENC_OFFSET = 0x12D
TOC_ENTRY = 0x2A
TOC_CRC = 0x22
EXT_HEADER = 0x308

def load_keys(cs_path):
    src = Path(cs_path).read_text(encoding="utf-8-sig")
    block = src[src.index("_keys_PC2AndAbove = new"):]
    block = block[:block.index("};")]
    return [bytes(int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", row))
            for row in re.findall(r"new byte\[\] \{([^}]*)\}", block)]

def deobfuscate(key):
    key = bytearray(key)
    xor, t = (0xAC, 0xC7, 0x91), 0
    i = 0
    while i + 1 < len(key):
        a = xor[t] ^ key[i]; t = (t + 1) % 3
        b = xor[t] ^ key[i + 1]; t = (t + 1) % 3
        key[i], key[i + 1] = b, a
        i += 2
    for i in range(i, len(key)):
        key[i] ^= xor[t]; t = (t + 1) % 3
    return bytes(key)

def rc4(key, data):
    box = list(range(256)); j = 0
    for i in range(256):
        j = (j + box[i] + key[i % len(key)]) & 255
        box[i], box[j] = box[j], box[i]
    out = bytearray(len(data)); a = j = 0
    for n, c in enumerate(data):
        a = (a + 1) & 255; j = (j + box[a]) & 255
        box[a], box[j] = box[j], box[a]
        out[n] = c ^ box[(box[a] + box[j]) & 255]
    return bytes(out)

M = 0xFFFFFFFF
rol = lambda v, s: ((v << (s & 31)) | (v >> (32 - (s & 31)))) & M if s & 31 else v
ror = lambda v, s: ((v >> (s & 31)) | (v << (32 - (s & 31)))) & M if s & 31 else v

class Scribe:
    KEY = [0xbb9fcbf5, 0xb296fa98, 0xdd9ccbdb, 0x96c2e3f2, 0x93e8dcf3, 0xbadbbc99,
           0xcc9acd89, 0xaae9bc98, 0xa8f9a8c5, 0xb6d8fbd0, 0xc6cea888, 0]
    R, KS = 30, 44
    F = R * 2 + 4

    def __init__(self):
        tk = []
        for c in self.KEY[:11]:
            tk += [(c >> 8) & 255, (c >> 24) & 255, c & 255, (c >> 16) & 255]
        s = [0] * 64
        s[0] = 0xB7E15163
        for x in range(1, self.R * 2 + 4):
            s[x] = (s[x - 1] + 0x9E3779B9) & M
        a = b = i = j = 0
        for x in range(1, 3 * max(self.KS, self.F) + 1):
            a = s[i] = rol((s[i] + a + b) & M, 3)
            kr = tk[j]
            if x <= self.KS:
                kr ^= (0xAEB3F79A >> ((j % 4) * 8)) & 255
            b = tk[j] = rol((kr + a + b) & M, (a + b) & 31)
            i = (i + 1) % self.F; j = (j + 1) % self.KS
        self.s = s

    def decrypt(self, data):
        s, R = self.s, self.R
        w = list(struct.unpack(f"<{len(data)//4}I", data))
        for x in range(0, len(w), 4):
            k0, k1, k2, k3 = w[x:x + 4]
            k2 = (k2 - s[R * 2 + 3]) & M
            k0 = (k0 - s[R * 2 + 2]) & M
            for i in range(R, 0, -1):
                k0, k1, k2, k3 = k3, k0, k1, k2
                a = rol((k3 * ((k3 << 1) + 1)) & M, 2)
                b = rol((k1 * ((k1 << 1) + 1)) & M, 2)
                k2 = ror((k2 - s[(i << 1) + 1]) & M, b & 31) ^ a
                k0 = ror((k0 - s[i << 1]) & M, a & 31) ^ b
            k3 = (k3 - s[1]) & M
            k1 = (k1 - s[0]) & M
            w[x:x + 4] = [k0, k1, k2, k3]
        return struct.pack(f"<{len(w)}I", *w)

def parse_header(b):
    count, = struct.unpack_from("<I", b, 8)
    toc_size, crc_size, ext_size, sec_pos, sec_size = struct.unpack_from("<5I", b, 0x118)
    return dict(count=count, toc_size=toc_size, crc_size=crc_size, ext_size=ext_size,
                sec_pos=sec_pos, sec_size=sec_size, flags=b[0x12C], enc=b[ENC_OFFSET],
                name=b[0x18:0x118].split(b"\0")[0].decode())

def ext_region(b, h):
    """(start, length) of the Scribe-encrypted ext entries + name table.

    PCarsTools (BPakFile.FromStream) only needs align16(ext_size - EXT_HEADER) bytes
    after the ext header. The game's writer, however, Scribe-encrypts zero padding
    in whole 16-byte blocks up to the section block (or the data offset when a pak
    has none), and the final (end - start) % 16 bytes are left as plain zeros. That
    remainder is not always 0 (e.g. VW_Virtus_GTS_Livery.bff: 10 bytes), so the
    encrypted extent is (end - start) rounded DOWN to 16. The encrypted padding can
    also stop early and be followed by plain zero blocks (vehiclespersistent.bff:
    encryption stops 64 KiB after start), so trailing all-zero 16-byte blocks are
    dropped too (an encrypted zero block is never all zero). The result always
    covers the table PCarsTools reads.
    """
    start = HEADER_SIZE + h["toc_size"] + EXT_HEADER
    data_off, = struct.unpack_from("<Q", b, 12)
    end = h["sec_pos"] or data_off
    need = (h["ext_size"] - EXT_HEADER + 15) & ~15
    length = (end - start) & ~15
    assert length >= need, (start, end, h)
    while length > need and not any(b[start + length - 16:start + length]):
        length -= 16
    assert not any(b[start + length:end]), "unexpected non-zero bytes after ext table"
    return start, length

def twin(src, dst, keys_cs):
    b = bytearray(Path(src).read_bytes())
    h = parse_header(b)
    assert b[:4] == b" KAP" and h["enc"] == 2, h
    keys = [deobfuscate(k.split(b"\x00")[0]) for k in load_keys(keys_cs)]  # keys are null-terminated

    toc_raw = bytes(b[HEADER_SIZE:HEADER_SIZE + h["toc_size"]])
    key = next(k for k in keys if (t := rc4(k, toc_raw))[14] == 0 and t[15] == 0)
    toc = rc4(key, toc_raw)
    b[HEADER_SIZE:HEADER_SIZE + h["toc_size"]] = toc

    ext_entries, ext_len = ext_region(b, h)
    ext = Scribe().decrypt(bytes(b[ext_entries:ext_entries + ext_len]))
    assert ext[6] == 0 and ext[7] == 0, "ext table did not decrypt"
    b[ext_entries:ext_entries + ext_len] = ext

    entries = []
    for i in range(h["count"]):
        uid, pos, size, orig, mtime, ctype, _, crc = struct.unpack_from("<QQIIQBBI", toc, i * TOC_ENTRY)
        name_off, = struct.unpack_from("<Q", ext, i * 16)
        rel = name_off - ext_entries  # name offsets are pak-relative, 1-byte length prefix
        path = ext[rel + 1:rel + 1 + ext[rel]].decode()
        data = rc4(key, bytes(b[pos:pos + size]))
        b[pos:pos + size] = data
        # The TOC CRC is ~crc32 of the bytes as stored, so it must follow the decrypted data.
        struct.pack_into("<I", b, HEADER_SIZE + i * TOC_ENTRY + TOC_CRC, ~zlib.crc32(data) & 0xFFFFFFFF)
        entries.append((path, pos, size, orig, ctype))
    b[ENC_OFFSET] = 0
    Path(dst).write_bytes(bytes(b))
    return h, keys.index(key), entries

if __name__ == "__main__":
    h, ki, entries = twin(sys.argv[1], sys.argv[2], sys.argv[3])
    print(h, "key", ki, "files", len(entries))
