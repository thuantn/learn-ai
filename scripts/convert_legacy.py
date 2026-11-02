"""Converts a legacy lesson source into a contract v1 package.

  python scripts/convert_legacy.py CONFIG.json OUT_DIR [--allow-draft]

CONFIG shares the format with scripts/package_content.py, plus an optional
"package" object for slug, title, topic and description.
"""
import argparse
import json
import pathlib
import re
import shutil
import sys
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.package_content import read_quiz, INLINE_SCRIPT
from app.contract import check_package, errors

LEGACY_PATCHES = [
    ("ask", "async function ask(q){", 'async function ask(q){LearnBridge.askApp(q||"");return;'),
    ("openPanel", "function openPanel(prefill){", 'function openPanel(prefill){LearnBridge.askApp(prefill||"");return;'),
    ("explain", "pendingExplain={sec,prompt:EXPLAIN[sec]};", 'LearnBridge.askApp("Tự giải thích lại phần "+secName(sec)+". "+EXPLAIN[sec]+"\\n\\nPhần của tôi: ");return;'),
]

HEAD_TAG = '<script src="/static/lesson-bridge.js"></script>\n<link rel="stylesheet" href="/static/lesson-fonts.css">\n'
FOOTER_TAG = "<footer>"

AUDIO_REF = re.compile(r'''(["'])(?:\.\./)?audio/([^"']+)''')


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0
        self.heading = 0
        self.last = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script", "style", "nav", "head", "title"):
            self.skip += 1
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading = int(tag[1])
        elif tag in ("p", "div", "section", "article", "li", "br"):
            self._break()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style", "nav", "head", "title"):
            self.skip -= 1
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading = 0
        elif tag in ("p", "div", "section", "article", "li"):
            self._break()

    def handle_data(self, data):
        if self.skip:
            return
        text = data.strip()
        if not text:
            return
        if self.heading:
            self.parts.append("#" * self.heading + " " + text + "\n\n")
            self.last = "break"
        else:
            self.parts.append(text + " ")
            self.last = "text"

    def _break(self):
        if self.last == "text":
            self.parts.append("\n\n")
            self.last = "break"

    def get_text(self):
        return "".join(self.parts).strip()


def apply_legacy_patches(html):
    for name, find, repl in LEGACY_PATCHES:
        count = html.count(find)
        if count != 1:
            raise SystemExit(f"{name}: expected exactly one occurrence of legacy pattern, found {count}")
        html = html.replace(find, repl, 1)
    return html


def page_to_text(html):
    extractor = TextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def read_summary(folder):
    text = (folder / "app" / "summary.md").read_text(encoding="utf-8")
    return [ln[2:].strip() for ln in text.splitlines() if ln.startswith("- ")]


def read_cards(folder, allow_draft):
    cards_file = folder / "app" / "cards.json"
    if not cards_file.exists():
        cards_file = folder / "app" / "cards.draft.json"
        if not allow_draft or not cards_file.exists():
            raise SystemExit(f"{folder.name}: no approved app/cards.json")
    return json.loads(cards_file.read_text(encoding="utf-8"))


def adjust_audio(page_html, scripts, page_dir, src_audio_dir, dst_audio_dir):
    dst_audio_dir.mkdir(parents=True, exist_ok=True)
    files = {"index.html": page_html}
    for name in scripts:
        files[name] = (page_dir / name).read_text(encoding="utf-8")
    for name, text in files.items():
        files[name] = AUDIO_REF.sub(r"\1../audio/\2", text)
    (page_dir / "index.html").write_text(files["index.html"], encoding="utf-8")
    for name in scripts:
        (page_dir / name).write_text(files[name], encoding="utf-8")
    names = set()
    for text in files.values():
        names.update(re.findall(r'''\.\./audio/([^"'\s]+)''', text))
    copied = set()
    for name in names:
        shutil.copy2(src_audio_dir / name, dst_audio_dir / name)
        copied.add(name)
    return files["index.html"], copied


def convert(config_path, out_path, allow_draft=False):
    cfg = json.loads(pathlib.Path(config_path).read_text(encoding="utf-8"))
    src = pathlib.Path(cfg["source"])
    out = pathlib.Path(out_path)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    package_cfg = cfg.get("package", {})
    lessons_cfg = cfg["lessons"]
    slug = package_cfg.get("slug") or lessons_cfg[0]["id"]
    package = {
        "contract_version": "v1",
        "slug": slug,
        "title": package_cfg.get("title") or "Package",
        "topic": package_cfg.get("topic") or "general",
        "description": package_cfg.get("description") or "",
        "lessons": [item["id"] for item in lessons_cfg],
    }

    for item in lessons_cfg:
        lid = item["id"]
        folder = src / item["folder"]
        lesson_dir = out / "lessons" / lid
        page_dir = lesson_dir / "page"
        page_dir.mkdir(parents=True)

        html = (folder / item["page"]).read_text(encoding="utf-8")
        for old, new in cfg.get("replace", []):
            html = html.replace(old, new)
        html = apply_legacy_patches(html)
        content = page_to_text(html)

        quiz = read_quiz(html, lid)
        summary = read_summary(folder)
        cards = read_cards(folder, allow_draft)

        page_html, scripts = build_page_with_bridge(html, lid, page_dir)
        page_html, copied = adjust_audio(page_html, scripts, page_dir, folder / item["audio_dir"], lesson_dir / "audio")
        (page_dir / "index.html").write_text(page_html, encoding="utf-8")

        tracks = {}
        for key, t in item.get("tracks", {}).items():
            if t["file"] not in copied:
                shutil.copy2(folder / item["audio_dir"] / t["file"], lesson_dir / "audio" / t["file"])
                copied.add(t["file"])
            tracks[key] = {"file": t["file"], "label": t["label"]}

        lesson = {
            "title": item["title"],
            "summary": summary,
            "cards": cards,
            "quiz": quiz,
            "tracks": tracks,
        }
        (lesson_dir / "lesson.json").write_text(json.dumps(lesson, ensure_ascii=False, indent=2), encoding="utf-8")
        (lesson_dir / "content.md").write_text(content, encoding="utf-8")

    (out / "package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def build_page_with_bridge(html, lesson_id, page_dir):
    from scripts.package_content import build_page
    return build_page(html, lesson_id, page_dir, [], head_tag=HEAD_TAG, footer_tag=FOOTER_TAG)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("config")
    ap.add_argument("out")
    ap.add_argument("--allow-draft", action="store_true")
    args = ap.parse_args(argv)
    out = convert(args.config, args.out, args.allow_draft)
    problems = errors(check_package(out))
    if problems:
        for p in problems:
            print(f"{p.path}: [{p.code}] {p.message}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
