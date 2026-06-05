#!/usr/bin/env python3
"""
Ford TSO Service Manual Extractor
Extracts workshop manual content from Ford's proprietary POD BAY / IDICOMP
archive format (.ARC files) used in the 1996-2003 era TSO (Technical Service
Online) disc-based service manuals.

Supports: STA.ARC (Service/Workshop), ETA.ARC (EVTM/Wiring), and other .ARC files.

Usage:
    python3 extract_ford_arc.py STA.ARC [--output-dir ./output] [--format text|html|both]
    python3 extract_ford_arc.py ETA.ARC --output-dir ./wiring
    python3 extract_ford_arc.py *.ARC --output-dir ./full_manual
"""

import argparse
import json
import os
import re
import struct
import sys
from pathlib import Path


def decompress_ford(compressed: bytes) -> bytearray:
    """
    Decompress Ford IDICOMP compressed data.

    Format: Hybrid RLE + LZ with 16-bit flag words.

    Flag mechanism:
    - 16-bit little-endian flag word, processed MSB-first
    - Initial mask = 0x8000, shifted right after each item
    - When mask reaches 0, a new flag word is read
    - Flag bit 0 = literal byte (copy as-is)
    - Flag bit 1 = reference token (RLE or LZ back-reference)

    Reference token encoding (determined by high nibble of first byte):
    - 0x0_ (hi=0): RLE short — repeat next byte (lo+3) times
    - 0x1_ (hi=1): RLE long  — repeat: length = lo + (next_byte<<4) + 19, char = byte after
    - 0x2_ (hi=2): LZ long   — distance = lo+3 + (next_byte<<4), length = next_next_byte + 16
    - 0x3_-0xF_ (hi>=3): LZ short — distance = lo+3 + (next_byte<<4), length = hi
    """
    output = bytearray()
    i = 0
    flag_mask = 0
    flags = 0

    while i < len(compressed):
        flag_mask >>= 1
        if flag_mask == 0:
            if i + 1 >= len(compressed):
                break
            flags = compressed[i] | (compressed[i + 1] << 8)
            i += 2
            flag_mask = 0x8000

        if i >= len(compressed):
            break

        if (flags & flag_mask) == 0:
            # Literal byte
            output.append(compressed[i])
            i += 1
        else:
            # Reference token
            if i >= len(compressed):
                break
            b = compressed[i]
            i += 1
            hi = (b >> 4) & 0x0F
            lo = b & 0x0F

            if hi == 0:
                # RLE short: repeat next byte (lo+3) times
                if i >= len(compressed):
                    break
                char = compressed[i]
                i += 1
                output.extend(bytes([char]) * (lo + 3))

            elif hi == 1:
                # RLE long: length = lo + (next_byte << 4) + 19
                if i + 1 >= len(compressed):
                    break
                b2 = compressed[i]
                char = compressed[i + 1]
                i += 2
                length = lo + (b2 << 4) + 19
                output.extend(bytes([char]) * length)

            elif hi == 2:
                # LZ long: distance = lo+3 + (next_byte<<4), length = next_next_byte + 16
                if i + 1 >= len(compressed):
                    break
                b2 = compressed[i]
                b3 = compressed[i + 1]
                i += 2
                distance = lo + 3 + (b2 << 4)
                length = b3 + 16
                start = len(output) - distance
                for k in range(length):
                    output.append(output[start + k])

            else:
                # LZ short (hi >= 3): distance = lo+3 + (next_byte<<4), length = hi
                if i >= len(compressed):
                    break
                b2 = compressed[i]
                i += 1
                distance = lo + 3 + (b2 << 4)
                length = hi
                start = len(output) - distance
                for k in range(length):
                    output.append(output[start + k])

    return output


