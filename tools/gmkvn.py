#!/usr/bin/env python3
"""
gmkvn - pack a Gamiko-style visual novel (scene JSON + images) into a PDF, and read it back.

This is the OPEN EDITION of the packing technique used by Gamiko:

    scene JSON + image files
        -> one JSON tree, where every image is stored as a raw *byte string* value
        -> serialized as binary JSON (format "GVJB", see docs/pdf-container.md)
        -> attached to an ordinary one-page PDF as an embedded file

The Gamiko app uses the same pipeline, but its binary data is additionally
protected by a private protocol before it goes into the PDF. PDFs made by this
tool are therefore NOT readable by the Gamiko app, and Gamiko's PDFs are not
readable by this tool. The point of this tool is to show the idea in plain sight.

Commands
    python3 gmkvn.py pack    story.json [-o out.pdf] [--desc TEXT | --desc-file FILE] [--font FONT.ttf]
    python3 gmkvn.py unpack  story.pdf  out_dir
    python3 gmkvn.py preview story.pdf|story.json [-o out.html] [--no-open]
    python3 gmkvn.py check   story.json

Images referenced as "@b<id>" are looked up next to story.json, first in images/<id>.<ext>,
then <id>.<ext>, for ext in png / jpg / jpeg / webp / gif / bmp.

Only the Python standard library is needed. Pillow is used only by `pack --font`, which
draws the visible page as a picture instead of embedding text.
"""

import argparse
import base64
import datetime
import hashlib
import io
import json
import os
import re
import struct
import sys
import webbrowser
import zlib

MAGIC = b"GVJB"
GVJB_VERSION = 1
ATTACHMENT_NAME = "story.gvnb"
IMAGE_EXTS = ("png", "jpg", "jpeg", "webp", "gif", "bmp")
APP_SIZE_HINT = 16 * 1024 * 1024    # the Gamiko app accepts external files up to 16MB


# ============================================================
# Binary JSON ("GVJB")
# ============================================================
#   file  := "GVJB" version:u8 value
#   value := tag:u8 payload
#     0x00 null      0x01 false      0x02 true
#     0x03 int       zigzag varint
#     0x04 float     8 bytes, IEEE 754 big-endian
#     0x05 string    varint length + UTF-8 bytes
#     0x06 bytes     varint length + raw bytes        <- the JSON extension: images live here
#     0x07 array     varint count + values
#     0x08 object    varint count + (key: varint length + UTF-8) value ...
T_NULL, T_FALSE, T_TRUE, T_INT, T_FLOAT, T_STR, T_BYTES, T_ARRAY, T_OBJECT = range(9)


def _put_varint(out, n):
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return


def _put_str(out, s):
    raw = s.encode("utf-8")
    _put_varint(out, len(raw))
    out += raw


def _encode(out, v):
    if v is None:
        out.append(T_NULL)
    elif v is True:
        out.append(T_TRUE)
    elif v is False:
        out.append(T_FALSE)
    elif isinstance(v, int):
        out.append(T_INT)
        _put_varint(out, v * 2 if v >= 0 else -v * 2 - 1)      # zigzag
    elif isinstance(v, float):
        out.append(T_FLOAT)
        out += struct.pack(">d", v)
    elif isinstance(v, str):
        out.append(T_STR)
        _put_str(out, v)
    elif isinstance(v, (bytes, bytearray)):
        out.append(T_BYTES)
        _put_varint(out, len(v))
        out += v
    elif isinstance(v, (list, tuple)):
        out.append(T_ARRAY)
        _put_varint(out, len(v))
        for x in v:
            _encode(out, x)
    elif isinstance(v, dict):
        out.append(T_OBJECT)
        _put_varint(out, len(v))
        for k, x in v.items():
            _put_str(out, str(k))
            _encode(out, x)
    else:
        raise TypeError(f"cannot encode {type(v).__name__}")


def gvjb_dumps(v):
    out = bytearray(MAGIC)
    out.append(GVJB_VERSION)
    _encode(out, v)
    return bytes(out)


