"""Portable Article links, parsed by CommonMark rather than inferred from prose."""

from __future__ import annotations

import posixpath
import re
from urllib.parse import quote, unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.rules_inline import image, link
from markdown_it.rules_inline.state_inline import StateInline

_MARKDOWN = MarkdownIt("commonmark").enable("table")
_WIKI = re.compile(r"\[\[([^\]\|#]+)(#[^\]\|]*)?(?:\|([^\]]*))?\]\]")
_CODE = re.compile(r"(?<!`)(`+)(?!`)[\s\S]*?(?<!`)\1(?!`)")
_DESTINATION = re.compile(
    r"(?P<open>\]\(<?|^[ \t]*\[[^\]\n]+\]:[ \t]*<?)"
    r"(?P<href>[^\s<>]+?)"
    r'''(?P<close>>?(?:[ \t]+(?:"[^"\n]*"|'[^'\n]*'|\([^\)\n]*\)))?(?:\)|[ \t]*$))''',
    re.M,
)


def article_ref(href: str, path: str = "") -> str | None:
    """Resolve a document URL relative to its Article, never outside the bundle."""
    try:
        url = urlsplit(href)
    except ValueError:
        return None
    if url.scheme or url.netloc or not url.path.lower().endswith(".md"):
        return None
    target = unquote(url.path)
    target = (target.lstrip("/") if target.startswith("/") else
              posixpath.join(posixpath.dirname(path), target))
    target = posixpath.normpath(target)
    if target == ".." or target.startswith("../"):
        return None
    return target[:-3]


def metadata_ref(value: str) -> str:
    """Project a typed metadata link to its exact, bundle-root Article identity.

    This only normalizes spelling; it does not resolve a basename, authorize a
    checkout, or rewrite the authored binding. Synthetic @ references survive.
    """
    ref = value.strip()
    if ref.startswith("[[") and ref.endswith("]]"):
        ref = ref[2:-2]
    ref = unquote(ref.split("|", 1)[0].split("#", 1)[0].strip()).lstrip("/")
    return ref[:-3] if ref.lower().endswith(".md") else ref


def body_links(body: str, path: str = "") -> list[str]:
    """Return actual internal links; code examples, images and web URLs aren't edges."""
    return list(dict.fromkeys(ref for ref, _line, _excerpt in body_link_locations(body, path)))


def body_link_locations(body: str, path: str = "") -> list[tuple[str, int, str]]:
    """Use the full document parse so reference-style links retain their evidence."""
    links = []
    lines = body.splitlines()
    for block in _MARKDOWN.parse(body):
        line = (block.map or [0])[0] + 1
        link_depth = 0
        for token in block.children or []:
            refs = []
            if token.type == "link_open":
                link_depth += 1
                ref = article_ref(token.attrGet("href") or "", path)
                if ref:
                    refs.append(ref)
            elif token.type == "link_close":
                link_depth -= 1
            elif token.type == "text" and not link_depth:
                refs.extend(match.group(1).strip() for match in _WIKI.finditer(token.content)
                            if not match.group(1).strip().startswith("source://"))
            elif token.type in {"softbreak", "hardbreak"}:
                line += 1
            links.extend((ref, line, lines[line - 1].strip()[:400]) for ref in refs)
    return links


def canonical_body(body: str, path: str, mapping: dict[str, str] | None = None) -> str:
    """Normalize authored wikilinks and moved paths to bundle-root Markdown links.

    Explicit typed metadata edges remain separate from body relationships.
    Code blocks and inline code are examples, not navigable links.
    """
    mapping = {old.casefold(): new for old, new in (mapping or {}).items()}

    def wiki(match):
        ref = match.group(1).strip().removesuffix(".md")
        if ref.startswith("@"):
            return match.group(0)  # UI-only generated navigation, never a concept file.
        if ref.startswith("source://"):
            # An evidence citation is an external resource, not an Article
            # path. Preserve its URI instead of inventing /source:/...md.
            label = (match.group(3) or ref).replace("[", "\\[").replace("]", "\\]")
            return f"[{label}]({ref}{match.group(2) or ''})"
        ref = mapping.get(ref.casefold(), ref)
        label = (match.group(3) or match.group(1).rsplit("/", 1)[-1]).replace("[", "\\[").replace("]", "\\]")
        fragment = match.group(2)
        href = "/" + quote(ref, safe="/") + ".md" + ("#" + quote(unquote(fragment[1:]), safe="/") if fragment else "")
        return f"[{label}]({href})"

    def destination(match):
        href = match.group("href")
        ref = article_ref(href, path)
        if ref is None:
            return match.group(0)
        ref = mapping.get(ref.casefold(), ref)
        fragment = urlsplit(href).fragment
        url = "/" + quote(ref, safe="/") + ".md" + ("#" + fragment if fragment else "")
        return match.group("open") + url + match.group("close")

    def wikilinks(text):
        # A CommonMark label can contain brackets: [[BBC]](source://id)
        # is already a Source link, not a wiki edge plus a trailing URL.
        state = StateInline(text, _MARKDOWN, environment, [])
        pieces = []
        cursor = 0
        while state.pos < state.posMax:
            start = state.pos
            if link(state, True) or image(state, True):
                pieces.append(_WIKI.sub(wiki, text[cursor:start]))
                pieces.append(text[start:state.pos])
                cursor = state.pos
            else:
                _MARKDOWN.inline.skipToken(state)
        pieces.append(_WIKI.sub(wiki, text[cursor:]))
        return "".join(pieces)

    # CommonMark owns block boundaries, including indented and nested fences.
    protected = set()
    environment = {}
    for block in _MARKDOWN.parse(body, environment):
        if block.type in {"fence", "code_block", "html_block"} and block.map:
            protected.update(range(*block.map))
    lines = body.splitlines(keepends=True)
    groups = []
    start = 0
    while start < len(lines):
        is_code = start in protected
        end = start + 1
        while end < len(lines) and (end in protected) == is_code:
            end += 1
        text = "".join(lines[start:end])
        if not is_code:
            pieces = []
            cursor = 0
            for match in _CODE.finditer(text):
                pieces.append(wikilinks(_DESTINATION.sub(destination, text[cursor:match.start()])))
                pieces.append(match.group(0))
                cursor = match.end()
            pieces.append(wikilinks(_DESTINATION.sub(destination, text[cursor:])))
            text = "".join(pieces)
        groups.append(text)
        start = end
    return "".join(groups)
