"""Engine sound: sound kits (another car's sound), and replacing samples in a kit's FMOD banks (docs/16).

A car's sound is picked by `vehicles\\<car>\\<car>.csdbin` in its pak. It names the FMOD banks the game
loads from `<game>\\Audio\\...` and the events it plays. So:
- **kit**: the car gets another car's csdbin (its whole sound setup) instead of the donor's;
- **samples**: `extract` decodes the kit's own banks to WAVs; WAVs dropped into `sound/replace/<bank>/`
  under a sample's name are packed into a copy of that bank (`rebuild_bank`), which the build installs
  under `Audio\\AMS2KIT\\<car>\\` and points the csdbin at. The bank's events, RPM crossfades and
  effects stay as they are; only the audio they play changes.

<project>/sound/
  kit.json                    the extracted kit: banks, samples, loops (written by extract)
  original/<bank>/<name>.wav  the kit's samples, for listening and as editing templates
  replace/<bank>/<name>.wav   your replacements (same name as the sample they replace)
"""
import json, os, re, shutil, struct, subprocess, wave
from pathlib import Path

from . import game, paks, physics

# ============================================================================ csdbin

ENGINE_BANKS = ("Audio/AMS2/Vehicles/Sort/", "Audio/VW_DEMO/Engine/")   # a car's engine banks (main + _AI); the
                                                                       # rest (limiter, gear shift, wind) are shared
MOD_BANKS = "Audio/AMS2KIT"               # where rebuilt banks are installed


def _serial_split(b):
    """Serialized-struct file (docs/12) -> (header bytes before the table, [(kind, bytes)])."""
    secs = physics.serial_sections(b)
    o = b[4] + 0x10 + 8 * b[3]
    out = []
    for _, size, kind, pad in secs:
        out.append((kind, bytes(b[o:o + size])))
        o += size + pad
    return bytes(b[:0x10]), out


def _serial_join(head, sections):
    out = bytearray(head) + b"".join(struct.pack("<IBBH", len(d), k, -len(d) % 16, 0) for k, d in sections)
    out += bytes(head[4])
    for _, d in sections:
        out += d + bytes(-len(d) % 16)
    if not physics.serial_layout_ok(out):
        raise ValueError("csdbin layout check failed after rewrite")
    return bytes(out)