def gvjb_loads(data):
    if data[:4] != MAGIC:
        raise ValueError("not a GVJB file (bad magic)")
    if data[4] != GVJB_VERSION:
        raise ValueError(f"unsupported GVJB version {data[4]}")
    pos = 5

    def varint():
        nonlocal pos
        n = shift = 0
        while True:
            b = data[pos]
            pos += 1
            n |= (b & 0x7F) << shift
            if not b & 0x80:
                return n
            shift += 7

    def raw(n):
        nonlocal pos
        if pos + n > len(data):
            raise ValueError("truncated GVJB data")
        r = data[pos:pos + n]
        pos += n
        return r

    def value():
        nonlocal pos
        tag = data[pos]
        pos += 1
        if tag == T_NULL:
            return None
        if tag == T_FALSE:
            return False
        if tag == T_TRUE:
            return True
        if tag == T_INT:
            z = varint()
            return (z >> 1) ^ -(z & 1)
        if tag == T_FLOAT:
            return struct.unpack(">d", raw(8))[0]
        if tag == T_STR:
            return raw(varint()).decode("utf-8")
        if tag == T_BYTES:
            return bytes(raw(varint()))
        if tag == T_ARRAY:
            return [value() for _ in range(varint())]
        if tag == T_OBJECT:
            obj = {}
            for _ in range(varint()):
                k = raw(varint()).decode("utf-8")
                obj[k] = value()
            return obj
        raise ValueError(f"bad GVJB tag 0x{tag:02x} at offset {pos - 1}")

    v = value()
    if pos != len(data):
        raise ValueError("trailing bytes after GVJB value")
    return v


