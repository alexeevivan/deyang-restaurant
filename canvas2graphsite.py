#!/usr/bin/env python3
"""
canvas2graphsite.py

Graph-based MkDocs generator for Obsidian Canvas.

This version does NOT classify cards by keywords.
It follows the actual Canvas links starting from the main root card.

Best for a structured Canvas like:

Restaurant Operating System
  -> Strategy
  -> Finance
  -> Procurement
      -> Bar
          -> Ice
          -> Hoshizaki

Output:
- MkDocs Material project
- One page per first-level section
- Nested headings based on Canvas graph depth
- Almost no "Unsorted" if your cards are connected to the root
- Open Questions page
- Build Report

Install:
  python3 -m venv .venv
  source .venv/bin/activate
  pip install mkdocs-material

Usage:
  python canvas2graphsite.py Main.canvas --out "/Users/alexeevivan/Documents/China/Restaurant"

Preview:
  cd "/Users/alexeevivan/Documents/China/Restaurant"
  source .venv/bin/activate
  mkdocs serve
"""

import argparse
import json
import re
import shutil
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path


def clean_text(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def get_title(text: str, fallback: str) -> str:
    text = clean_text(text)
    if not text:
        return fallback
    line = text.split("\n", 1)[0].strip()
    line = re.sub(r"^#+\s*", "", line)
    line = re.sub(r"^\-\s*", "", line)
    return line[:120] or fallback


def get_body_without_title(text: str, title: str) -> str:
    text = clean_text(text)
    if not text:
        return ""
    lines = text.split("\n")
    if lines and normalize(lines[0]) == normalize(title):
        return "\n".join(lines[1:]).strip()
    return text


def normalize(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"^#+\s*", "", value)
    value = re.sub(r"^\-\s*", "", value)
    value = re.sub(r"\s+", " ", value)
    return value


def slug(value: str, fallback: str = "page") -> str:
    value = normalize(value)
    value = re.sub(r"[^a-z0-9а-яё]+", "-", value, flags=re.IGNORECASE)
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:80] or fallback


def backup_existing(out_dir: Path, no_backup: bool) -> None:
    if not out_dir.exists():
        return
    if no_backup:
        shutil.rmtree(out_dir)
    else:
        backup = out_dir.with_name(out_dir.name + " BACKUP " + datetime.now().strftime("%Y%m%d-%H%M%S"))
        shutil.move(str(out_dir), str(backup))


def md_escape(text: str) -> str:
    return text.replace("|", "\\|")


def find_root(id_to_title: dict, parents: dict, id_to_xy: dict) -> str:
    # Prefer explicit Restaurant Operating System
    for node_id, title in id_to_title.items():
        if "restaurant operating system" in normalize(title):
            return node_id

    # Then prefer the root-like card with no parents and many outgoing links.
    candidates = [node_id for node_id in id_to_title if not parents.get(node_id)]
    if candidates:
        candidates.sort(key=lambda i: (-len(children_global.get(i, [])), id_to_xy[i][1], id_to_xy[i][0]))
        return candidates[0]

    return next(iter(id_to_title))


def collect_reachable(root_id: str, children: dict) -> set:
    reachable = set()
    q = deque([root_id])
    while q:
        node_id = q.popleft()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        for child_id, _ in children.get(node_id, []):
            if child_id not in reachable:
                q.append(child_id)
    return reachable