def decode_record_name(name8: bytes) -> str:
    """Decode the 8-byte record name field into the real filename stem.

    Reverse-engineered: the first 6 bytes pack 8 characters as 6-bit symbols,
    big-endian / MSB-first (48 bits total). The trailing 2 bytes are a constant
    type marker and are ignored. Symbol alphabet:

        0       padding / end of name
        1..10   digits '0'..'9'
        11..36  letters 'A'..'Z'
        37      underscore '_'

    Validated against 65 figures whose image dimensions uniquely identify their
    archive block (e.g. b'\\x78\\x60\\x5e\\x08\\x10\\x4b' -> "T50T100A").
    Returns the stem without extension (callers append '.gif').
    """
    bits = int.from_bytes(name8[:6], 'big')
    out = []
    for i in range(8):
        sym = (bits >> (42 - i * 6)) & 0x3F
        if sym == 0:
            continue
        if 1 <= sym <= 10:
            out.append(chr(ord('0') + sym - 1))
        elif 11 <= sym <= 36:
            out.append(chr(ord('A') + sym - 11))
        elif sym == 37:
            out.append('_')
        else:
            out.append('?')  # unknown symbol; should not occur in practice
    return ''.join(out)


def parse_arc_header(data: bytes) -> dict:
    """
    Parse the POD BAY archive header.

    File structure:
    - Bytes 0-6: Magic "POD BAY" (7 bytes) or "BAY POD" (v2)
    - Bytes 7-8: Version marker (0x01 0x00)
    - Bytes 9-12: Record count (uint32 LE)
    - Byte 13+: Record table (record_count × 15 bytes each)

    Each record entry (15 bytes):
    - Bytes 0-7: Filename (8 bytes, null-padded)
    - Bytes 8-11: File offset (uint32 LE)
    - Bytes 12-14: Metadata (3 bytes)
    """
    magic = data[:7]
    if magic == b'POD BAY':
        version = 1
    elif magic == b'BAY POD':
        version = 2
    else:
        raise ValueError(f"Not a POD BAY archive. Magic: {magic!r}")

    record_count = struct.unpack_from('<I', data, 9)[0]

    records = []
    for i in range(record_count):
        offset = 13 + i * 15
        name_raw = data[offset:offset + 8]
        file_offset = struct.unpack_from('<I', data, offset + 8)[0]
        meta = data[offset + 12:offset + 15]

        records.append({
            'index': i,
            'name': decode_record_name(name_raw),
            'offset': file_offset,
            'meta': meta.hex()
        })

    return {
        'magic': magic.decode('ascii'),
        'version': version,
        'record_count': record_count,
        'records': records,
        'data_start': 13 + record_count * 15
    }


# Block payloads are capped at this many bytes per chunk. Files larger than
# this are split into consecutive chunks, each with its own signed int16 size
# field and NO intervening IDICOMP marker. |size| == CHUNK_CAP signals that
# another chunk follows; a shorter chunk is the final one.
CHUNK_CAP = 16384

MARKER = b'\x01IDICOMP\x01'


def read_block_payload(data: bytes, pos: int):
    """Read a block's full payload starting at the IDICOMP marker at `pos`.

    Returns (payload: bytes, compressed: bool, is_end: bool).

    Each chunk is an int16 size field (signed, little-endian) followed by
    |size| bytes: positive => compressed, negative => raw, zero => end of
    stream. When a chunk's length equals CHUNK_CAP the file continues in the
    next chunk (no marker between them), so we concatenate until a shorter
    chunk closes the file. The block's compressed flag is taken from its first
    chunk. The exact-multiple edge case is handled by stopping if the next
    bytes are a new IDICOMP marker.
    """
    p = pos + 9
    first = struct.unpack_from('<h', data, p)[0]
    if first == 0:
        return b'', False, True
    compressed = first > 0

    out = bytearray()
    while True:
        size = struct.unpack_from('<h', data, p)[0]
        p += 2
        if size == 0:
            break
        n = abs(size)
        out += data[p:p + n]
        p += n
        if n < CHUNK_CAP:
            break
        # Capped chunk: another chunk follows, UNLESS the file ended exactly on
        # a chunk boundary (next bytes are the following block's marker).
        if data[p:p + 9] == MARKER:
            break

    return bytes(out), compressed, False