# ============================================================
# Story helpers
# ============================================================
def image_mime(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", "gif"
    if data[:2] == b"BM":
        return "image/bmp", "bmp"
    return "application/octet-stream", "bin"


def iter_steps(scene):
    steps = scene.get("steps")
    if isinstance(steps, dict):      # an ordered object is allowed; keys are only for humans
        return list(steps.values())
    return steps if isinstance(steps, list) else []


def image_ids(story):
    """Every image id referenced by a background "@b<id>", in first-seen order."""
    ids = []
    for scene in (story.get("scenes") or {}).values():
        if not isinstance(scene, dict):
            continue
        bgs = [scene.get("background")] + [st.get("background") for st in iter_steps(scene) if isinstance(st, dict)]
        for bg in bgs:
            if isinstance(bg, str) and bg.startswith("@b") and bg[2:] not in ids:
                ids.append(bg[2:])
    return ids


def find_image(base_dir, img_id):
    for folder in (os.path.join(base_dir, "images"), base_dir):
        for ext in IMAGE_EXTS:
            p = os.path.join(folder, f"{img_id}.{ext}")
            if os.path.isfile(p):
                return p
    return None


def load_story(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def check_story(story, base_dir=None):
    """Returns (errors, warnings)."""
    E, W = [], []
    if not isinstance(story, dict):
        return ["the top level must be an object"], W
    scenes = story.get("scenes")
    if not isinstance(scenes, dict) or not scenes:
        return ['"scenes" must be a non-empty object'], W
    if "start" not in scenes:
        E.append('no "start" scene')
    if not story.get("title"):
        W.append('no "title"')

    def ref(sid, where):
        if not isinstance(sid, str) or sid not in scenes:
            E.append(f'{where}: scene "{sid}" does not exist')

    for sid, sc in scenes.items():
        if not isinstance(sc, dict):
            E.append(f'scene "{sid}" is not an object')
            continue
        steps = iter_steps(sc)
        if not steps:
            E.append(f'scene "{sid}": "steps" is empty or missing')
        for i, st in enumerate(steps):
            if not isinstance(st, dict):
                E.append(f'scene "{sid}" step {i}: not an object')
                continue
            lines = st.get("lines")
            if lines is not None and not isinstance(lines, (list, dict)):
                E.append(f'scene "{sid}" step {i}: "lines" must be an array or {{language: array}}')
        for i, ch in enumerate(sc.get("choices") or []):
            if not isinstance(ch, dict) or not ch.get("title"):
                E.append(f'scene "{sid}" choice {i}: needs a "title"')
                continue
            ref(ch.get("next_scene"), f'scene "{sid}" choice {i}')
        if "next_scene" in sc:
            ref(sc["next_scene"], f'scene "{sid}" next_scene')
        for target in (sc.get("next_scenes") or {}):
            ref(target, f'scene "{sid}" next_scenes')
        if sc.get("choices") and ("next_scene" in sc or "next_scenes" in sc):
            W.append(f'scene "{sid}": has choices, so next_scene / next_scenes are ignored')

    # unreachable scenes
    seen, todo = set(), ["start"] if "start" in scenes else []
    while todo:
        sid = todo.pop()
        if sid in seen or sid not in scenes:
            continue
        seen.add(sid)
        sc = scenes[sid]
        todo += [c.get("next_scene") for c in (sc.get("choices") or []) if isinstance(c, dict)]
        todo += [sc.get("next_scene")] + list((sc.get("next_scenes") or {}).keys())
    for sid in scenes:
        if sid not in seen:
            W.append(f'scene "{sid}" can never be reached from "start"')

    if base_dir is not None:
        for img in image_ids(story):
            if not find_image(base_dir, img):
                E.append(f'image "@b{img}": no file images/{img}.png (or .jpg/.webp/...) next to the story')
    return E, W


def build_envelope(story, base_dir):
    """The data tree that goes into the PDF. Same envelope shape as Gamiko's own files."""
    images = {}
    for img in image_ids(story):
        with open(find_image(base_dir, img), "rb") as f:
            images[img] = f.read()
    body = dict(story)
    body["images"] = images
    return {
        "dataType": "gmk",
        "ver": 1,
        "appType": "vn",
        "appInnerId": -2,
        "edition": "open",
        "story": body,
    }


def pick_text(v, lang="en"):
    if isinstance(v, dict):
        for k in (lang, "en", "cn", "zh"):
            if v.get(k):
                return str(v[k])
        return str(next(iter(v.values()), ""))
    return "" if v is None else str(v)


# ============================================================
# PDF writing
# ============================================================
PAGE_W, PAGE_H = 420, 595          # A5, in points
MARGIN = 40

# Helvetica advance widths (1/1000 em) for ASCII 32..126, from the standard AFM.
_HELV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
         556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
         1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
         667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
         333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
         556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]


def _latin(ch):
    """Characters drawn with Helvetica (WinAnsi). Everything else goes to the CJK font."""
    try:
        ch.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def _break_anywhere(ch):
    return ord(ch) >= 0x2E80          # CJK, kana, full-width punctuation ...


def _pdf_char_width(ch):
    if _latin(ch):
        o = ord(ch)
        return (_HELV[o - 32] if 32 <= o <= 126 else 556) / 1000.0
    return 1.0


NO_LINE_START = set("，。、；：！？）》」』”’…,.;:!?)]}")


def wrap(text, size, width, measure):
    """Greedy line breaking. Latin words stay whole; CJK may break between any two characters."""
    lines = []
    for para in text.split("\n"):
        tokens, word = [], ""
        for ch in para:
            if ch == " ":
                if word:
                    tokens.append(word)
                    word = ""
                tokens.append(" ")
            elif _break_anywhere(ch):
                if word:
                    tokens.append(word)
                    word = ""
                tokens.append(ch)
            else:
                word += ch
        if word:
            tokens.append(word)
        line = ""
        for tok in tokens:
            if line and tok in NO_LINE_START:      # keep closing punctuation on the previous line
                line += tok
            elif line and measure(line + tok, size) > width:
                lines.append(line.rstrip())
                line = "" if tok == " " else tok
            else:
                line += tok
        lines.append(line.rstrip())
    return lines


def layout_page(title, desc, footer, measure):
    """Returns [(text, size, gray, baseline_y_from_top)] for the visible page."""
    items = []
    y = MARGIN + 6
    width = PAGE_W - 2 * MARGIN
    for ln in wrap(title, 20, width, measure):
        y += 26
        items.append((ln, 20, 0.0, y))
    y += 18
    for ln in wrap(desc, 11, width, measure):
        y += 17
        if y > PAGE_H - MARGIN - 60:
            break
        items.append((ln, 11, 0.15, y))
    fy = PAGE_H - MARGIN - 12 * len(wrap(footer, 8, width, measure))
    for ln in wrap(footer, 8, width, measure):
        fy += 12
        items.append((ln, 8, 0.45, fy))
    return items


def _pdf_measure(s, size):
    return sum(_pdf_char_width(c) for c in s) * size


def _pdf_text_ops(items):
    """Content stream: Helvetica for WinAnsi runs, STSong-Light (UniGB-UCS2-H) for the rest."""
    ops = []
    for text, size, gray, ytop in items:
        ops.append(f"BT {gray:.2f} g 1 0 0 1 {MARGIN} {PAGE_H - ytop:.2f} Tm")
        run, run_latin = "", None
        for ch in text + "\0":
            lat = _latin(ch) if ch != "\0" else None
            if run and (ch == "\0" or lat != run_latin):
                if run_latin:
                    esc = run.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
                    ops.append(f"/F1 {size} Tf (" + esc.decode("latin-1") + ") Tj")
                else:
                    hexs = "".join(f"{ord(c):04X}" if ord(c) <= 0xFFFF else "003F" for c in run)
                    ops.append(f"/F2 {size} Tf <{hexs}> Tj")
                run = ""
            if ch != "\0":
                run += ch
                run_latin = lat
        ops.append("ET")
    return "\n".join(ops).encode("latin-1")


def _pdf_text_utf16(s):
    return "<FEFF" + s.encode("utf-16-be").hex().upper() + ">"


def _render_page_image(items, font_path, scale=3):
    """Draws the same layout as a picture (needs Pillow and a font that covers the text)."""
    from PIL import Image, ImageDraw, ImageFont
    fonts = {}

    def font(size):
        if size not in fonts:
            fonts[size] = ImageFont.truetype(font_path, int(size * scale))
        return fonts[size]

    im = Image.new("RGB", (PAGE_W * scale, PAGE_H * scale), "white")
    dr = ImageDraw.Draw(im)
    for text, size, gray, ytop in items:
        c = int(gray * 255)
        dr.text((MARGIN * scale, ytop * scale), text, font=font(size), fill=(c, c, c), anchor="ls")
    return im


class Pdf:
    def __init__(self):
        self.objs = []

    def reserve(self):
        self.objs.append(None)
        return len(self.objs)

    def put(self, num, body):
        self.objs[num - 1] = body if isinstance(body, bytes) else body.encode("latin-1")

    def add(self, body):
        n = self.reserve()
        self.put(n, body)
        return n

    def stream(self, num, head, data):
        self.put(num, f"<< {head} /Length {len(data)} >>\nstream\n".encode("latin-1") + data + b"\nendstream")

    def output(self, root, info):
        out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(self.objs, 1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(self.objs) + 1}\n0000000000 65535 f \n".encode()
        for off in offsets:
            out += f"{off:010d} 00000 n \n".encode()
        out += (f"trailer\n<< /Size {len(self.objs) + 1} /Root {root} 0 R /Info {info} 0 R >>\n"
                f"startxref\n{xref}\n%%EOF\n").encode()
        return bytes(out)


DEFAULT_DESC = (
    'This PDF contains a complete interactive visual novel, "{title}".\n'
    'The script and all images are attached to this file as "story.gvnb". '
    'You can preview it with the open tool gmkvn:  python3 gmkvn.py preview <this file>\n'
    '\n'
    '本 PDF 内含一部完整的互动视觉小说《{title}》。'
    '剧本与全部图片以附件 story.gvnb 的形式嵌在本文件里，可以用公开工具 gmkvn 预览。'
)
FOOTER = ("Packed with gmkvn (open edition). This open format is not compatible with the Gamiko app.\n"
          "由 gmkvn 公开版打包。公开版格式与 Gamiko App 不互通。")


def write_pdf(envelope, title, desc, font_path=None):
    payload = gvjb_dumps(envelope)
    pdf = Pdf()
    catalog, pages, page, content, names, filespec, embedded, info = (pdf.reserve() for _ in range(8))

    if font_path:
        from PIL import ImageFont
        cache = {}

        def measure(s, size):
            if size not in cache:
                cache[size] = ImageFont.truetype(font_path, size * 10)
            return cache[size].getlength(s) / 10.0

        items = layout_page(title, desc, FOOTER, measure)
        im = _render_page_image(items, font_path)
        img = pdf.reserve()
        pdf.stream(img, f"/Type /XObject /Subtype /Image /Width {im.width} /Height {im.height} "
                        "/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode",
                   zlib.compress(im.tobytes(), 9))
        resources = f"<< /XObject << /Im1 {img} 0 R >> >>"
        ops = f"q {PAGE_W} 0 0 {PAGE_H} 0 0 cm /Im1 Do Q".encode()
    else:
        f1 = pdf.add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        fd = pdf.add("<< /Type /FontDescriptor /FontName /STSong-Light /Flags 6 /FontBBox [-25 -254 1000 880] "
                     "/ItalicAngle 0 /Ascent 880 /Descent -120 /CapHeight 880 /StemV 93 >>")
        cid = pdf.add(f"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light "
                      f"/CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 2 >> "
                      f"/FontDescriptor {fd} 0 R /DW 1000 >>")
        f2 = pdf.add(f"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H "
                     f"/DescendantFonts [{cid} 0 R] >>")
        resources = f"<< /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> >>"
        ops = _pdf_text_ops(layout_page(title, desc, FOOTER, _pdf_measure))

    now = datetime.datetime.now(datetime.timezone.utc).strftime("D:%Y%m%d%H%M%SZ")
    pdf.put(catalog, f"<< /Type /Catalog /Pages {pages} 0 R /Names << /EmbeddedFiles {names} 0 R >> "
                     f"/AF [{filespec} 0 R] /PageMode /UseAttachments >>")
    pdf.put(pages, f"<< /Type /Pages /Kids [{page} 0 R] /Count 1 >>")
    pdf.put(page, f"<< /Type /Page /Parent {pages} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                  f"/Resources {resources} /Contents {content} 0 R >>")
    pdf.stream(content, "/Filter /FlateDecode", zlib.compress(ops, 9))
    pdf.put(names, f"<< /Names [({ATTACHMENT_NAME}) {filespec} 0 R] >>")
    pdf.put(filespec, f"<< /Type /Filespec /F ({ATTACHMENT_NAME}) /UF ({ATTACHMENT_NAME}) "
                      f"/EF << /F {embedded} 0 R >> /AFRelationship /Data "
                      f"/Desc (Gamiko visual novel data, open edition \\(GVJB binary JSON\\)) >>")
    md5 = hashlib.md5(payload).hexdigest()
    pdf.stream(embedded, f"/Type /EmbeddedFile /Subtype /application#2Fx-gvjb "
                         f"/Params << /Size {len(payload)} /CheckSum <{md5}> /ModDate ({now}) >>", payload)
    pdf.put(info, f"<< /Title {_pdf_text_utf16(title)} /Producer (gmkvn open edition) /CreationDate ({now}) >>")
    return pdf.output(catalog, info)


# ============================================================
# PDF reading (enough for files written by this tool)
# ============================================================
def _resolve_int(data, token):
    m = re.fullmatch(rb"\s*(\d+)\s+(\d+)\s+R\s*", token)
    if not m:
        return int(token)
    obj = re.search(rb"(?<!\d)" + m.group(1) + rb"\s+" + m.group(2) + rb"\s+obj\s*(\d+)\s*endobj", data)
    if not obj:
        raise ValueError("cannot resolve indirect /Length")
    return int(obj.group(1))


def read_pdf_payload(data):
    """Finds the embedded file whose content is GVJB data and returns it (raw bytes)."""
    for m in re.finditer(rb"\d+\s+\d+\s+obj\b", data):
        start = m.end()
        nxt = data.find(b"endobj", start)
        s = data.find(b"stream", start)
        if s < 0 or (0 <= nxt < s):
            continue
        head = data[start:s]
        if not re.search(rb"/Type\s*/EmbeddedFile\b", head):
            continue
        ln = re.search(rb"/Length\s+(\d+\s+\d+\s+R|\d+)", head)
        if not ln:
            continue
        length = _resolve_int(data, ln.group(1))
        p = s + len(b"stream")
        if data[p:p + 2] == b"\r\n":
            p += 2
        elif data[p:p + 1] in (b"\n", b"\r"):
            p += 1
        body = data[p:p + length]
        if re.search(rb"/Filter\s*/FlateDecode", head):
            body = zlib.decompress(body)
        if body[:4] == MAGIC:
            return body
    raise ValueError("no gmkvn data found in this PDF (was it made by gmkvn open edition?)")


def load_any(path):
    """Returns (story_with_images_as_bytes, envelope_meta). Accepts a gmkvn PDF or a story.json."""
    if path.lower().endswith(".json"):
        story = load_story(path)
        base = os.path.dirname(os.path.abspath(path))
        E, _ = check_story(story, base)
        if E:
            raise ValueError("story has errors:\n  " + "\n  ".join(E))
        env = build_envelope(story, base)
    else:
        with open(path, "rb") as f:
            env = gvjb_loads(read_pdf_payload(f.read()))
    if not isinstance(env, dict) or env.get("appType") != "vn" or not isinstance(env.get("story"), dict):
        raise ValueError("the attached data is not a visual novel")
    story = env["story"]
    meta = {k: v for k, v in env.items() if k != "story"}
    return story, meta


# ============================================================
# Preview (one self-contained HTML file)
# ============================================================
PLAYER_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Story Preview</title>
<style>
:root { --bg: #0b0d12; --fg: #f3f4f6; --panel: rgba(12,14,22,.84); --accent: #2563eb; }
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; background: var(--bg); color: var(--fg); overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Noto Sans CJK SC", sans-serif; }
#stage { position: fixed; inset: 0; user-select: none; }
#pic { position: absolute; inset: 0; background: center / cover no-repeat; transition: opacity .35s ease; }
#pic.fade { opacity: 0; }
#stage.shake #pic { animation: shake .12s linear infinite; }
@keyframes shake { 0% { transform: translate(0,0); } 25% { transform: translate(-4px,2px); } 50% { transform: translate(3px,-3px); } 75% { transform: translate(-2px,-2px); } 100% { transform: translate(0,0); } }
#panel { position: absolute; left: 0; right: 0; bottom: 0; margin: 0 auto; max-width: 920px; max-height: 60vh; overflow-y: auto;
  background: var(--panel); backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
  border-radius: 18px 18px 0 0; padding: 20px 24px calc(20px + env(safe-area-inset-bottom)); }
#text { font-size: 18px; line-height: 1.8; white-space: pre-wrap; min-height: 1.8em; }
#hint { margin-top: 8px; font-size: 13px; color: #9ca3af; text-align: right; }
#acts { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; }
#acts:empty { display: none; }
#acts button { width: 100%; text-align: left; padding: 12px 16px; border-radius: 12px; border: 1px solid rgba(255,255,255,.18);
  background: rgba(255,255,255,.08); color: var(--fg); font: inherit; font-size: 16px; cursor: pointer; }
#acts button:hover { background: rgba(255,255,255,.18); }
#acts button small { display: block; color: #9ca3af; font-size: 13px; margin-top: 4px; }
#acts button.main { text-align: center; background: var(--accent); border-color: var(--accent); font-weight: 600; }
#acts .end { text-align: center; letter-spacing: .25em; color: #d1d5db; }
#acts .end b { display: block; font-size: 22px; letter-spacing: normal; color: #fde68a; margin-bottom: 4px; }
#tools { position: absolute; top: calc(12px + env(safe-area-inset-top)); right: 12px; display: flex; gap: 8px; z-index: 2; }
#tools button { min-width: 40px; height: 40px; border-radius: 20px; border: none; background: rgba(0,0,0,.5); color: #fff;
  font-size: 15px; cursor: pointer; padding: 0 12px; }