def render_tree(
    node_id: str,
    children: dict,
    id_to_title: dict,
    id_to_text: dict,
    depth: int,
    max_depth: int,
    visited: set,
) -> list[str]:
    lines = []

    if depth > max_depth:
        return lines

    for child_id, label in children.get(node_id, []):
        if child_id in visited:
            lines.append(f"- {id_to_title[child_id]} *(repeated link)*")
            continue

        visited.add(child_id)
        title = id_to_title[child_id]
        body = get_body_without_title(id_to_text.get(child_id, ""), title)

        heading_level = min(depth + 2, 6)
        lines.append(f"{'#' * heading_level} {title}\n")

        if label:
            lines.append(f"*Connection: {md_escape(label)}*\n")

        if body:
            lines.append(body + "\n")

        subchildren = children.get(child_id, [])
        if subchildren and depth + 1 >= max_depth:
            lines.append("**Sub-items:**")
            for grand_id, grand_label in subchildren:
                suffix = f" — {md_escape(grand_label)}" if grand_label else ""
                lines.append(f"- {id_to_title[grand_id]}{suffix}")
            lines.append("")
        else:
            lines.extend(
                render_tree(
                    child_id,
                    children,
                    id_to_title,
                    id_to_text,
                    depth + 1,
                    max_depth,
                    visited,
                )
            )

    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("canvas", help="Path to Obsidian .canvas")
    parser.add_argument("--out", default="deyang-graph-site", help="Output MkDocs project folder")
    parser.add_argument("--site-name", default="Deyang Restaurant Project", help="Website title")
    parser.add_argument("--max-depth", type=int, default=6, help="Max graph depth rendered per section")
    parser.add_argument("--no-backup", action="store_true", help="Delete previous output without backup")
    args = parser.parse_args()

    canvas_path = Path(args.canvas).expanduser()
    out_dir = Path(args.out).expanduser()
    docs_dir = out_dir / "docs"

    if not canvas_path.exists():
        raise FileNotFoundError(f"Canvas not found: {canvas_path}")

    backup_existing(out_dir, args.no_backup)
    docs_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(canvas_path.read_text(encoding="utf-8"))
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    id_to_title = {}
    id_to_text = {}
    id_to_xy = {}

    for node in nodes:
        if node.get("type") != "text":
            continue
        node_id = node["id"]
        text = clean_text(node.get("text", ""))
        id_to_text[node_id] = text
        id_to_title[node_id] = get_title(text, f"Card {node_id[:6]}")
        id_to_xy[node_id] = (node.get("x", 0), node.get("y", 0))

    children = defaultdict(list)
    parents = defaultdict(list)

    for edge in edges:
        src = edge.get("fromNode")
        dst = edge.get("toNode")
        label = clean_text(edge.get("label", ""))
        if src in id_to_title and dst in id_to_title:
            children[src].append((dst, label))
            parents[dst].append((src, label))

    # Sort children visually: top-to-bottom, left-to-right
    for node_id in list(children.keys()):
        children[node_id].sort(
            key=lambda item: (
                id_to_xy[item[0]][1],
                id_to_xy[item[0]][0],
                id_to_title[item[0]].lower(),
            )
        )

    # Hack for find_root function
    global children_global
    children_global = children

    root_id = find_root(id_to_title, parents, id_to_xy)
    reachable = collect_reachable(root_id, children)

    top_sections = [child_id for child_id, _ in children.get(root_id, [])]
    if not top_sections:
        top_sections = sorted(
            [node_id for node_id in id_to_title if node_id != root_id],
            key=lambda i: (id_to_xy[i][1], id_to_xy[i][0]),
        )[:12]

    # Unique page slugs
    used_slugs = set()
    section_to_file = {}

    for section_id in top_sections:
        base = slug(id_to_title[section_id], f"section-{section_id[:6]}")
        page_slug = base
        n = 2
        while page_slug in used_slugs:
            page_slug = f"{base}-{n}"
            n += 1
        used_slugs.add(page_slug)
        section_to_file[section_id] = f"{page_slug}.md"

    # Home
    root_title = id_to_title[root_id]
    root_body = get_body_without_title(id_to_text.get(root_id, ""), root_title)

    home = [f"# {root_title}\n"]
    if root_body:
        home.append(root_body + "\n")

    home.append("## Project Sections\n")
    for section_id in top_sections:
        home.append(f"- [{id_to_title[section_id]}]({section_to_file[section_id]})")
    home.append("\n## Project Control\n")
    home.append("- [Open Questions](open-questions.md)")
    home.append("- [Unconnected Cards](unconnected-cards.md)")
    home.append("- [Build Report](build-report.md)\n")
    home.append("## Note\n")
    home.append("This site is generated from the project Canvas and reflects the current planning structure.")
    (docs_dir / "index.md").write_text("\n".join(home).strip() + "\n", encoding="utf-8")

    # Section pages
    for section_id in top_sections:
        section_title = id_to_title[section_id]
        section_body = get_body_without_title(id_to_text.get(section_id, ""), section_title)

        page = [f"# {section_title}\n"]
        if section_body:
            page.append(section_body + "\n")

        page.append("## Structure\n")
        rendered = render_tree(
            section_id,
            children,
            id_to_title,
            id_to_text,
            depth=1,
            max_depth=args.max_depth,
            visited={root_id, section_id},
        )

        if rendered:
            page.extend(rendered)
        else:
            page.append("_No child cards connected to this section._\n")

        # Incoming cross-links from outside this tree
        incoming = []
        for node_id, outgoing in children.items():
            for child_id, label in outgoing:
                if child_id == section_id and node_id != root_id:
                    incoming.append((node_id, label))

        if incoming:
            page.append("\n## Incoming Links\n")
            for source_id, label in incoming:
                suffix = f" — {md_escape(label)}" if label else ""
                page.append(f"- {id_to_title[source_id]}{suffix}")

        (docs_dir / section_to_file[section_id]).write_text("\n".join(page).strip() + "\n", encoding="utf-8")

    # Open questions page
    question_nodes = []
    for node_id, text in id_to_text.items():
        hay = f"{id_to_title[node_id]}\n{text}".lower()
        if "?" in text or "question" in hay or "decision" in hay or "risk" in hay:
            question_nodes.append(node_id)

    question_nodes.sort(key=lambda i: (id_to_xy[i][1], id_to_xy[i][0]))

    qpage = ["# Open Questions & Decisions\n"]
    if question_nodes:
        for node_id in question_nodes:
            qpage.append(f"## {id_to_title[node_id]}\n")
            qpage.append((id_to_text[node_id] or "_No details._") + "\n")
    else:
        qpage.append("_No open questions detected._\n")
    (docs_dir / "open-questions.md").write_text("\n".join(qpage).strip() + "\n", encoding="utf-8")

    # Unconnected cards
    unconnected = [node_id for node_id in id_to_title if node_id not in reachable]
    unconnected.sort(key=lambda i: (id_to_xy[i][1], id_to_xy[i][0]))

    upage = ["# Unconnected Cards\n"]
    upage.append("These cards are not reachable from the main root card. Connect them to the main structure if they should appear in the project sections.\n")
    if unconnected:
        for node_id in unconnected:
            upage.append(f"## {id_to_title[node_id]}\n")
            text = id_to_text.get(node_id, "")
            if text:
                upage.append(text + "\n")
    else:
        upage.append("_All text cards are connected to the main root._\n")
    (docs_dir / "unconnected-cards.md").write_text("\n".join(upage).strip() + "\n", encoding="utf-8")

    # Build report
    report = f"""# Build Report

Generated: {datetime.now().isoformat(timespec="seconds")}

Source canvas: `{canvas_path}`

Root card: `{root_title}`

## Counts

- Text cards: {len(id_to_title)}
- Canvas links: {len(edges)}
- Reachable cards: {len(reachable)}
- Unconnected cards: {len(unconnected)}
- Top-level sections: {len(top_sections)}
- Open question / decision cards: {len(question_nodes)}

## How this generator works

This version follows the Canvas graph structure.

It starts from the main root card, then creates one page for each first-level child section.
Cards below each section are rendered as nested headings based on their actual links.

No keyword classification is used for the main structure.
"""
    (docs_dir / "build-report.md").write_text(report.strip() + "\n", encoding="utf-8")

    # mkdocs.yml
    nav = []
    nav.append(f"site_name: {args.site_name}")
    nav.append("theme:")
    nav.append("  name: material")
    nav.append("  language: en")
    nav.append("  features:")
    nav.append("    - navigation.sections")
    nav.append("    - navigation.expand")
    nav.append("    - navigation.top")
    nav.append("    - search.highlight")
    nav.append("    - search.suggest")
    nav.append("plugins:")
    nav.append("  - search")
    nav.append("markdown_extensions:")
    nav.append("  - admonition")
    nav.append("  - toc:")
    nav.append("      permalink: true")
    nav.append("  - tables")
    nav.append("nav:")
    nav.append("  - Home: index.md")
    for section_id in top_sections:
        nav.append(f"  - {id_to_title[section_id]}: {section_to_file[section_id]}")
    nav.append("  - Open Questions: open-questions.md")
    nav.append("  - Unconnected Cards: unconnected-cards.md")
    nav.append("  - Build Report: build-report.md")

    (out_dir / "mkdocs.yml").write_text("\n".join(nav).strip() + "\n", encoding="utf-8")

    readme = f"""# {args.site_name}

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install mkdocs-material
```

## Preview

```bash
mkdocs serve
```

## Build

```bash
mkdocs build
```

## Rebuild from Canvas

```bash
python canvas2graphsite.py Main.canvas --out .
```
"""
    (out_dir / "README.md").write_text(readme.strip() + "\n", encoding="utf-8")

    print(f"Done: {out_dir.resolve()}")
    print(f"Text cards: {len(id_to_title)}")
    print(f"Reachable: {len(reachable)}")
    print(f"Unconnected: {len(unconnected)}")
    print(f"Top sections: {len(top_sections)}")
    print("Next:")
    print(f"  cd \"{out_dir}\"")
    print("  source .venv/bin/activate")
    print("  mkdocs serve")


if __name__ == "__main__":
    main()