def _classify(content: bytes, compressed: bool) -> str:
    """Determine a block's content type from the start of its payload."""
    if compressed:
        if len(content) >= 6:
            flags = content[0] | (content[1] << 8)
            if (flags & 0x8000) == 0 and content[2] == 0x3C:  # '<'
                return 'html'
            if content[2:5] == b'GIF':
                return 'gif'
        return 'compressed'
    if content[:3] == b'GIF':
        return 'gif_raw'
    if content[:1] == b';' or b'wcf' in content[:20]:
        return 'wcf'
    if content[:1] == b'<':
        return 'xml_raw'
    return 'raw'


def extract_blocks(data: bytes) -> list:
    """
    Find and categorize all IDICOMP blocks in the archive.

    Each block begins with a 9-byte marker (\\x01IDICOMP\\x01) followed by one
    or more chunks. See read_block_payload() for the chunking rules: large
    files (e.g. detailed GIF illustrations over 16 KB) are split into multiple
    16384-byte chunks that must be reassembled.
    """
    positions = [m.start() for m in re.finditer(re.escape(MARKER), data)]

    blocks = []
    for idx, pos in enumerate(positions):
        content, compressed, is_end = read_block_payload(data, pos)
        if is_end:
            blocks.append({
                'index': idx, 'position': pos, 'size': 0,
                'type': 'end', 'compressed': False, 'content': b''
            })
            continue
        blocks.append({
            'index': idx,
            'position': pos,
            'size': len(content),
            'type': _classify(content, compressed),
            'compressed': compressed,
            'content': content,
        })

    return blocks


def extract_html_pages(blocks: list) -> list:
    """Decompress all HTML pages from the block list."""
    pages = []
    errors = 0

    for block in blocks:
        if block['type'] == 'html' and block['compressed']:
            try:
                result = decompress_ford(block['content'])
                text = result.decode('utf-8', errors='replace')
                if '<html>' in text.lower()[:100]:
                    pages.append({
                        'block_index': block['index'],
                        'html': text,
                        'size': len(result)
                    })
            except Exception as e:
                errors += 1

    return pages, errors


# UI / navigation chrome images that are not service illustrations.
_NAV_GIF_RE = re.compile(
    r'^(arrowbak|arrowfwd|arrow|ani_|spacer|blank|dot|bullet|line|hr|'
    r'logo|home|print|back|next|btn|nav)', re.IGNORECASE)


def _figure_name(src: str) -> str:
    """Normalize an <img src> to its canonical on-disk filename.

    Extracted GIFs are named from the decoded record name, which is always
    uppercase (stem) with a lowercase '.gif' extension. The manual's HTML,
    however, references some figures in lowercase (e.g. '1p70235a.gif'). To keep
    the manual->diagram linkage working on case-sensitive filesystems (Linux),
    normalize every reference to UPPERCASE stem + lowercase extension so it
    matches the actual file.
    """
    base = src.replace('\\', '/').rsplit('/', 1)[-1]
    if '.' in base:
        stem, ext = base.rsplit('.', 1)
        return f'{stem.upper()}.{ext.lower()}'
    return base.upper()


def is_content_figure(src: str) -> bool:
    """True for service illustrations, False for UI/navigation chrome."""
    return not _NAV_GIF_RE.match(_figure_name(src))


def extract_figures(html: str) -> list:
    """Ordered list of service-illustration filenames referenced by a page."""
    figs = []
    for m in re.finditer(r'<img[^>]*?\bsrc\s*=\s*"([^"]+)"', html, re.IGNORECASE):
        name = _figure_name(m.group(1))
        if is_content_figure(name) and name not in figs:
            figs.append(name)
    return figs


