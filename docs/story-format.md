# Scene JSON format (current version)

[中文版](story-format.zh.md)

This is the format the Gamiko app reads today for **imported** visual novels, such as the ones made with the online editor and shared as PDF files. A richer version with characters, audio and multi-language packages is being designed. It will be documented separately when it ships, and stories in this format will keep working.

A complete, playable example is in [`examples/lighthouse/`](../examples/lighthouse/).

## The model in one paragraph

A story is a graph of **scenes**. A scene is a list of **steps**. A step sets the background picture and shows one or more **lines** of text, one line per screen. After the last line of a scene the reader either picks a **choice**, moves on to the next scene, or has reached an **ending**.

```
start ──▶ 2 ──┬─(choice)─▶ 3 ─▶ 4 ──┐
              └─(choice)─▶ 5 ─▶ 6 ──┴─▶ 7 ─▶ 8 ──┬─(choice)─▶ 9   (ending)
                                                 └─(choice)─▶ 10  (ending)
```

## Top level

| Field | Type | Required | Meaning |
|---|---|---|---|
| `title` | string or `{lang: string}` | yes | Story title |
| `serial` | string | yes | A unique id. A UUID is a good choice. The app uses it to recognize a story it has already imported: a file with a known serial opens the existing copy and is not imported again. **Give a new version a new serial.** |
| `scenes` | `{sceneId: scene}` | yes | Must contain a scene called `"start"` |
| `images` | `{imageId: bytes}` | — | Added by the packer. Never written by hand. See [pdf-container.md](pdf-container.md) |

Scene ids are free-form strings. Only `"start"` is special.

## scene

| Field | Type | Meaning |
|---|---|---|
| `steps` | array of steps | **Required.** An object is also accepted; then its keys are only for humans and the steps run in key order |
| `background` | string | Used when the first step has no `background` of its own |
| `choices` | array of choices | Shown after the last line of the last step. **If present, `next_scene` and `next_scenes` are ignored** |
| `next_scene` | string | Where to go when there are no choices. **No `next_scene` (and no `next_scenes` match) = this scene is an ending** |
| `next_scenes` | `{sceneId: threshold}` | Branch on the score, see below |
| `effect` | string | Transition into the scene: `"fade"` (cross-fade) or `"space"` (a fly-through effect) |
| `ending_name` | `{lang: string}` | The name of this ending, shown when the reader reaches it |

## step

| Field | Type | Meaning |
|---|---|---|
| `lines` | `[string]` or `{lang: [string]}` | One element = one screen. `\n` is allowed inside a line. Use `\n\n` for a gap between paragraphs |
| `background` | string | Change the background, see "Backgrounds". It stays until a later step changes it |
| `effect` | string | `"tremor"` starts a screen shake at the beginning of this step, and `"stopTremor"` stops it |

The current external format has **no characters or portraits**. If someone speaks, write the name into the line itself, such as `"Nell: Look!"`.

## choice

| Field | Type | Meaning |
|---|---|---|
| `title` | string or `{lang: string}` | Button text |
| `next_scene` | string | Where this choice leads |
| `point` | int | Optional. Added to the story's score when chosen |
| `description` | `{lang: string}` | Optional. When a scene has several choices, the app shows the description on the first tap and confirms on the second |

## Score and `next_scenes`

Every playthrough has a score that starts at 0 when the reader enters `start`. Each chosen choice adds its `point`. The score is not stored in the file.

When a scene without choices ends, `next_scenes` is checked against the current score `pt`. For each entry with threshold `t`:

- `t > 0` matches when `pt >= t`, at distance `pt - t`
- `t < 0` matches when `pt <= t`, at distance `t - pt`
- `t = 0` never matches

Among all matches, the one with the **smallest distance** wins. If nothing matches, `next_scene` is used. If that is also missing, the scene is an ending.

```json
"judgement": {
  "steps": [{ "lines": ["The council goes quiet."] }],
  "next_scenes": { "hero": 5, "villain": -5 },
  "next_scene": "neutral"
}
```

## Backgrounds

A background value is one of:

| Value | Meaning |
|---|---|
| `"@b<id>"` | A picture. The packer reads the file `images/<id>.png` next to the story and stores it under `images["<id>"]` |
| `"black"`, `"white"`, `"red"`, `"green"`, `"blue"`, `"gray"`, `"grey"`, `"silver"`, `"golden"` | A solid color |
| `"#…"` | A hex color in the engine's internal byte order, **AABBGGRR**. Named colors are easier and safer |

Pictures for the Gamiko app are PNG. The app accepts packed files up to **16 MB**. The official editor keeps the long side at most 1440 px and the aspect ratio between 9:16 and 16:9, and compresses the pictures automatically so the whole file fits. The open tool in this repository also accepts JPEG, WebP and GIF, because its files are only meant for previews.

## Languages

A story can be written in any language: plain strings are shown as they are.

One file can also carry several languages at once. Then a text field is an object keyed by language, and the app shows the one that matches the device. These keys are the engine's own codes:

| Code | Language |
|---|---|
| `en` `es` `pt` `ru` `ja` | English, Spanish, Portuguese, Russian, Japanese |
| `cn` | Simplified Chinese |
| `zh` | **Traditional** Chinese |

`ending_name` and `description` are always read as `{lang: string}`. In a single-language story, put the same text under every code, as the example does.

## Minimal example

```json
{
  "title": "The Door",
  "serial": "0b5f3e8a-2f1c-4c0e-9d3a-7a1e2b3c4d5e",
  "scenes": {
    "start": {
      "steps": [
        { "background": "@b1", "lines": ["A red door stands at the end of the hall.", "It is not locked."] }
      ],
      "choices": [
        { "title": "Open it", "next_scene": "inside", "point": 1 },
        { "title": "Walk away", "next_scene": "away" }
      ]
    },
    "inside": {
      "effect": "fade",
      "steps": [{ "background": "black", "effect": "tremor", "lines": ["The floor shakes."] },
                { "effect": "stopTremor", "lines": ["Then, silence."] }],
      "ending_name": { "en": "Inside", "es": "Inside", "pt": "Inside", "ru": "Inside", "ja": "Inside", "zh": "Inside", "cn": "Inside" }
    },
    "away": {
      "steps": [{ "lines": ["You never find out."] }],
      "ending_name": { "en": "Away", "es": "Away", "pt": "Away", "ru": "Away", "ja": "Away", "zh": "Away", "cn": "Away" }
    }
  }
}
```

Check a story with `python3 tools/gmkvn.py check story.json`. It reports missing scenes, missing pictures, choices without a title and scenes that can never be reached.
