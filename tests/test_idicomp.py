"""Tests for the Ford IDICOMP decompressor and POD BAY archive parsing.

`decompress_ford` is the heart of the extractor (verified at 0% error across
2,146 pages), so these tests pin its exact behaviour. Rather than feed it bytes
captured from a real (copyrighted, gitignored) archive, we build the compressed
streams here with an *independent* encoder written straight from the documented
format (docs/FORMAT_SPECIFICATION.md section 3). A decoder bug that diverges
from the spec therefore fails a round-trip, instead of two wrong implementations
agreeing.

Flag mechanism (independent restatement of the spec):
  * items are grouped in runs of 16; each run is preceded by a 16-bit
    little-endian flag word, consumed MSB-first (mask 0x8000, 0x4000, ..., 0x0001);
  * a 0 bit => the next item is a literal byte; a 1 bit => a reference token.
"""
import struct

import pytest

import extract_ford_arc as arc


# ----------------------------------------------------------------------------
# An independent IDICOMP encoder, used only by the tests.
# ----------------------------------------------------------------------------

class Encoder:
    """Builds an IDICOMP stream from a list of items.

    Each item is one of:
      ("lit",  byte)                         literal
      ("rle_s", char, count)                 RLE short, 3 <= count <= 18
      ("rle_l", char, length)                RLE long, length >= 19
      ("lz_s", distance, length)             LZ short, 3 <= length <= 15
      ("lz_l", distance, length)             LZ long, length >= 16

    Items are flagged literal (0) or token (1) and emitted in runs of 16 with a
    leading little-endian flag word, exactly as the decoder consumes them.
    """

    def __init__(self):
        self.items = []

    def lit(self, b):                       self.items.append(("lit", b)); return self
    def rle_short(self, c, n):              self.items.append(("rle_s", c, n)); return self
    def rle_long(self, c, n):               self.items.append(("rle_l", c, n)); return self
    def lz_short(self, distance, length):   self.items.append(("lz_s", distance, length)); return self
    def lz_long(self, distance, length):    self.items.append(("lz_l", distance, length)); return self

    @staticmethod
    def _token_bytes(item):
        kind = item[0]
        if kind == "lit":
            return False, bytes([item[1]])
        if kind == "rle_s":
            _, char, count = item
            assert 3 <= count <= 18
            lo = count - 3
            return True, bytes([(0x0 << 4) | lo, char])
        if kind == "rle_l":
            _, char, length = item
            assert length >= 19
            rem = length - 19
            lo = rem & 0x0F
            b2 = rem >> 4
            assert b2 <= 0xFF
            return True, bytes([(0x1 << 4) | lo, b2, char])
        if kind == "lz_s":
            _, distance, length = item
            assert 3 <= length <= 15
            d = distance - 3
            lo = d & 0x0F
            b2 = d >> 4
            assert b2 <= 0xFF
            return True, bytes([(length << 4) | lo, b2])
        if kind == "lz_l":
            _, distance, length = item
            assert length >= 16
            d = distance - 3
            lo = d & 0x0F
            b2 = d >> 4
            b3 = length - 16
            assert b2 <= 0xFF and b3 <= 0xFF
            return True, bytes([(0x2 << 4) | lo, b2, b3])
        raise ValueError(kind)

    def build(self):
        out = bytearray()
        for start in range(0, len(self.items), 16):
            group = self.items[start:start + 16]
            flags = 0
            payloads = []
            for pos, item in enumerate(group):
                is_token, data = self._token_bytes(item)
                if is_token:
                    flags |= 0x8000 >> pos
                payloads.append(data)
            out += struct.pack("<H", flags)
            for d in payloads:
                out += d
        return bytes(out)


# ----------------------------------------------------------------------------
# decompress_ford
# ----------------------------------------------------------------------------

def test_all_literals_single_flag_word():
    enc = Encoder()
    for b in b"Hello, Pod Bay":
        enc.lit(b)
    assert bytes(arc.decompress_ford(enc.build())) == b"Hello, Pod Bay"


