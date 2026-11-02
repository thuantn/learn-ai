"""Builds the content folder the server reads: lesson pages, audio, summaries, cards and quiz answers.

  python scripts/package_content.py CONFIG.json OUT_DIR

Lesson sources stay outside this repo. CONFIG.json lists them:
{"source": "path", "replace": [["old", "new"]], "lessons": [{
  "id": "bai02", "order": 2, "title": "...", "folder": "Bai02", "page": "bai02.html", "doc": "lesson2", "audio_dir": "podcast",
  "tracks": {"short": {"file": "a.mp3", "label": "Bản ngắn"}, "long": {"file": "b.mp3", "label": "Bản dài"}}}]}
Each lesson folder has app/summary.md (one "- " line per point) and app/cards.json, or app/cards.draft.json with --allow-draft.
"""
import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys

CDN_SCRIPT = re.compile(r'<script src="https://cdnjs\.cloudflare\.com/[^"]*/([^"/]+)"([^>]*)></script>')
FONT_LINK = re.compile(r'<link [^>]*fonts\.(?:googleapis|gstatic)\.com[^>]*>\n?')
INLINE_SCRIPT = re.compile(r"<script>(.*?)</script>", re.S)
HANDLER = re.compile(r'<[a-z][^>]*\son[a-z]+\s*=', re.I)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return round(float(out.stdout.strip()))


def read_quiz(html, lesson_id):
    """Runs only the QS array from our own lesson page, in a throwaway Node process."""
    found = re.search(r"const QS=\[.*?\n\];", html, re.S)
    if not found:
        raise SystemExit(f"{lesson_id}: no QS array in the page")
    js = found.group(0).replace("const QS=", "process.stdout.write(JSON.stringify(", 1).rstrip(";") + "));"
    out = subprocess.run(["node", "-e", js], capture_output=True, encoding="utf-8", check=True)
    quiz = []
    for i, q in enumerate(json.loads(out.stdout)):
        quiz.append({"id": f"{lesson_id}-q{i}", "q": q["q"], "options": q["o"], "answer": q["a"], "why": q.get("w", "")})
    return quiz


def build_page(html, lesson_id, target_dir, replace, head_tag=None, footer_tag=None):
    html, fonts = FONT_LINK.subn("", html)
    html, libs = CDN_SCRIPT.subn(lambda m: f'<script src="/static/vendor/{m[1]}"{m[2]}></script>', html)
    if not libs:
        raise SystemExit(f"{lesson_id}: expected library scripts")
    for old, new in replace:
        html = html.replace(old, new)
    if HANDLER.search(html):
        raise SystemExit(f"{lesson_id}: the page has inline event handlers, which the CSP blocks")
    count = 0
    names = []

    def extract(m):
        nonlocal count
        count += 1
        name = f"page.{count}.js"
        (target_dir / name).write_text(m[1], encoding="utf-8")
        names.append(name)
        return f'<script src="{name}"></script>'

    html = INLINE_SCRIPT.sub(extract, html)
    if head_tag is None:
        head_tag = f'<script src="/static/lesson-shim.js" data-lesson="{lesson_id}"></script>\n'
    if footer_tag is None:
        footer_tag = '<footer><a href="/">Về app</a>. '
    if "<head>" not in html or "<footer>" not in html:
        raise SystemExit(f"{lesson_id}: page layout changed")
    html = html.replace("<head>", "<head>\n" + head_tag, 1)
    html = html.replace("<footer>", footer_tag, 1)
    return html, names


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("config")
    ap.add_argument("out")
    ap.add_argument("--allow-draft", action="store_true")
    args = ap.parse_args()
    cfg = json.loads(pathlib.Path(args.config).read_text(encoding="utf-8"))
    src = pathlib.Path(cfg["source"])
    out = pathlib.Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    manifest = {"lessons": [], "files": []}
    for item in cfg["lessons"]:
        lid = item["id"]
        folder = src / item["folder"]
        target = out / lid
        (target / "audio").mkdir(parents=True)
        html = (folder / item["page"]).read_text(encoding="utf-8")
        quiz = read_quiz(html, lid)
        page, scripts = build_page(html, lid, target, cfg.get("replace", []))
        (target / "lesson.html").write_text(page, encoding="utf-8")
        manifest["files"].append(f"{lid}/lesson.html")
        manifest["files"] += [f"{lid}/{s}" for s in scripts]
        audio_dir = folder / item["audio_dir"]
        for name in re.findall(r'src="audio/([^"]+)"', page):
            shutil.copy2(audio_dir / name, target / "audio" / name)
            manifest["files"].append(f"{lid}/audio/{name}")
        tracks = {}
        for key, t in item["tracks"].items():
            if f"{lid}/audio/{t['file']}" not in manifest["files"]:
                raise SystemExit(f"{lid}: track {t['file']} is not used by the page")
            tracks[key] = {"file": f"{lid}/audio/{t['file']}", "duration": duration(target / "audio" / t["file"]), "label": t["label"]}
        cards_file = folder / "app" / "cards.json"
        draft = False
        if not cards_file.exists():
            cards_file = folder / "app" / "cards.draft.json"
            draft = True
            if not args.allow_draft or not cards_file.exists():
                raise SystemExit(f"{lid}: no approved app/cards.json")
        cards = json.loads(cards_file.read_text(encoding="utf-8"))
        ids = [c["id"] for c in cards]
        if len(set(ids)) != len(ids) or not all(c["q"] and c["a"] and c["id"].startswith(lid + "-") for c in cards):
            raise SystemExit(f"{lid}: bad cards file")
        summary = [ln[2:].strip() for ln in (folder / "app" / "summary.md").read_text(encoding="utf-8").splitlines() if ln.startswith("- ")]
        if not summary:
            raise SystemExit(f"{lid}: empty summary")
        manifest["lessons"].append({"id": lid, "order": item["order"], "title": item["title"], "page": f"{lid}/lesson.html", "doc": item["doc"],
                                    "summary": summary, "cards": cards, "quiz": quiz, "tracks": tracks})
        print(f"{lid}: {len(cards)} thẻ{' (nháp)' if draft else ''}, {len(quiz)} câu quiz, {len(summary)} ý tóm tắt, {len(scripts)} khối script")
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"{len(manifest['files'])} file, {size / 1048576:.1f} MB")


if __name__ == "__main__":
    sys.exit(main())