def _csd_parts(data):
    b = bytes(data)
    if b[:3] != bytes.fromhex("510201"):
        raise ValueError("not a .csdbin file")
    head, secs = _serial_split(b)
    kinds = [k for k, _ in secs]
    body, relocs = secs[kinds.index(1)][1], secs[kinds.index(0x10)][1]
    ptrs = [struct.unpack_from("<Q", relocs, 8 * i)[0] for i in range(len(relocs) // 8)]
    # the string pool is the printable tail of the body; pointers into it are the csdbin's strings
    end = len(body)
    while end and (0x20 <= body[end - 1] < 0x7F or body[end - 1] == 0):
        end -= 1
    targets = [struct.unpack_from("<Q", body, r)[0] for r in ptrs]
    in_pool = [t for t in targets if end <= t < len(body)]
    pool = min(in_pool) if in_pool else len(body)
    return head, secs, body, ptrs, targets, pool


def read_csd(data):
    """[str] in pointer order (banks, events, bank-relative names), as the game reads them."""
    _, _, body, ptrs, targets, pool = _csd_parts(data)
    return [body[t:body.index(b"\0", t)].decode("latin-1") for t in targets if t >= pool]


def csd_banks(data):
    """Bank paths (no extension) the csdbin loads, e.g. Audio/AMS2/Vehicles/Sort/L/Lamborghini_Veneno_AMS2."""
    return list(dict.fromkeys(s for s in read_csd(data) if s.startswith("Audio/")))


def write_csd(data, replace):
    """Rewrite the csdbin's strings ({old: new}); the string pool is rebuilt and the pointers fixed."""
    head, secs, body, ptrs, targets, pool = _csd_parts(data)
    if any(r >= pool for r in ptrs):
        raise ValueError("csdbin pointer field inside the string pool")
    table, offs, new_body = bytearray(), {}, bytearray(body[:pool])
    for r, t in zip(ptrs, targets):
        if t < pool:
            continue
        s = body[t:body.index(b"\0", t)].decode("latin-1")
        s = replace.get(s, s)
        if s not in offs:
            offs[s] = pool + len(table)
            table += s.encode("latin-1") + b"\0"
        struct.pack_into("<Q", new_body, r, offs[s])
    new_body += table
    kinds = [k for k, _ in secs]
    secs[kinds.index(1)] = (1, bytes(new_body))
    return _serial_join(head, secs)


def car_csd(gamedir, car):
    """A car's csdbin bytes, from its pak (car: list_cars entry)."""
    with paks.PakReader(Path(gamedir) / "Pakfiles" / "Vehicles" / car["pak"]) as r:
        want = car["crd"].rsplit("\\", 1)[0].lower() + "\\" + car["name"].lower() + ".csdbin"
        hits = [p for p in r.paths if p.lower() == want] or [p for p in r.paths if p.lower().endswith(".csdbin")]
        return r.read(hits[0]) if hits else None


def kits(gamedir, refresh=False, log=print):
    """Every car's sound: [{name, display, cls, banks, engine}], cached in the data dir."""
    cache = game.DATA_DIR / "sound_kits.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    out = []
    cars = game.list_cars(gamedir)
    log(f"reading the sound setup of {len(cars)} cars...")
    for c in cars:
        try:
            data = car_csd(gamedir, c)
        except Exception:
            data = None
        if not data:
            continue
        strings = read_csd(data)
        engine = next((s for s in strings if s.endswith("_EngineExt")), next((s for s in strings if s.startswith("event:/")), ""))
        out.append({"name": c["name"], "display": c["display"], "cls": c["cls"], "banks": csd_banks(data),
                    "engine": engine.rsplit("/", 1)[-1]})
    game.DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def bank_file(gamedir, bank):
    return Path(gamedir).joinpath(*bank.split("/")).with_suffix(".bank")


def own_banks(banks):
    """The kit's engine banks: the ones whose samples can be replaced (the shared ones would change every car)."""
    return [b for b in banks if b.startswith(ENGINE_BANKS)]


def cars_using(gamedir, bank):
    """Names of the base cars whose csdbin loads this bank."""
    return [k["name"] for k in kits(gamedir) if bank in k["banks"]]


# ============================================================================ FMOD bank / FSB5

FSB_RATES = {1: 8000, 2: 11000, 3: 11025, 4: 16000, 5: 22050, 6: 24000, 7: 32000, 8: 44100, 9: 48000, 10: 96000}
FSB_CHANNELS = (1, 2, 6, 8)
MODE_PCM16, MODE_VORBIS, MODE_FADPCM = 2, 15, 16
CHUNK_CHANNELS, CHUNK_FREQ, CHUNK_LOOP, CHUNK_PEAK = 1, 2, 3, 13


def _riff_chunks(d):
    """[(path, offset, size)] of every leaf chunk in an FMOD bank (RIFF 'FEV ')."""
    out = []

    def walk(o, end, path):
        while o < end - 8:
            cid = d[o:o + 4]
            sz = struct.unpack_from("<I", d, o + 4)[0]
            if cid in (b"RIFF", b"LIST"):
                walk(o + 12, o + 8 + sz, path + "/" + d[o + 8:o + 12].decode("latin-1"))
            else:
                out.append((path + "/" + cid.decode("latin-1"), o, sz))
            o += 8 + sz + (sz & 1)
    walk(0, len(d), "")
    return out


def parse_fsb(d, f):
    """FSB5 at offset f -> dict(mode, samples=[{name, rate, channels, frames, offset, size, loop, chunks}])."""
    if d[f:f + 4] != b"FSB5":
        raise ValueError("no FSB5 block")
    _, ns, shs, nts, ds, mode = struct.unpack_from("<6I", d, f + 4)
    p, nt, data = f + 60, f + 60 + shs, f + 60 + shs + nts
    samples = []
    for i in range(ns):
        m = struct.unpack_from("<Q", d, p)[0]
        start, p = p, p + 8
        s = {"rate": FSB_RATES.get((m >> 1) & 15, 44100), "channels": FSB_CHANNELS[(m >> 5) & 3],
             "offset": ((m >> 7) & 0x7FFFFFF) << 5, "frames": m >> 34, "loop": None, "chunks": []}
        more = m & 1
        while more:
            h = struct.unpack_from("<I", d, p)[0]
            more, size, kind = h & 1, (h >> 1) & 0xFFFFFF, h >> 25
            body = d[p + 4:p + 4 + size]
            if kind == CHUNK_LOOP:
                s["loop"] = list(struct.unpack_from("<II", body))
            elif kind == CHUNK_FREQ:
                s["rate"] = struct.unpack_from("<I", body)[0]
            elif kind == CHUNK_CHANNELS:
                s["channels"] = body[0]
            s["chunks"].append((kind, body))
            p += 4 + size
        s["header"] = (start, p)
        s["name"] = d[nt + struct.unpack_from("<I", d, nt + 4 * i)[0]:].split(b"\0", 1)[0].decode("latin-1") if nts else f"sample_{i}"
        samples.append(s)
    for i, s in enumerate(samples):
        nxt = samples[i + 1]["offset"] if i + 1 < ns else ds
        s["size"] = nxt - s["offset"]
        s["data_at"] = data + s["offset"]
    return {"mode": mode, "samples": samples, "offset": f, "size": 60 + shs + nts + ds}


class Bank:
    """An FMOD Studio bank: its FSB5 sample blocks and the waveforms (WAV chunks) that point into them."""

    def __init__(self, data):
        self.data = bytes(data)
        if self.data[:4] != b"RIFF" or self.data[8:12] != b"FEV ":
            raise ValueError("not an FMOD bank")
        self.chunks = _riff_chunks(self.data)
        self.fsbs = []
        for path, o, sz in self.chunks:
            if path.endswith("/SND "):
                self.fsbs.append(parse_fsb(self.data, self.data.index(b"FSB5", o, o + 8 + sz)))
        # waveform: GUID, u16 0x0c, u16 FSB index, u16 0, u32 subsound, u32 compressed-in-memory flag
        self.waves = [(o + 8, struct.unpack_from("<H", self.data, o + 26)[0], struct.unpack_from("<I", self.data, o + 30)[0])
                      for path, o, sz in self.chunks if path.endswith("/WAV ") and sz >= 30]

    def samples(self):
        """[(fsb index, subsound index, sample)] in bank order."""
        return [(i, j, s) for i, f in enumerate(self.fsbs) for j, s in enumerate(f["samples"])]


# ---- decoding ----

_FADPCM_COEFS = [(0, 0), (60, 0), (122, 60), (115, 52), (98, 55), (0, 0), (0, 0), (0, 0)]
FADPCM_FRAME, FADPCM_SAMPLES = 0x8C, 256


def decode_fadpcm(raw, channels, frames):
    """FMOD's own ADPCM (FSB mode 16) -> int16 array (frames, channels). Every 0x8C-byte frame holds
    256 samples of one channel (channels interleave frame by frame) and carries its own history, so all
    frames are decoded in parallel: per frame u32 coef indexes, u32 shifts (4 bits per 32-sample
    subframe), s16 hist1, s16 hist2, then 8 x 16 bytes of nibbles (low nibble first)."""
    import numpy as np
    n = len(raw) // FADPCM_FRAME
    fr = np.frombuffer(raw[:n * FADPCM_FRAME], dtype=np.uint8).reshape(n, FADPCM_FRAME)
    coefs = fr[:, 0:4].copy().view("<u4")[:, 0].astype(np.int64)
    shifts = fr[:, 4:8].copy().view("<u4")[:, 0].astype(np.int64)
    h1 = fr[:, 8:10].copy().view("<i2")[:, 0].astype(np.int64)
    h2 = fr[:, 10:12].copy().view("<i2")[:, 0].astype(np.int64)
    nib = fr[:, 12:].astype(np.int64)
    nib = np.stack([nib & 15, nib >> 4], axis=2).reshape(n, 256)      # low nibble first
    nib = np.where(nib >= 8, nib - 16, nib)
    table = np.array(_FADPCM_COEFS, dtype=np.int64)
    out = np.empty((n, 256), dtype=np.int64)
    for sub in range(8):
        idx = (coefs >> (4 * sub)) & 15
        c1, c2 = table[idx % 8, 0], table[idx % 8, 1]
        scale = 22 - ((shifts >> (4 * sub)) & 15)
        for k in range(32):
            i = sub * 32 + k
            s = ((nib[:, i] << 28) >> scale)   # nibble as the top of an int32, then scaled
            s = np.clip((s - h2 * c2 + h1 * c1) >> 6, -32768, 32767)
            out[:, i] = s
            h2, h1 = h1, s
    out = out.reshape(-1, channels, 256).transpose(0, 2, 1).reshape(-1, channels)
    return out[:frames].astype(np.int16)


def decode_pcm16(raw, channels, frames):
    import numpy as np
    return np.frombuffer(raw[:frames * channels * 2], dtype="<i2").reshape(-1, channels)


def find_vgmstream():
    """vgmstream-cli, needed only to decode Vorbis-compressed samples: Setup, %AMS2KIT_VGMSTREAM%, PATH."""
    for exe in (game.load_config().get("vgmstream"), os.environ.get("AMS2KIT_VGMSTREAM")):
        if exe and Path(exe).exists():
            return Path(exe)
    found = shutil.which("vgmstream-cli")
    return Path(found) if found else None


def single_fsb(bank, fsb, j):
    """A standalone FSB5 holding one subsound of a bank's FSB (for vgmstream), codec data untouched."""
    d, f = bank.data, bank.fsbs[fsb]
    s = f["samples"][j]
    a, b = s["header"]
    hdr = bytearray(d[a:b])
    m = struct.unpack_from("<Q", hdr)[0] & ~(0x7FFFFFF << 7)   # data offset 0
    struct.pack_into("<Q", hdr, 0, m)
    body = d[s["data_at"]:s["data_at"] + s["size"]]
    head = bytearray(d[f["offset"]:f["offset"] + 60])
    struct.pack_into("<6I", head, 4, 1, 1, len(hdr), 0, len(body), f["mode"])
    return bytes(head) + bytes(hdr) + body


def decode(bank, fsb, j, tmp=None):
    """int16 array (frames, channels) of one sample, or None when it needs vgmstream and there is none."""
    f = bank.fsbs[fsb]
    s = f["samples"][j]
    raw = bank.data[s["data_at"]:s["data_at"] + s["size"]]
    if f["mode"] == MODE_FADPCM:
        return decode_fadpcm(raw, s["channels"], s["frames"])
    if f["mode"] == MODE_PCM16:
        return decode_pcm16(raw, s["channels"], s["frames"])
    exe = find_vgmstream()
    if not exe:
        return None
    import tempfile
    with tempfile.TemporaryDirectory(dir=tmp) as t:
        src, dst = Path(t) / "s.fsb", Path(t) / "s.wav"
        src.write_bytes(single_fsb(bank, fsb, j))
        subprocess.run([str(exe), "-o", str(dst), str(src)], check=True, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return read_wav(dst)["pcm"]


# ---- WAV files ----

def write_wav(path, pcm, rate, loop=None):
    """16-bit WAV; a loop goes in a `smpl` chunk (start, end inclusive), which audio editors keep."""
    import numpy as np
    pcm = np.asarray(pcm, dtype="<i2")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    if loop:
        smpl = struct.pack("<9I", 0, 0, round(1e9 / rate), 60, 0, 0, 0, 1, 0) + struct.pack("<6I", 0, 0, loop[0], loop[1], 0, 0)
        b = bytearray(path.read_bytes()) + b"smpl" + struct.pack("<I", len(smpl)) + smpl
        struct.pack_into("<I", b, 4, len(b) - 8)
        path.write_bytes(b)


def read_wav(path):
    """{pcm: int16 (frames, channels), rate, loop}: PCM 8/16/24/32-bit or float WAVs, loop from `smpl`."""
    import numpy as np
    d = Path(path).read_bytes()
    if d[:4] != b"RIFF" or d[8:12] != b"WAVE":
        raise ValueError(f"{path}: not a WAV file")
    o, fmt, data, loop = 12, None, None, None
    while o + 8 <= len(d):
        cid, sz = d[o:o + 4], struct.unpack_from("<I", d, o + 4)[0]
        body = d[o + 8:o + 8 + sz]
        if cid == b"fmt ":
            tag, ch, rate, _, _, bits = struct.unpack_from("<HHIIHH", body)
            if tag == 0xFFFE and len(body) >= 26:
                tag = struct.unpack_from("<H", body, 24)[0]
            fmt = (tag, ch, rate, bits)
        elif cid == b"data":
            data = body
        elif cid == b"smpl" and len(body) >= 60 and struct.unpack_from("<I", body, 28)[0]:
            loop = list(struct.unpack_from("<II", body, 44))
        o += 8 + sz + (sz & 1)
    if not fmt or data is None:
        raise ValueError(f"{path}: no fmt/data chunk")
    tag, ch, rate, bits = fmt
    if tag == 3 and bits == 32:
        x = np.frombuffer(data[:len(data) // 4 * 4], dtype="<f4")
        pcm = np.clip(np.round(x * 32767), -32768, 32767).astype(np.int16)
    elif tag == 1 and bits == 16:
        pcm = np.frombuffer(data[:len(data) // 2 * 2], dtype="<i2")
    elif tag == 1 and bits == 8:
        pcm = ((np.frombuffer(data, dtype=np.uint8).astype(np.int16) - 128) << 8).astype(np.int16)
    elif tag == 1 and bits == 24:
        b = np.frombuffer(data[:len(data) // 3 * 3], dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        pcm = (((b[:, 0] << 8) | (b[:, 1] << 16) | (b[:, 2] << 24)) >> 16).astype(np.int16)
    elif tag == 1 and bits == 32:
        pcm = (np.frombuffer(data[:len(data) // 4 * 4], dtype="<i4") >> 16).astype(np.int16)
    else:
        raise ValueError(f"{path}: unsupported WAV format (tag {tag}, {bits} bits); save it as 16-bit PCM")
    pcm = pcm[:len(pcm) // ch * ch].reshape(-1, ch)
    if loop and not (0 <= loop[0] < loop[1] < len(pcm)):
        loop = None
    return {"pcm": pcm, "rate": rate, "loop": loop}


# ---- writing ----

def build_fsb_pcm16(samples):
    """FSB5 with PCM16 samples: [{name, pcm (frames, channels) int16, rate, loop}]."""
    import numpy as np
    headers, names, data = bytearray(), bytearray(), bytearray()
    name_offs = []
    for s in samples:
        pcm = np.asarray(s["pcm"], dtype="<i2")
        frames, ch = pcm.shape
        chunks = []
        rate_idx = next((k for k, v in FSB_RATES.items() if v == s["rate"]), 0)
        if not rate_idx:
            rate_idx = 8
            chunks.append((CHUNK_FREQ, struct.pack("<I", s["rate"])))
        ch_idx = FSB_CHANNELS.index(ch) if ch in FSB_CHANNELS else 0
        if ch not in FSB_CHANNELS:
            chunks.append((CHUNK_CHANNELS, bytes([ch])))
        if s.get("loop"):
            chunks.append((CHUNK_LOOP, struct.pack("<II", *s["loop"])))
        peak = float(np.abs(pcm.astype(np.int32)).max(initial=0)) / 32767
        chunks.append((CHUNK_PEAK, struct.pack("<f", peak)))
        m = 1 | (rate_idx << 1) | (ch_idx << 5) | ((len(data) >> 5) << 7) | (frames << 34)
        headers += struct.pack("<Q", m)
        for i, (k, b) in enumerate(chunks):
            headers += struct.pack("<I", (i + 1 < len(chunks)) | (len(b) << 1) | (k << 25)) + b
        data += pcm.tobytes()
        data += bytes(-len(data) % 32)
        name_offs.append(len(names))
        names += s["name"].encode("latin-1", "replace") + b"\0"
    table = b"".join(struct.pack("<I", 4 * len(samples) + o) for o in name_offs) + names
    table += bytes(-(60 + len(headers) + len(table)) % 32)
    head = b"FSB5" + struct.pack("<6I", 1, len(samples), len(headers), len(table), len(data), MODE_PCM16)
    head += bytes(8) + os.urandom(16) + bytes(8)
    return head + bytes(headers) + table + bytes(data)


def rebuild_bank(bank, replacements):
    """A copy of the bank where the waveforms of the replaced samples ({(fsb, sub): sample dict for
    build_fsb_pcm16}) play new PCM audio. The new samples go into one extra FSB5 block and those
    waveforms are pointed at it; everything else (events, the old sample blocks) is kept byte for byte."""
    if not replacements:
        return bank.data
    d = bytearray(bank.data)
    order = list(replacements)
    new_index = len(bank.fsbs)
    hit = 0
    for at, fsb, sub in bank.waves:
        if (fsb, sub) in replacements:
            # FSB index, 0, subsound, 0 = decompressed in memory
            struct.pack_into("<HHII", d, at + 18, new_index, 0, order.index((fsb, sub)), 0)
            hit += 1
    if hit < len(set(order)):
        raise ValueError("a replaced sample has no waveform in the bank")
    fsb_blocks = [bytes(d[f["offset"]:f["offset"] + f["size"]]) for f in bank.fsbs]
    fsb_blocks.append(build_fsb_pcm16([replacements[k] for k in order]))
    # layout: everything up to SNDH unchanged, then SNDH (one more entry), STDT, then one SND chunk per
    # FSB with the FSB 32-byte aligned in the file; SNDH holds each FSB's absolute offset and size
    (_, sndh, sndh_size), = [(p, o, s) for p, o, s in bank.chunks if p.endswith("/SNDH")]
    proj = d.index(b"LIST", 12)
    if d[proj + 8:proj + 12] != b"PROJ":
        raise ValueError("bank without a PROJ list first")
    proj_end = proj + 8 + struct.unpack_from("<I", d, proj + 4)[0]
    tail_proj = bytes(d[sndh + 8 + sndh_size + (sndh_size & 1):proj_end])   # STDT (strings, empty here)
    n = len(fsb_blocks)
    out = bytearray(d[:sndh])
    sndh_at = len(out)
    out += b"SNDH" + struct.pack("<I", 4 + 8 * n) + struct.pack("<HH", 2 * n + 1, 8) + bytes(8 * n)
    out += tail_proj
    struct.pack_into("<I", out, proj + 4, len(out) - proj - 8)
    entries = []
    for blk in fsb_blocks:
        start = len(out) + 8
        pad = -start % 32
        out += b"SND " + struct.pack("<I", pad + len(blk)) + bytes(pad) + blk
        entries.append((start + pad, len(blk)))
        if len(out) & 1:
            out += b"\0"
    for i, (o, s) in enumerate(entries):
        struct.pack_into("<II", out, sndh_at + 12 + 8 * i, o, s)
    struct.pack_into("<I", out, 4, len(out) - 8)
    Bank(out)   # parses back
    return bytes(out)


# ============================================================================ project side

def sound_dir(project):
    return project.root / "sound"


def kit_name(project):
    return project.cfg["sound"]["kit"] or project.cfg["car"]["donor"]


def kit_csd(project, gamedir):
    """The csdbin of the project's kit (the donor's unless [sound] kit names another car)."""
    name = kit_name(project)
    car = next((c for c in game.list_cars(gamedir) if c["name"].lower() == name.lower()), None)
    if car is None:
        raise KeyError(f"sound kit car {name} not found in the game")
    data = car_csd(gamedir, car)
    if not data:
        raise FileNotFoundError(f"{name} has no .csdbin")
    return data


def _safe(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip() or "sample"


def extract(project, gamedir, log=print):
    """Decode the kit's own banks to sound/original/<bank>/<sample>.wav and write sound/kit.json."""
    gamedir = Path(gamedir)
    csd = kit_csd(project, gamedir)
    banks = own_banks(csd_banks(csd))
    root = sound_dir(project)
    orig = root / "original"
    shutil.rmtree(orig, ignore_errors=True)
    info = {"kit": kit_name(project), "banks": {}}
    skipped = 0
    for b in banks:
        bf = bank_file(gamedir, b)
        if not bf.exists():
            log(f"warning: {bf} missing; skipped")
            continue
        bank = Bank(bf.read_bytes())
        short = b.rsplit("/", 1)[-1]
        rows, used = [], set()
        for fsb, j, s in bank.samples():
            fname = _safe(s["name"])
            while fname.lower() in used:
                fname += "_"
            used.add(fname.lower())
            pcm = decode(bank, fsb, j)
            if pcm is None:
                skipped += 1
            else:
                write_wav(orig / short / f"{fname}.wav", pcm, s["rate"], s["loop"])
            rows.append({"file": f"{fname}.wav", "name": s["name"], "fsb": fsb, "sub": j, "rate": s["rate"],
                         "channels": s["channels"], "frames": s["frames"], "seconds": round(s["frames"] / s["rate"], 2),
                         "loop": s["loop"], "codec": {MODE_FADPCM: "fadpcm", MODE_VORBIS: "vorbis", MODE_PCM16: "pcm16"}.get(bank.fsbs[fsb]["mode"], str(bank.fsbs[fsb]["mode"])),
                         "decoded": pcm is not None})
        (root / "replace" / short).mkdir(parents=True, exist_ok=True)
        info["banks"][short] = {"path": b, "samples": rows}
        log(f"{short}: {len(rows)} samples")
    if skipped:
        log(f"{skipped} Vorbis samples not decoded: set vgmstream-cli in Setup to get them as WAVs "
            "(you can still replace them)")
    root.mkdir(parents=True, exist_ok=True)
    (root / "kit.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info


def kit_info(project):
    f = sound_dir(project) / "kit.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def replacements(project):
    """{bank short name: {sample row: replacement wav}} of the WAVs in sound/replace/ that match a sample."""
    info = kit_info(project)
    if not info or info["kit"].lower() != kit_name(project).lower():
        return {}
    out = {}
    for short, b in info["banks"].items():
        folder = sound_dir(project) / "replace" / short
        if not folder.exists():
            continue
        by_name = {r["file"].lower(): r for r in b["samples"]} | {(r["name"] + ".wav").lower(): r for r in b["samples"]}
        hits = {}
        for w in folder.glob("*.wav"):
            r = by_name.get(w.name.lower())
            if r:
                hits[r["name"]] = (r, w)
        if hits:
            out[short] = hits
    return out


def _fit_loop(row, wav):
    """Loop for a replacement: its own smpl loop, else the original's (scaled when the length changed)."""
    if wav["loop"]:
        return wav["loop"]
    if not row["loop"]:
        return None
    n, old = len(wav["pcm"]), row["frames"]
    if n == old:
        return row["loop"]
    a, b = (round(v * n / old) for v in row["loop"])
    return [min(a, n - 2), min(max(b, a + 1), n - 1)]


def build_files(project, gamedir, log=print):
    """(csdbin bytes for the car, {game-relative path: bank bytes}) or (None, {}) for the donor's own
    sound with no replaced samples (the renamed donor csdbin is then kept)."""
    custom = project.cfg["sound"]["replace_samples"] and replacements(project)
    if not project.cfg["sound"]["kit"] and not custom:
        return None, {}
    gamedir = Path(gamedir)
    csd = kit_csd(project, gamedir)
    if project.cfg["sound"]["kit"]:
        log(f"sound kit: {kit_name(project)}")
    banks = {}
    if custom:
        info = kit_info(project)
        moved = {}
        for short, hits in custom.items():
            path = info["banks"][short]["path"]
            bank = Bank(bank_file(gamedir, path).read_bytes())
            reps = {}
            for row, w in hits.values():
                wav = read_wav(w)
                reps[(row["fsb"], row["sub"])] = {"name": row["name"], "pcm": wav["pcm"], "rate": wav["rate"],
                                                  "loop": _fit_loop(row, wav)}
            new_path = f"{MOD_BANKS}/{project.name}/{short}"
            banks[new_path + ".bank"] = rebuild_bank(bank, reps)
            moved[path] = new_path
            log(f"{short}: {len(reps)} samples replaced -> {new_path}.bank")
        csd = write_csd(csd, moved)
    return csd, banks