def html_to_text(html: str) -> str:
    """Convert HTML to plain text, preserving structure and figure references."""
    text = html
    # Remove scripts and styles
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Decode entities
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
    text = text.replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&reg;', '\u00ae').replace('&deg;', '\u00b0')
    text = text.replace('&plusmn;', '\u00b1')
    # Preserve service illustrations as inline figure markers (drop UI chrome).
    def _img_repl(m):
        src = _figure_name(m.group(1))
        return f'\n[FIGURE: {src}]\n' if is_content_figure(src) else ' '
    text = re.sub(r'<img[^>]*?\bsrc\s*=\s*"([^"]+)"[^>]*>', _img_repl, text, flags=re.IGNORECASE)
    # Convert block elements to newlines
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</?(?:p|div|tr|li|h[1-6]|ol|ul|table|td|th|hr)[^>]*>', '\n', text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Clean whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n\n', text)
    return text.strip()


def extract_section_info(text: str) -> dict:
    """Extract section number and name from page text."""
    sec_match = re.search(r'Section (\d+-\d+)', text)
    section = sec_match.group(1) if sec_match else ''

    name_match = re.search(r'Section \d+-\d+: ([A-Za-z][\w ,/\-&;()\u2014]+)', text)
    name = name_match.group(1).strip()[:100] if name_match else ''

    return {'section': section, 'name': name}


def _gif_filename(block: dict) -> str:
    """Name a GIF by its decoded record name; fall back to block index."""
    name = block.get('name')
    if name and re.fullmatch(r'[A-Z0-9_]+', name):
        return f'{name}.gif'
    return f'image_{block["index"]:04d}.gif'


def extract_gifs(blocks: list, output_dir: Path):
    """Extract all GIF images, named by their real (decoded) filename.

    Returns the set of written filenames so the caller can validate that figure
    references in the manual text resolve to actual files.
    """
    gif_dir = output_dir / 'images'
    gif_dir.mkdir(exist_ok=True)

    written = set()
    for block in blocks:
        data = None
        if block['type'] == 'gif_raw':
            data = block['content']
        elif block['type'] == 'gif' and block['compressed']:
            try:
                result = decompress_ford(block['content'])
                if result[:3] == b'GIF':
                    data = result
            except Exception:
                data = None
        if data is None:
            continue
        fname = _gif_filename(block)
        (gif_dir / fname).write_bytes(data)
        written.add(fname)

    return written


