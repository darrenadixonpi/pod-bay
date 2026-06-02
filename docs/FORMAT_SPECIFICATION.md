# Ford TSO Archive Format Specification & Reverse Engineering Process

## Document Purpose

This document describes the complete reverse engineering of Ford Motor Company's
proprietary POD BAY / IDICOMP archive format used in the TSO (Technical Service
Online) dealer service manual system, circa 1996-2003. It covers the archive
structure, the compression algorithm, and the full process used to crack the
format by disassembling the `tsobrowser.exe` application.

This serves as both a format specification for anyone implementing an extractor,
and a case study in reverse engineering a proprietary binary format.

---

## 1. Background

### The TSO System

Ford distributed factory service manuals to dealerships on optical discs
(initially CD-ROM, later DVD). The system was called TSO — Technical Service
Online. Each disc contained:

- A VirtualBox OVA virtual machine image (later distributions)
- Or a raw ISO with InstallShield installer (earlier distributions)

Inside the VM or installed application:

```
DATA/
├── DATABASE/
│   └── US/
│       └── EN/           ← Access MDB wiring databases (87+ files)
├── SERVICE/
│   ├── STA.ARC           ← Service manual archive (vehicle code A)
│   ├── STB.ARC           ← Service manual archive (vehicle code B)
│   └── ...
├── EVTM/
│   ├── ETA.ARC           ← EVTM wiring diagrams (vehicle code A)
│   └── ...
└── ...
TSO/
├── tsobrowser.exe        ← The viewer application
├── objects/
│   ├── TSBASP.dll        ← Server-side components
│   └── ...
└── ...
```

### File Naming Convention

Ford's 3-letter naming scheme:

| Position | Meaning | Known Codes |
|----------|---------|-------------|
| 1st | Content type | E=EVTM, S=Service Manual, V=Other |
| 2nd | Model year | S=1995, T=1996, V=1997, W=1998, X=1999 |
| 3rd | Vehicle family | A=Crown Vic/Grand Marquis/Town Car, C=Mark VIII, D=T-Bird/Cougar, H=Taurus SHO, L=Explorer/Ranger, O=Econoline |

Example: `STA.ARC` = Service manual, 1996, Crown Vic/Grand Marquis/Town Car

---

## 2. POD BAY Archive Format

### File Header

```
Offset  Size  Description
------  ----  -----------
0x00    7     Magic string: "POD BAY" (ASCII, version 1)
                        or: "BAY POD" (ASCII, version 2)
0x07    2     Version marker: 0x01 0x00
0x09    4     Record count (uint32 little-endian)
0x0D    ...   Record table begins
```

### Record Table

Each record is 15 bytes:

```
Offset  Size  Description
------  ----  -----------
0x00    8     Encoded filename (see below — NOT plain ASCII)
0x08    4     File offset within archive (uint32 LE)
0x0C    3     Metadata (purpose varies)
```

The record table starts at byte 13 (0x0D) and contains `record_count` entries.
Total record table size = `record_count × 15` bytes.

Each record's `offset` points **exactly** at an `\x01IDICOMP\x01` marker, so a
record maps 1:1 to a data block (and thus to the HTML page or GIF it contains).

#### Encoded Filename

The 8-byte name field is **not** ASCII (an early draft of this spec assumed it
was; that was wrong). The first 6 bytes pack the filename as **8 symbols of 6
bits each**, read big-endian / MSB-first (6 × 8 = 48 bits = 8 × 6). The
trailing 2 bytes are a constant type marker (`0x62 0xC6` for the archives
examined) and carry no name data.

Symbol alphabet:

| Value | Meaning |
|-------|---------|
| 0 | padding / end of name |
| 1–10 | digits `'0'`–`'9'` (value − 1) |
| 11–36 | letters `'A'`–`'Z'` (value − 11) |
| 37 | underscore `'_'` |

Decoding example — bytes `78 60 5E 08 10 4B`:

```
0x78605E08104B  = 011110 000110 000001 011110 000010 000001 000001 001011
                =   30      6      1     30      2      1      1     11
                =   'T'    '5'    '0'   'T'    '1'    '0'    '0'   'A'   -> "T50T100A"
```

