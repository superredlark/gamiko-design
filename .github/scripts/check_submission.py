#!/usr/bin/env python3
"""
Checks a pull request that submits works under works/<login>/.

Runs from the TRUSTED base branch. The pull request's files are only ever read as
data (git objects -> a temp folder -> json.loads / byte checks). Nothing from the
pull request is executed, imported or checked out as code.

    python3 check_submission.py --login LOGIN --base BASE_SHA --head HEAD_SHA --report report.md

Exit codes:
    0  every change is a valid submission under works/<login>/  -> merge
    1  something is wrong; report.md explains it                 -> comment
    2  not a works submission at all (nothing under works/)       -> leave it for a human
"""

import argparse
import json
import os
import posixpath
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
import gmkvn  # noqa: E402  (trusted: comes from the base branch)

TEXT_EXTS = {".json", ".md", ".txt"}
IMAGE_EXTS = {".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".webp": "webp"}
MAX_IMAGE = 5 * 1024 * 1024
MAX_TEXT = 512 * 1024
MAX_WORK = 20 * 1024 * 1024
MAX_FILES = 300


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def changed_paths(base, head):
    """Paths added / modified / deleted by the PR, relative to the merge base."""
    mb = git("merge-base", base, head).decode().strip()
    out = git("diff", "--name-status", "--no-renames", "-z", mb, head).decode("utf-8", "replace")
    parts = [p for p in out.split("\0") if p]
    return [(parts[i], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]


def tree_entries(head, prefix):
    """{path: (mode, type, sha, size)} for every entry under prefix in the PR head."""
    out = git("ls-tree", "-r", "-l", "-z", head, "--", prefix).decode("utf-8", "replace")
    entries = {}
    for rec in out.split("\0"):
        if not rec:
            continue
        meta, path = rec.split("\t", 1)
        mode, typ, sha, size = meta.split()
        entries[path] = (mode, typ, sha, 0 if size == "-" else int(size))
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--report", required=True)
    a = ap.parse_args()

    errors = []
    changes = changed_paths(a.base, a.head)
    if not any(p.startswith("works/") for _, p in changes):
        return finish(a.report, 2, ["This pull request does not touch `works/`, so it is left for a maintainer to review."])

    own = f"works/{a.login}/"
    own_lower = own.lower()
    touched_works = set()
    for status, path in changes:
        if not path.lower().startswith(own_lower):
            errors.append(f"`{path}`: you can only change files inside `{own}` (your GitHub user name).")
            continue
        rest = path[len(own):].split("/")
        if len(rest) >= 2:
            touched_works.add(path[:len(own)] + rest[0])
    if len(changes) > MAX_FILES:
        errors.append(f"Too many files in one pull request ({len(changes)}, at most {MAX_FILES}).")
    if errors:
        return finish(a.report, 1, errors)

    # the actual folder name may differ in case from the login; use what is in the tree
    entries = tree_entries(a.head, "works/")
    entries = {p: e for p, e in entries.items() if p.lower().startswith(own_lower)}

    with tempfile.TemporaryDirectory() as tmp:
        for path, (mode, typ, sha, size) in entries.items():
            rel = path[len(own):]
            parts = rel.split("/")
            if typ != "blob" or mode not in ("100644", "100755"):
                errors.append(f"`{path}`: only regular files are allowed (no links or submodules).")
                continue
            if any(p in ("", ".", "..") or p.startswith(".") for p in parts):
                errors.append(f"`{path}`: hidden files and odd path names are not allowed.")
                continue
            ext = posixpath.splitext(path)[1].lower()
            if ext not in TEXT_EXTS and ext not in IMAGE_EXTS:
                errors.append(f"`{path}`: file type `{ext or '(none)'}` is not allowed. Use .json .md .txt .png .jpg .webp.")
                continue
            if len(parts) == 1 and ext != ".md":
                errors.append(f"`{path}`: put each work in its own folder, `{own}<work-name>/`.")
                continue
            if len(parts) > 3 or (len(parts) == 3 and parts[1] != "images"):
                errors.append(f"`{path}`: inside a work folder, use only the top level and `images/`.")
                continue
            limit = MAX_IMAGE if ext in IMAGE_EXTS else MAX_TEXT
            if size > limit:
                errors.append(f"`{path}`: {size / 1048576:.1f} MB, the limit for this type is {limit / 1048576:.1f} MB.")
                continue
            data = git("cat-file", "blob", sha)
            if ext in IMAGE_EXTS and gmkvn.image_mime(data)[1] != IMAGE_EXTS[ext]:
                errors.append(f"`{path}`: the content is not a real {ext[1:].upper()} image.")
                continue
            if ext in TEXT_EXTS:
                try:
                    data.decode("utf-8")
                except UnicodeDecodeError:
                    errors.append(f"`{path}`: text files must be UTF-8.")
                    continue
            dst = os.path.join(tmp, *parts)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)

        for work in sorted(touched_works):
            name = work[len(own):]
            folder = os.path.join(tmp, name)
            if not any(p.lower().startswith(work.lower() + "/") for p in entries):
                continue                                   # the whole work was deleted: fine
            total = sum(e[3] for p, e in entries.items() if p.lower().startswith(work.lower() + "/"))
            if total > MAX_WORK:
                errors.append(f"`{work}/`: {total / 1048576:.1f} MB in total, at most {MAX_WORK // 1048576} MB per work.")
            files = os.listdir(folder) if os.path.isdir(folder) else []
            readme = os.path.join(folder, "README.md")
            if not os.path.isfile(readme) or not open(readme, encoding="utf-8").read().strip():
                errors.append(f"`{work}/README.md` is missing or empty. Say what the work is and what others may do with it.")
            stories = sorted(f for f in files if f.endswith(".json"))
            if not stories:
                errors.append(f"`{work}/`: no story file (`*.json`) found.")
            for s in stories:
                try:
                    with open(os.path.join(folder, s), encoding="utf-8") as f:
                        story = json.load(f)
                except ValueError as e:
                    errors.append(f"`{work}/{s}`: not valid JSON ({e}).")
                    continue
                E, _ = gmkvn.check_story(story, folder)
                errors += [f"`{work}/{s}`: {e}" for e in E]

    if errors:
        return finish(a.report, 1, errors)
    return finish(a.report, 0, [f"Checked {len(touched_works)} work(s) under `{own}`. Thank you!"])


def finish(report, code, lines):
    head = {0: "✅ Submission accepted", 1: "❌ The submission needs a fix", 2: "ℹ️ Not a works submission"}[code]
    body = [f"### {head}", ""] + [f"- {x}" for x in lines]
    if code == 1:
        repo = os.environ.get("GITHUB_REPOSITORY", "superredlark/gamiko-design")
        body += ["", "Push a fix to the same branch and the check runs again. "
                     f"Guide: [works/README.md](https://github.com/{repo}/blob/main/works/README.md)"]
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(body) + "\n")
    print("\n".join(body))
    return code


if __name__ == "__main__":
    sys.exit(main())
