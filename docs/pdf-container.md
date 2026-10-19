# Packing a story into a PDF

[中文版](pdf-container.zh.md)

Gamiko shares a whole visual novel, with its script and every picture, as **one ordinary PDF file**. This document explains how that works and specifies the open format written by [`tools/gmkvn.py`](../tools/gmkvn.py).

> **Open edition.** Gamiko's own files follow exactly the pipeline described here. In addition, the app protects the binary data with a private protocol before it goes into the PDF. Files made with `gmkvn` are therefore **not readable by the Gamiko app**, and Gamiko's files are not readable by `gmkvn`. This repository shows the technique, not the app's private protocol.

## Why a PDF

- It survives everything. Chat apps, email, cloud drives and phone file managers pass PDFs through unchanged. Unknown file types are often blocked, renamed or recompressed.
- Every device can open it. Anyone who opens the file in a normal reader sees a readable page with the title and how to play it, instead of an error.
- The data rides along inside. PDF has a standard way to carry attached files, so the story needs no second file.

## The pipeline

```
story.json + images/*.png
   │ 1. collect     every "@b<id>" background -> read images/<id>.png
   │ 2. extend      story.images = { "<id>": <raw bytes> }      JSON + a byte-string type
   │ 3. envelope    { dataType, ver, appType, appInnerId, story }
   │ 4. serialize   binary JSON
   ▼ 5. embed       attach to a one-page PDF
story.pdf
```

**1. Collect.** Scan the backgrounds of all scenes and steps. Every value of the form `"@b<id>"` names a picture, stored next to the story as `images/<id>.png`.

**2. Extend JSON with byte strings.** Plain JSON has no binary type, and base64 would make every picture a third bigger. So the JSON tree gets one extra value type, the **byte string**, and each picture is stored as-is in `story.images`. The PNG bytes are not decoded, re-encoded or base64-encoded. Unpacking gives back the identical file.

**3. Envelope.** The story is wrapped so a reader can tell what kind of content it holds:

```json
{
  "dataType": "gmk",
  "ver": 1,
  "appType": "vn",
  "appInnerId": -2,
  "edition": "open",
  "story": { "title": "...", "serial": "...", "scenes": { }, "images": { "1": "<bytes>" } }
}
```

`edition: "open"` is written only by `gmkvn`.

**4. Serialize to binary JSON.** The tree, byte strings included, is written as a compact binary stream. The format used by `gmkvn` is specified below.

**5. Embed in a PDF.** The binary stream becomes an **embedded file**, a standard PDF attachment, of a normal one-page document.

### What the Gamiko app does differently

Steps 1 to 3 are the same. In step 4 the app uses its own binary JSON layout, and between steps 4 and 5 the data goes through a private protection layer. The visible page of an official file is also drawn as a picture with the app's font, while `gmkvn` embeds real text by default. Neither of these changes the idea.

## GVJB: the binary JSON used by gmkvn

All multi-byte integers are **varints**: 7 bits per byte, least significant group first, high bit set on every byte except the last (LEB128).

```
file  := "GVJB"  version:u8 (= 1)  value
value := tag:u8  payload
```

| Tag | Type | Payload |
|---|---|---|
| `0x00` | null | — |
| `0x01` | false | — |
| `0x02` | true | — |
| `0x03` | integer | zigzag varint: `n >= 0 -> 2n`, `n < 0 -> -2n-1` |
| `0x04` | float | 8 bytes, IEEE 754 double, big-endian |
| `0x05` | string | varint byte length, then UTF-8 |
| `0x06` | **bytes** | varint length, then the raw bytes. This is the extension that carries the pictures |
| `0x07` | array | varint count, then that many values |
| `0x08` | object | varint count, then for each member: key (varint length + UTF-8) and value |

Example: `{"a": 1}` is

```
47 56 4A 42   01   08 01   01 61   03 02
"GVJB"        ver  obj n=1 key "a" int 1 (zigzag 2)
```

The whole file must be exactly one value with no trailing bytes. Object keys keep their order.

This is close to well-known formats such as CBOR or BSON. The point is only that "JSON + a byte-string type" is enough to carry a whole story in one tree.

## PDF layout written by gmkvn

| Object | Content |
|---|---|
| Catalog | `/Names << /EmbeddedFiles … >>`, `/AF [filespec]`, `/PageMode /UseAttachments`, which opens the attachments panel in most readers |
| Page | One A5 page with the title, a description and a footer |
| Filespec | `/F (story.gvnb)`, `/AFRelationship /Data` |
| EmbeddedFile | `/Subtype /application#2Fx-gvjb`, `/Params << /Size … /CheckSum <md5> /ModDate … >>`. The stream is the GVJB data, **uncompressed** (the pictures are already compressed) |
| Fonts | Helvetica (WinAnsi) for Latin text, and **STSong-Light** with `UniGB-UCS2-H` for CJK and other text. Both are standard fonts that are not embedded, so the file stays small. Acrobat may ask to download its Asian font pack |

With `--font some.ttf` (needs Pillow), the page is drawn as a picture with that font instead. This is how the official files do it. Use it when the readers' PDF software lacks CJK support.

**Reading** a file back needs no PDF library. Find the embedded-file stream whose content starts with `GVJB`, read `/Length` bytes, and decode. Any PDF reader can also save the attachment by hand; `gmkvn unpack` does that and splits the pictures out again.

## Using the tool

Only Python 3.8+ is needed. Pillow is optional and used only by `--font`.

```sh
# check a story (missing scenes, missing pictures, unreachable scenes ...)
python3 tools/gmkvn.py check examples/lighthouse/story_en.json

# story.json + images/ -> PDF
python3 tools/gmkvn.py pack examples/lighthouse/story_en.json -o lighthouse.pdf
python3 tools/gmkvn.py pack story.json --desc "Your own page text"
python3 tools/gmkvn.py pack story.json --font /path/to/NotoSansSC-Regular.ttf

# PDF -> story.json + images/ (the pictures come back byte-identical)
python3 tools/gmkvn.py unpack lighthouse.pdf lighthouse_out

# PDF (or story.json) -> one self-contained HTML file, opened in the browser
python3 tools/gmkvn.py preview lighthouse.pdf
python3 tools/gmkvn.py preview examples/lighthouse/story_zh.json --no-open
```

The preview plays the story with the rules in [story-format.md](story-format.md): lines one screen at a time, choices, score and `next_scenes`, endings, colors, and the shake effect. It also has a back button. Add `?lang=en` (or `cn`, `zh`, `ja` …) to the HTML address to pick a language in multi-language stories.