def test_flag_word_reload_after_16_items():
    # 20 literals forces a second flag word (16 items per word).
    data = bytes(range(20))
    enc = Encoder()
    for b in data:
        enc.lit(b)
    out = bytes(arc.decompress_ford(enc.build()))
    assert out == data
    assert len(out) == 20


def test_rle_short_bounds():
    # count = lo + 3, so lo=0 -> 3 repeats, lo=15 -> 18 repeats.
    enc = Encoder().rle_short(ord("x"), 3).rle_short(ord("y"), 18)
    out = bytes(arc.decompress_ford(enc.build()))
    assert out == b"x" * 3 + b"y" * 18


def test_rle_long_minimum_and_larger():
    # length = lo + (b2<<4) + 19; minimum is 19 (lo=0, b2=0).
    enc = Encoder().rle_long(ord("z"), 19).rle_long(ord("Q"), 100)
    out = bytes(arc.decompress_ford(enc.build()))
    assert out == b"z" * 19 + b"Q" * 100


def test_lz_short_back_reference():
    # Emit "ABCD" as literals, then copy "BCD" (distance 3, length 3).
    enc = Encoder()
    for b in b"ABCD":
        enc.lit(b)
    enc.lz_short(distance=3, length=3)  # copies B, C, D
    out = bytes(arc.decompress_ford(enc.build()))
    assert out == b"ABCD" + b"BCD"


def test_lz_long_back_reference():
    base = b"The quick brown fox."
    enc = Encoder()
    for b in base:
        enc.lit(b)
    # Copy the first 16 bytes ("The quick brown ") from distance len(base).
    enc.lz_long(distance=len(base), length=16)
    out = bytes(arc.decompress_ford(enc.build()))
    assert out == base + base[:16]


def test_lz_overlap_copies_byte_by_byte():
    # Classic LZSS overlap: distance < length means the copy reads bytes it is
    # itself producing. The codec's minimum distance is 3 (distance = lo+3+...),
    # so start "ABC" then copy distance=3 length=7 -> the 3-byte run tiles out.
    enc = Encoder().lit(ord("A")).lit(ord("B")).lit(ord("C")).lz_short(distance=3, length=7)
    out = bytes(arc.decompress_ford(enc.build()))
    assert out == b"ABC" + b"ABCABCA"


def test_mixed_literals_and_tokens():
    enc = Encoder()
    for b in b"abc":
        enc.lit(b)
    enc.lz_short(distance=3, length=3)  # copies "abc" -> "abcabc"
    enc.rle_short(ord("!"), 4)          # "!!!!"
    out = bytes(arc.decompress_ford(enc.build()))
    assert out == b"abcabc" + b"!" * 4


def test_empty_input():
    assert bytes(arc.decompress_ford(b"")) == b""


# ----------------------------------------------------------------------------
# decode_record_name  (6-bit symbol unpacking)
# ----------------------------------------------------------------------------

def _encode_record_name(stem, marker=b"\x62\xc6"):
    """Independent encoder: pack up to 8 symbols (6 bits each, MSB-first) into
    6 bytes, then append the 2-byte type marker. Inverse of decode_record_name.
    """
    assert len(stem) <= 8
    bits = 0
    for i in range(8):
        ch = stem[i] if i < len(stem) else None
        if ch is None:
            sym = 0
        elif ch.isdigit():
            sym = 1 + (ord(ch) - ord("0"))
        elif "A" <= ch <= "Z":
            sym = 11 + (ord(ch) - ord("A"))
        elif ch == "_":
            sym = 37
        else:
            raise ValueError(ch)
        bits |= sym << (42 - i * 6)
    return bits.to_bytes(6, "big") + marker


def test_record_name_documented_vector():
    # From the docstring: these 6 bytes decode to "T50T100A".
    assert arc.decode_record_name(b"\x78\x60\x5e\x08\x10\x4b\x00\x00") == "T50T100A"


@pytest.mark.parametrize("stem", ["T50T100A", "Y5111B", "ABCDEFGH", "A1", "Z", "FOO_BAR"])
def test_record_name_round_trip(stem):
    assert arc.decode_record_name(_encode_record_name(stem)) == stem