#tools button:disabled { opacity: .35; cursor: default; }
#cover { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 18px; text-align: center; padding: 24px; z-index: 3; background: rgba(0,0,0,.35); }
#cover h1 { font-size: clamp(26px, 5vw, 44px); margin: 0; text-shadow: 0 2px 18px rgba(0,0,0,.7); }
#cover button { padding: 14px 44px; border-radius: 999px; border: none; background: var(--accent); color: #fff; font-size: 18px; font-weight: 600; cursor: pointer; }
#cover .sub { color: #d1d5db; font-size: 13px; max-width: 460px; line-height: 1.6; }
.hidden { display: none !important; }
</style>
</head>
<body>
<div id="stage">
  <div id="pic"></div>
  <div id="cover"><h1 id="cTitle"></h1><button id="btnStart"></button><div class="sub" id="cSub"></div></div>
  <div id="tools" class="hidden"><button id="btnBack">↶</button><button id="btnRestart">⟲</button></div>
  <div id="panel" class="hidden"><div id="text"></div><div id="acts"></div><div id="hint"></div></div>
</div>
<script id="story" type="application/json">__STORY__</script>
<script>
"use strict";
const story = JSON.parse(document.getElementById("story").textContent);
const $ = (id) => document.getElementById(id);
const UI = {
  zh: { start: "开始", next: "点击继续", end: "完", restart: "从头再来", back: "上一步", sub: "gmkvn 公开版预览" },
  en: { start: "Start", next: "Tap to continue", end: "THE END", restart: "Play again", back: "Back", sub: "gmkvn open edition preview" },
};
// Story texts may be a plain string or {language: text}. Engine language codes:
// en es pt ru ja, zh = Traditional Chinese, cn = Simplified Chinese.
const qs = new URL(location.href).searchParams.get("lang");
const nav = (navigator.language || "en").toLowerCase();
const LANG = qs || (nav.startsWith("zh") ? (/(hant|tw|hk|mo)/.test(nav) ? "zh" : "cn") : nav.slice(0, 2));
function pick(v) {
  if (v == null) return "";
  if (typeof v !== "object" || Array.isArray(v)) return v;
  for (const k of [LANG, "en", "cn", "zh"]) if (v[k] != null) return v[k];
  const ks = Object.keys(v); return ks.length ? v[ks[0]] : "";
}
// Buttons follow the story: a Chinese title gets Chinese buttons even in an English browser.
const L = UI[(qs ? (LANG === "cn" || LANG === "zh") : /[\u3400-\u9fff]/.test(pick(story.title)) || LANG === "cn" || LANG === "zh") ? "zh" : "en"];
const COLORS = { black: "#000", white: "#fff", red: "#d00", green: "#090", blue: "#14c", gray: "#808080", grey: "#808080", silver: "#c0c0c0", golden: "#d4a017" };
function bgCss(name) {
  if (!name) return null;
  if (name.startsWith("@b")) { const u = story.images[name.slice(2)]; return u ? { image: u } : { color: "#000" }; }
  if (COLORS[name]) return { color: COLORS[name] };
  const m = /^#([0-9a-f]{1,8})$/i.exec(name);
  if (m) {            // engine colors are 0xAABBGGRR
    const v = parseInt(m[1], 16) >>> 0, r = v & 255, g = (v >> 8) & 255, b = (v >> 16) & 255;
    return { color: `rgb(${r},${g},${b})` };
  }
  return { color: "#000" };
}
function steps(sc) { const s = sc.steps; return Array.isArray(s) ? s : (s && typeof s === "object" ? Object.values(s) : []); }
function lines(st) { const v = pick(st.lines); return Array.isArray(v) ? v : (v ? [String(v)] : []); }