def main():
    parser = argparse.ArgumentParser(
        description='Extract Ford TSO service manual from POD BAY / IDICOMP archives'
    )
    parser.add_argument('archives', nargs='+', help='Path(s) to .ARC file(s)')
    parser.add_argument('--output-dir', '-o', default='./output',
                        help='Output directory (default: ./output)')
    parser.add_argument('--format', choices=['text', 'html', 'both'], default='text',
                        help='Output format (default: text)')
    parser.add_argument('--extract-images', action='store_true',
                        help='Also extract GIF illustrations')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')

    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for arc_path in args.archives:
        print(f"\n{'=' * 60}")
        print(f"Processing: {arc_path}")
        print(f"{'=' * 60}")

        with open(arc_path, 'rb') as f:
            data = f.read()

        # Parse header
        try:
            header = parse_arc_header(data)
        except ValueError as e:
            print(f"  ERROR: {e}")
            continue

        print(f"  Magic: {header['magic']}")
        print(f"  Records: {header['record_count']}")

        # Extract blocks and attach each block's real filename via the record
        # table (record offsets land exactly on IDICOMP markers = block starts).
        blocks = extract_blocks(data)
        name_by_pos = {r['offset']: r['name'] for r in header['records']}
        for b in blocks:
            b['name'] = name_by_pos.get(b['position'])

        block_types = {}
        for b in blocks:
            block_types[b['type']] = block_types.get(b['type'], 0) + 1
        print(f"  Blocks: {len(blocks)} total")
        for bt, count in sorted(block_types.items()):
            print(f"    {bt}: {count}")

        # Extract HTML pages
        pages, errors = extract_html_pages(blocks)
        print(f"  HTML pages extracted: {len(pages)} (errors: {errors})")

        if not pages:
            print("  No HTML pages found in this archive.")
            continue

        # Build section index
        section_data = {}
        for page in pages:
            plain = html_to_text(page['html'])
            info = extract_section_info(plain)
            page['plain_text'] = plain
            page['section'] = info['section']
            page['section_name'] = info['name']
            page['figures'] = extract_figures(page['html'])

            if info['section']:
                if info['section'] not in section_data:
                    section_data[info['section']] = {
                        'name': info['name'],
                        'pages': [],
                        'total_chars': 0
                    }
                section_data[info['section']]['pages'].append(page['block_index'])
                section_data[info['section']]['total_chars'] += len(plain)

        # Determine output filename base from archive name
        arc_name = Path(arc_path).stem

        # Write plain text output
        if args.format in ('text', 'both'):
            txt_path = output_dir / f'{arc_name}_manual.txt'
            with open(txt_path, 'w', encoding='utf-8') as f:
                for page in pages:
                    f.write('=' * 80 + '\n')
                    f.write(f'PAGE {page["block_index"]}\n')
                    f.write('=' * 80 + '\n')
                    f.write(page['plain_text'] + '\n\n')
            print(f"  Text output: {txt_path} ({txt_path.stat().st_size:,} bytes)")

        # Write HTML output
        if args.format in ('html', 'both'):
            html_dir = output_dir / f'{arc_name}_html'
            html_dir.mkdir(exist_ok=True)
            for page in pages:
                page_path = html_dir / f'page_{page["block_index"]:04d}.html'
                page_path.write_text(page['html'], encoding='utf-8')
            print(f"  HTML output: {html_dir}/ ({len(pages)} files)")

        # Write section index
        index = []
        for sec in sorted(section_data.keys(), key=lambda s: [int(x) for x in s.split('-')]):
            d = section_data[sec]
            index.append({
                'section': sec,
                'name': d['name'],
                'page_count': len(d['pages']),
                'total_chars': d['total_chars'],
                'first_page': min(d['pages']),
                'last_page': max(d['pages'])
            })

        index_path = output_dir / f'{arc_name}_section_index.json'
        with open(index_path, 'w') as f:
            json.dump(index, f, indent=2)
        print(f"  Section index: {index_path} ({len(index)} sections)")

        # Extract images (named by their real decoded filename)
        written = set()
        if args.extract_images:
            written = extract_gifs(blocks, output_dir)
            print(f"  Images extracted: {len(written)}")

        # Write figures index: which illustrations each page references, and
        # whether the referenced file was extracted. This is the manual->diagram
        # linkage that get_diagram relies on.
        figures_index = []
        all_referenced = set()
        for page in pages:
            if not page.get('figures'):
                continue
            all_referenced.update(page['figures'])
            figures_index.append({
                'page': page['block_index'],
                'section': page.get('section') or None,
                'figures': page['figures'],
            })
        fig_path = output_dir / f'{arc_name}_figures.json'
        with open(fig_path, 'w') as f:
            json.dump(figures_index, f, indent=2)
        print(f"  Figures index: {fig_path} "
              f"({len(figures_index)} pages reference {len(all_referenced)} illustrations)")
        if written:
            missing = {f for f in all_referenced if f not in written}
            print(f"    referenced figures resolved to files: "
                  f"{len(all_referenced) - len(missing)}/{len(all_referenced)}"
                  + (f" (missing {len(missing)})" if missing else ""))

        # Print section summary
        if args.verbose and section_data:
            print(f"\n  Section Summary:")
            for item in index:
                print(f"    {item['section']}: {item['name'][:50]:50s} "
                      f"{item['page_count']:3d} pages")

    print(f"\nDone. Output in: {output_dir}")


if __name__ == '__main__':
    main()