This recovers the real filename (e.g. `T50T100A.gif`), which is what `<IMG SRC>`
tags in the decompressed HTML reference. Without decoding it, extracted images
can only be named by block index and cannot be linked back to the procedures
that show them. Validated against 65 figures whose image dimensions uniquely
identify their block; see `decode_record_name()` in `extract_ford_arc.py`.

### Data Blocks

After the record table, the file data begins. Each logical file in the archive
consists of one or more data blocks, each preceded by a 9-byte marker:

```
Marker: 0x01 "IDICOMP" 0x01    (9 bytes total: \x01IDICOMP\x01)
```

Immediately after the marker:

```
Offset  Size  Description
------  ----  -----------
0x00    2     Block size (int16 signed, little-endian)
0x02    ...   Block data
```

The block size field determines how to handle the data:

- **Positive value**: Compressed data follows (block_size bytes). Pass to decompressor.
- **Negative value**: Raw/uncompressed data follows (|block_size| bytes). Copy directly.
- **Zero**: End-of-stream marker. No more blocks for this file.

### Content Type Detection

After reading block_size bytes of a compressed block, detect the content type by
attempting decompression of the first few bytes:

- If first literal byte after flag word is `<` (0x3C): **HTML page**
- If first bytes decompress to "GIF89a" or "GIF87a": **GIF image**
- If first byte of raw block is `;`: **WCF metadata** (workunit config)
- If first byte of raw block is `<`: **XML/HTML raw data**

---

## 3. IDICOMP Compression Algorithm

### Overview

The compression is a hybrid RLE (Run-Length Encoding) + LZ (Lempel-Ziv) scheme.
It uses 16-bit flag words to distinguish literal bytes from reference tokens.

This was determined by disassembling `tsobrowser.exe` (the Ford TSO viewer
application), specifically:

- The `ArcDump::ExtractFile` export at RVA 0x179D0
- The block reader function at 0x18811
- The actual decompression function at 0x18579

### Flag Mechanism

The compressed stream is organized into groups of up to 16 items, each group
preceded by a 16-bit flag word:

```
[flag_word_16LE] [item_0] [item_1] ... [item_15]
[flag_word_16LE] [item_0] [item_1] ... [item_15]
...
```

The flag word is read as a 16-bit little-endian unsigned integer. Bits are
processed **MSB first**:

```
Initial mask = 0x8000
After each item: mask >>= 1
When mask reaches 0: read new flag word, reset mask = 0x8000
```

For each item:
- **Flag bit = 0**: Literal byte. Read 1 byte from stream, output as-is.
- **Flag bit = 1**: Reference token. Read token bytes and decode (see below).

### Reference Token Encoding

Each reference token starts with a single byte. The high nibble (bits 7-4)
determines the token type and how many additional bytes to consume:

#### Type 0 — RLE Short (high nibble = 0x0)

```
Byte layout: [0x0L] [CHAR]
L = low nibble (0x0-0xF)
Length = L + 3  (range: 3-18)
Output: repeat CHAR for Length bytes
```

Encodes runs of 3-18 identical bytes.

#### Type 1 — RLE Long (high nibble = 0x1)

```
Byte layout: [0x1L] [B2] [CHAR]
L = low nibble
Length = L + (B2 << 4) + 19  (range: 19-4114)
Output: repeat CHAR for Length bytes
```

Encodes runs of 19-4114 identical bytes (e.g., large blocks of spaces or
null bytes in formatted HTML).

#### Type 2 — LZ Long (high nibble = 0x2)

```
Byte layout: [0x2L] [B2] [B3]
L = low nibble
Distance = L + 3 + (B2 << 4)  (range: 3-4098)
Length = B3 + 16  (range: 16-271)
Output: copy Length bytes from (current_position - Distance) in output
```

Encodes long back-references (16-271 bytes) at distances up to ~4KB.

#### Type 3-F — LZ Short (high nibble = 0x3 through 0xF)

```
Byte layout: [0xHL] [B2]
H = high nibble (3-15) = Length
L = low nibble
Distance = L + 3 + (B2 << 4)  (range: 3-4098)
Output: copy Length bytes from (current_position - Distance) in output
```