let S = null, hist = [], shownBg = undefined;
function setBg(name) {
  if (name === shownBg) return;
  shownBg = name;
  const c = bgCss(name) || { color: "#000" };
  const pic = $("pic");
  pic.classList.add("fade");
  setTimeout(() => {
    pic.style.backgroundImage = c.image ? `url("${c.image}")` : "none";
    pic.style.backgroundColor = c.color || "#000";
    pic.classList.remove("fade");
  }, 180);
}
function nextOf(sc) {
  // next_scenes: compare the score pt with each threshold t.
  //   t > 0 hits when pt >= t (distance pt - t); t < 0 hits when pt <= t (distance t - pt); t = 0 never hits.
  //   The hit with the smallest distance wins; no hit -> next_scene.
  let best = null, bestD = Infinity;
  for (const [sid, t] of Object.entries(sc.next_scenes || {})) {
    let d = null;
    if (t > 0 && S.point >= t) d = S.point - t;
    if (t < 0 && S.point <= t) d = t - S.point;
    if (d != null && d < bestD) { best = sid; bestD = d; }
  }
  return best != null ? best : sc.next_scene;
}
function btn(html, cls, fn) { const b = document.createElement("button"); b.innerHTML = html; if (cls) b.className = cls; b.onclick = (e) => { e.stopPropagation(); fn(); }; return b; }
function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }
function enterScene(sid, point) { S = { sid, step: 0, line: 0, point }; enterStep(); }
function enterStep() {
  const sc = story.scenes[S.sid], st = steps(sc)[S.step] || {};
  let bg = st.background;
  if (bg == null && S.step === 0) bg = sc.background;
  if (bg != null) setBg(bg);
  if (st.effect === "tremor") $("stage").classList.add("shake");
  if (st.effect === "stopTremor") $("stage").classList.remove("shake");
  if (!lines(st).length) return advance(true);
  render();
}
function atSceneEnd() {
  const sc = story.scenes[S.sid], st = steps(sc)[S.step] || {};
  return S.step >= steps(sc).length - 1 && S.line >= lines(st).length - 1;
}
function render() {
  const sc = story.scenes[S.sid], st = steps(sc)[S.step] || {};
  $("text").textContent = lines(st)[S.line] || "";
  const acts = $("acts"); acts.innerHTML = ""; $("hint").textContent = "";
  $("btnBack").disabled = !hist.length;
  if (!atSceneEnd()) { $("hint").textContent = L.next + " ▸"; return; }
  if ((sc.choices || []).length) {
    sc.choices.forEach((c, i) => {
      const d = pick(c.description);
      acts.append(btn(`${i + 1}. ${esc(pick(c.title))}${d ? `<small>${esc(d)}</small>` : ""}`, "", () => {
        hist.push({ ...S, bg: shownBg });
        enterScene(c.next_scene, S.point + (c.point || 0));
      }));
    });
  } else if (nextOf(sc) == null) {
    const e = document.createElement("div"); e.className = "end";
    const n = pick(sc.ending_name);
    e.innerHTML = (n ? `<b>${esc(n)}</b>` : "") + "— " + L.end + " —";
    acts.append(e, btn(L.restart, "main", restart));
  } else {
    $("hint").textContent = L.next + " ▸";
  }
}
function advance(silent) {
  const sc = story.scenes[S.sid], all = steps(sc), st = all[S.step] || {};
  if (!silent) hist.push({ ...S, bg: shownBg });
  if (S.line < lines(st).length - 1) { S.line++; return render(); }
  if (S.step < all.length - 1) { S.step++; S.line = 0; return enterStep(); }
  if ((sc.choices || []).length) { if (!silent) hist.pop(); return render(); }
  const nx = nextOf(sc);
  if (nx == null) { if (!silent) hist.pop(); return render(); }
  enterScene(nx, S.point);
}
function back() {
  const h = hist.pop(); if (!h) return;
  S = { sid: h.sid, step: h.step, line: h.line, point: h.point };
  setBg(h.bg); render();
}
function restart() { hist = []; $("stage").classList.remove("shake"); enterScene("start", 0); }