def test_record_name_padding_truncates():
    # Trailing zero symbols are padding and drop off the end.
    assert arc.decode_record_name(_encode_record_name("AB")) == "AB"


def test_record_name_ignores_trailing_marker_bytes():
    a = arc.decode_record_name(_encode_record_name("HELLO", marker=b"\x62\xc6"))
    b = arc.decode_record_name(_encode_record_name("HELLO", marker=b"\xff\xff"))
    assert a == b == "HELLO"


# ----------------------------------------------------------------------------
# parse_arc_header
# ----------------------------------------------------------------------------

def _build_archive(records, magic=b"POD BAY"):
    """records: list of (stem, offset, meta3). Returns header bytes."""
    out = bytearray(magic)
    out += b"\x01\x00"
    out += struct.pack("<I", len(records))
    for stem, offset, meta in records:
        out += _encode_record_name(stem)[:8]
        out += struct.pack("<I", offset)
        out += meta
    return bytes(out)


def test_parse_header_v1():
    data = _build_archive([("STA", 100, b"\x01\x02\x03"),
                           ("Y5111B", 250, b"\x00\x00\x00")])
    hdr = arc.parse_arc_header(data)
    assert hdr["magic"] == "POD BAY"
    assert hdr["version"] == 1
    assert hdr["record_count"] == 2
    assert hdr["data_start"] == 13 + 2 * 15
    assert hdr["records"][0]["name"] == "STA"
    assert hdr["records"][0]["offset"] == 100
    assert hdr["records"][1]["name"] == "Y5111B"
    assert hdr["records"][1]["offset"] == 250


def test_parse_header_v2_magic():
    hdr = arc.parse_arc_header(_build_archive([("AB", 1, b"\x00\x00\x00")], magic=b"BAY POD"))
    assert hdr["version"] == 2


def test_parse_header_bad_magic_raises():
    with pytest.raises(ValueError):
        arc.parse_arc_header(b"NOT AN ARCHIVE" + b"\x00" * 20)


# ----------------------------------------------------------------------------
# read_block_payload / extract_blocks  (chunking)
# ----------------------------------------------------------------------------

MARKER = arc.MARKER


def test_block_compressed_positive_size():
    payload = b"compressed-bytes"
    data = MARKER + struct.pack("<h", len(payload)) + payload
    content, compressed, is_end = arc.read_block_payload(data, 0)
    assert content == payload
    assert compressed is True and is_end is False


def test_block_raw_negative_size():
    payload = b"GIF89a-rawdata"
    data = MARKER + struct.pack("<h", -len(payload)) + payload
    content, compressed, is_end = arc.read_block_payload(data, 0)
    assert content == payload
    assert compressed is False and is_end is False


def test_block_end_marker_zero_size():
    data = MARKER + struct.pack("<h", 0)
    content, compressed, is_end = arc.read_block_payload(data, 0)
    assert content == b"" and is_end is True


def test_block_chunk_reassembly(monkeypatch):
    # Shrink the chunk cap so we can exercise multi-chunk reassembly cheaply.
    monkeypatch.setattr(arc, "CHUNK_CAP", 4)
    # First chunk exactly CHUNK_CAP (=> continues), second chunk shorter (=> ends).
    chunk1 = b"ABCD"           # len == cap, signals "more follows"
    chunk2 = b"EF"             # len < cap, final chunk
    data = (MARKER
            + struct.pack("<h", len(chunk1)) + chunk1
            + struct.pack("<h", len(chunk2)) + chunk2)
    content, compressed, is_end = arc.read_block_payload(data, 0)
    assert content == b"ABCDEF"
    assert compressed is True and is_end is False


def test_extract_blocks_finds_all_markers():
    b1 = MARKER + struct.pack("<h", 3) + b"xyz"
    b2 = MARKER + struct.pack("<h", -3) + b"GIF"
    end = MARKER + struct.pack("<h", 0)
    blocks = arc.extract_blocks(b1 + b2 + end)
    assert len(blocks) == 3
    assert blocks[0]["compressed"] is True and blocks[0]["content"] == b"xyz"
    assert blocks[1]["compressed"] is False and blocks[1]["content"] == b"GIF"
    assert blocks[2]["type"] == "end"