Encodes short back-references (3-15 bytes). This is the most common token
type, as most repeated HTML patterns (tags, attributes, boilerplate) are
short strings.

### Summary Table

| High Nibble | Type | Extra Bytes | Length Range | Distance Range |
|-------------|------|-------------|-------------|----------------|
| 0x0 | RLE Short | 1 (char) | 3-18 | N/A |
| 0x1 | RLE Long | 2 (ext+char) | 19-4114 | N/A |
| 0x2 | LZ Long | 2 (dist+len) | 16-271 | 3-4098 |
| 0x3-0xF | LZ Short | 1 (dist) | 3-15 | 3-4098 |

### Pseudocode

```python
def decompress(compressed_bytes):
    output = bytearray()
    i = 0
    flag_mask = 0
    flags = 0

    while i < len(compressed_bytes):
        flag_mask >>= 1
        if flag_mask == 0:
            flags = read_uint16_le(compressed_bytes, i)
            i += 2
            flag_mask = 0x8000

        if (flags & flag_mask) == 0:
            # Literal
            output.append(compressed_bytes[i])
            i += 1
        else:
            # Reference token
            b = compressed_bytes[i]; i += 1
            hi = (b >> 4) & 0x0F
            lo = b & 0x0F

            if hi == 0:       # RLE short
                char = compressed_bytes[i]; i += 1
                output.extend([char] * (lo + 3))

            elif hi == 1:     # RLE long
                b2 = compressed_bytes[i]; i += 1
                char = compressed_bytes[i]; i += 1
                output.extend([char] * (lo + (b2 << 4) + 19))

            elif hi == 2:     # LZ long
                b2 = compressed_bytes[i]; i += 1
                b3 = compressed_bytes[i]; i += 1
                dist = lo + 3 + (b2 << 4)
                for k in range(b3 + 16):
                    output.append(output[-dist + k])

            else:             # LZ short (hi >= 3)
                b2 = compressed_bytes[i]; i += 1
                dist = lo + 3 + (b2 << 4)
                for k in range(hi):
                    output.append(output[len(output) - dist + k])

    return output
```

---

## 4. Reverse Engineering Process

### Phase 1: Archive Structure Discovery

**Tools**: Python, hex editor, `strings`

1. **Identified the magic header** by examining the first bytes of .ARC files:
   `50 4F 44 20 42 41 59` = "POD BAY"

2. **Found the record count** at offset 9: a uint32 LE value matching the
   number of files described in metadata.

3. **Located the IDICOMP markers** by searching for `\x01IDICOMP\x01` throughout
   the file. Found 4312 occurrences in a typical STA.ARC.

4. **Determined the record table format** (15 bytes per record) by examining
   the pattern of data between the header and the first IDICOMP marker.

5. **Distinguished compressed from raw blocks** by noting that the int16 value
   after each IDICOMP marker was positive for HTML blocks and negative for
   GIF/metadata blocks. The absolute value matched the actual data length
   to the next marker.

### Phase 2: Identifying the Decompressor Binary

**Tools**: `strings`, `file`, PE header analysis

1. **Ruled out FORDSTAR.EXE** — no IDICOMP or POD BAY strings found. This was
   a dealership network configuration tool, not the viewer.

2. **Identified tsobrowser.exe** in the TSO folder (from the VMDK) as the
   actual viewer. Found `ArcDump` class exports and "POD BAY" string.

3. **Located the ArcDump class exports** in the PE export table:
   - `ArcDump::ArcDump(char*)` — Constructor (opens archive)
   - `ArcDump::ExtractFile(char*)` — Main extraction entry point
   - `ArcDump::FileName(char*)` — Get filename for current record
   - `ArcDump::Seek(char*)` — Seek to named record
   - `ArcDump::Next()` — Advance to next record
   - `ArcDump::Top()` — Reset to first record
   - Plus: `IsValid`, `Length`, `Offset`, `NumberOfRecords`, `eof`

### Phase 3: Disassembly of the Decompression Chain

**Tools**: Python `capstone` disassembler