document.title = pick(story.title) || "Story";
$("cTitle").textContent = document.title;
$("btnStart").textContent = L.start;
$("cSub").textContent = L.sub;
$("btnBack").title = L.back; $("btnRestart").title = L.restart;
const first = steps(story.scenes.start || {})[0] || {};
setBg(first.background != null ? first.background : (story.scenes.start || {}).background);
$("btnStart").onclick = (e) => {
  e.stopPropagation();
  $("cover").classList.add("hidden"); $("tools").classList.remove("hidden"); $("panel").classList.remove("hidden");
  restart();
};
$("btnBack").onclick = (e) => { e.stopPropagation(); back(); };
$("btnRestart").onclick = (e) => { e.stopPropagation(); restart(); };
$("stage").addEventListener("click", () => {
  if (!S) return;
  const sc = story.scenes[S.sid];
  if (atSceneEnd() && ((sc.choices || []).length || nextOf(sc) == null)) return;   // waiting for a choice / the end
  advance();
});
document.addEventListener("keydown", (e) => {
  if (!S) { if (e.key === "Enter" || e.key === " ") $("btnStart").click(); return; }
  const sc = story.scenes[S.sid];
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("stage").click(); }
  else if (/^[1-9]$/.test(e.key) && atSceneEnd() && (sc.choices || [])[+e.key - 1]) $("acts").children[+e.key - 1].click();
  else if (e.key === "Backspace" || e.key === "ArrowLeft") back();
});
</script>
</body>
</html>
"""


def make_preview_html(story):
    out = dict(story)
    imgs = {}
    for k, v in (story.get("images") or {}).items():
        if isinstance(v, (bytes, bytearray)):
            mime, _ = image_mime(v)
            imgs[k] = f"data:{mime};base64," + base64.b64encode(v).decode("ascii")
    out["images"] = imgs
    js = json.dumps(out, ensure_ascii=False).replace("</", "<\\/")
    return PLAYER_HTML.replace("__STORY__", js)


# ============================================================
# Commands
# ============================================================
def _report(E, W):
    for e in E:
        print(f"  error: {e}")
    for w in W:
        print(f"  warning: {w}")


def cmd_check(a):
    story = load_story(a.story)
    E, W = check_story(story, os.path.dirname(os.path.abspath(a.story)))
    _report(E, W)
    print(f"{len(E)} error(s), {len(W)} warning(s)")
    return 1 if E else 0


def cmd_pack(a):
    story = load_story(a.story)
    base = os.path.dirname(os.path.abspath(a.story))
    E, W = check_story(story, base)
    _report(E, W)
    if E:
        print("not packed: fix the errors first")
        return 1
    title = pick_text(story.get("title")) or "Untitled"
    if a.desc_file:
        with open(a.desc_file, "r", encoding="utf-8") as f:
            desc = f.read().strip()
    else:
        desc = a.desc if a.desc is not None else DEFAULT_DESC.format(title=title)
    env = build_envelope(story, base)
    pdf = write_pdf(env, title, desc, a.font)
    out = a.output or os.path.splitext(a.story)[0] + ".pdf"
    with open(out, "wb") as f:
        f.write(pdf)
    n = len(env["story"]["images"])
    print(f"wrote {out}  ({len(pdf):,} bytes, {len(env['story']['scenes'])} scenes, {n} images)")
    if len(pdf) > APP_SIZE_HINT:
        print("  note: over 16MB. (The Gamiko app itself rejects external files above 16MB.)")
    return 0


def cmd_unpack(a):
    story, meta = load_any(a.pdf)
    os.makedirs(os.path.join(a.out_dir, "images"), exist_ok=True)
    for img, data in (story.get("images") or {}).items():
        _, ext = image_mime(data)
        with open(os.path.join(a.out_dir, "images", f"{img}.{ext}"), "wb") as f:
            f.write(data)
    plain = {k: v for k, v in story.items() if k != "images"}
    with open(os.path.join(a.out_dir, "story.json"), "w", encoding="utf-8") as f:
        json.dump(plain, f, ensure_ascii=False, indent=2)
    print(f"envelope: {json.dumps(meta, ensure_ascii=False)}")
    print(f"wrote {a.out_dir}/story.json and {len(story.get('images') or {})} image(s) in {a.out_dir}/images/")
    return 0


def cmd_preview(a):
    story, _ = load_any(a.input)
    out = a.output or os.path.splitext(a.input)[0] + ".preview.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(make_preview_html(story))
    print(f"wrote {out}")
    if not a.no_open:
        webbrowser.open("file://" + os.path.abspath(out))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="gmkvn", description="Gamiko visual novel packer, open edition.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("pack", help="story.json + images -> PDF")
    s.add_argument("story")
    s.add_argument("-o", "--output")
    s.add_argument("--desc", help="text shown on the PDF page")
    s.add_argument("--desc-file", help="read the page text from a UTF-8 file")
    s.add_argument("--font", help="draw the page as a picture with this TTF/OTF font (needs Pillow)")
    s.set_defaults(func=cmd_pack)

    s = sub.add_parser("unpack", help="PDF -> story.json + images/")
    s.add_argument("pdf")
    s.add_argument("out_dir")
    s.set_defaults(func=cmd_unpack)

    s = sub.add_parser("preview", help="PDF or story.json -> one playable HTML file")
    s.add_argument("input")
    s.add_argument("-o", "--output")
    s.add_argument("--no-open", action="store_true", help="do not open a browser")
    s.set_defaults(func=cmd_preview)

    s = sub.add_parser("check", help="validate a story.json")
    s.add_argument("story")
    s.set_defaults(func=cmd_check)

    a = p.parse_args(argv)
    try:
        return a.func(a)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