The decompression involved three nested functions:

#### Function 1: `ArcDump::ExtractFile` (RVA 0x179D0)

High-level orchestrator:
- Opens the output file
- Calls the block reader in a loop
- Writes decompressed output to temp file

Key operations:
- Seeks to the record's offset in the archive
- Reads the IDICOMP block metadata
- Allocates 0x1000-byte (4KB) buffers for I/O
- Calls function 2 for each block

#### Function 2: Block Reader (0x18811)

Reads one block at a time:
- Reads 2-byte block_size from the archive
- If `block_size == 0`: returns 0 (end of stream)
- If `block_size < 0`: reads |block_size| raw bytes directly into output
- If `block_size > 0`: reads block_size bytes into input buffer,
  then calls function 3 (the decompressor)

This is where we confirmed that negative block_size means raw data.

#### Function 3: The Decompressor (0x18579)

The actual decompression loop. Key disassembly findings:

```
0x4185B2: shr dx, 1           ; flag_mask >>= 1
0x4185C3: jne 0x4185DE        ; if mask != 0, skip reload
0x4185C5: mov dx, [ecx]       ; flags = read 16-bit word
0x4185D8: mov word [ebp-0x10], 0x8000  ; reset mask

0x4185F0: and ecx, edx        ; test flags & mask
0x4185F4: jne 0x418614        ; if bit set, go to reference decoder
0x4185F6: mov [eax], dl       ; else: literal byte copy

0x418614: mov al, [edx]       ; read first token byte
0x41861B: sar eax, 4          ; hi = byte >> 4
0x41861E: and eax, 0xF        ; hi &= 0xF
0x41862C: and edx, 0xF        ; lo = byte & 0xF

0x418648: cmp [ebp-0x24], 0   ; switch on hi
0x41864C: je 0x418663         ; case 0: RLE short
0x418652: je 0x4186B0         ; case 1: RLE long
0x418658: je 0x41871D         ; case 2: LZ long
0x41865E: jmp 0x4187A1        ; default: LZ short (hi >= 3)
```

For the RLE short case (hi=0):
```
0x418663: add dx, 3           ; length = lo + 3
0x418693: call 0x419EF0       ; memset(dst, char, length)
```

For the RLE long case (hi=1):
```
0x4186B7: shl eax, 4          ; b2 << 4
0x4186BE: add cx, ax          ; length = lo + (b2 << 4)
0x4186D6: add ax, 0x13        ; length += 19
0x4186FF: call 0x419EF0       ; memset(dst, char, length)
```

For the LZ long case (hi=2):
```
0x418725: add eax, 3          ; distance starts at lo + 3
0x418733: shl edx, 4          ; b2 << 4
0x41873A: add ax, dx          ; distance = lo + 3 + (b2 << 4)
0x418751: movzx ax, [edx]     ; length = b3
0x418762: add dx, 0x10        ; length += 16
0x41877F: sub edx, ecx        ; src = dst - distance
0x418786: call 0x419620       ; memcpy(dst, src, length)
```

For the LZ short case (hi>=3):
```
0x4187A9: add eax, 3          ; distance starts at lo + 3
0x4187B5: shl edx, 4          ; b2 << 4
0x4187BE: add ax, dx          ; distance = lo + 3 + (b2 << 4)
0x4187D7: push edx            ; length = hi (the high nibble itself)
0x4187E3: sub ecx, eax        ; src = dst - distance
0x4187EA: call 0x419620       ; memcpy(dst, src, length)
```

### Phase 4: Verification

The decompressor was verified by extracting all 2146 HTML pages from a
`STA.ARC` file with **zero errors**. The decompressed HTML contains clean,
well-formed content with proper tags, entity references, and readable
service procedure text.

### Key Insights for Future Work

1. **The compressor exists in the same binary** at RVA 0x17DF0. It uses a
   hash table for LZ matching (hash mask passed as parameter). The compressor
   first attempts RLE (run of identical bytes), then falls back to LZ
   (hash-based string matching).

2. **The format supports two archive versions** ("POD BAY" and "BAY POD").
   The block structure is identical; only header parsing differs slightly.

3. **The archive is self-contained** — no external dictionary or state is
   needed between blocks. Each compressed block decompresses independently.

4. **GIF images are typically stored raw** (negative block_size) rather than
   compressed, since GIF already uses LZW compression internally.

---

## 5. MDB Wiring Database Structure

The EVTM (Electrical Vacuum Troubleshooting Manual) data is stored in
Microsoft Access MDB files. Standard tables:

| Table | Contents | Typical Row Count |
|-------|----------|-------------------|
| CELLS | Wiring diagram cell layout data | ~150-300 |
| COMP | Electrical components (name, description, location) | ~250-350 |
| COMPREF | Component cross-references to diagram pages | ~400-600 |
| CONN | Connectors (ID, pin count, location) | ~250-400 |
| CONNREF | Connector cross-references | ~300-500 |
| GRND | Ground points | ~10-20 |
| GRNDREF | Ground cross-references | ~30-50 |
| LOCREF | Location references | ~200-400 |
| PAGEREF | Page-to-page cross-references | ~1000-1500 |
| SPLCREF | Splice cross-references | ~100-200 |
| SPLICE | Wire splices (location, wire identification) | ~150-250 |

These can be extracted using `mdbtools` (Linux) or directly with Access/LibreOffice.

---

## 6. End-to-End Extraction Pipeline

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│  OVA / VMDK │────>│  7z extract  │────>│  .ARC files    │
│  / ISO      │     │  DATA folder │     │  .MDB files    │
└─────────────┘     └──────────────┘     │  .PDF (owner)  │
                                          └───────┬────────┘
                                                  │
                    ┌─────────────────────────────┤
                    │                             │
            ┌───────▼───────┐            ┌────────▼────────┐
            │ extract_ford  │            │ extract_ford    │
            │ _arc.py       │            │ _mdb.py         │
            │               │            │                 │
            │ Decompresses  │            │ Exports tables  │
            │ IDICOMP blocks│            │ to CSV / JSON   │
            └───────┬───────┘            └────────┬────────┘
                    │                             │
                    └─────────────┬───────────────┘
                                  │
                          ┌───────▼───────┐
                          │ build_skill   │
                          │ .py           │
                          │               │
                          │ Packages into │
                          │ Claude skill  │
                          └───────┬───────┘
                                  │
                          ┌───────▼───────┐
                          │ vehicle-name  │
                          │ -skill.tar.gz │
                          │               │
                          │ Ready for     │
                          │ Claude upload │
                          └───────────────┘
```

---

## Appendix A: Compression Algorithm Comparison

The Ford IDICOMP algorithm is a custom variant that doesn't match any standard
compression scheme exactly, but shares characteristics with several:

| Feature | IDICOMP | Classic LZSS | LZ77 | Deflate |
|---------|---------|-------------|------|---------|
| Flag mechanism | 16-bit word, MSB-first | 8-bit byte, LSB-first | Implicit | Huffman coded |
| Literal encoding | Direct byte | Direct byte | Direct byte | Huffman coded |
| RLE support | Built-in (types 0,1) | No | No | Via LZ |
| Back-reference | 2-byte tokens | 2-byte tokens | Variable | Huffman coded |
| Max distance | 4098 | 4096 | 32768 | 32768 |
| Max match length | 271 (LZ long) | 18 | 258 | 258 |
| Dictionary | Sliding window | Ring buffer | Sliding window | Sliding window |
| Block independence | Yes | Yes | Yes | Per deflate block |

The closest match is LZSS, but with a wider flag word (16 vs 8 bits), built-in
RLE, and a different reference encoding scheme.

## Appendix B: Known File Signatures in ARC Archives

| Bytes | Type | Description |
|-------|------|-------------|
| `47 49 46 38 39 61` | GIF89a | GIF image (typically raw blocks) |
| `47 49 46 38 37 61` | GIF87a | GIF image (older format) |
| `3C 68 74 6D 6C 3E` | `<html>` | HTML page (first literal after flag word) |
| `3B 20 77 63 66` | `; wcf` | WCF metadata block |
| `3C 77 6F 72 6B` | `<work` | Workunit XML descriptor |
