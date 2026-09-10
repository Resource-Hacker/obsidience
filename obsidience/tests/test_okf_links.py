from obsidience.harness.knowledge.links import article_ref, body_links, canonical_body
import pytest


def test_native_link_forms_and_code_are_distinct():
    body = '''[One](../One.md#Part) and [Two](/Knowledge/Two.md).
[Three][three]

[three]: ../Three.md "Optional title"

![Not an Article](/Knowledge/Image.md) and [Web](https://example.org/Web.md).
`[Example](/Knowledge/Code.md)`

```markdown
[[Knowledge/Not-an-edge]]
```
'''
    assert body_links(body, "Knowledge/Child/Child.md") == [
        "Knowledge/One", "Knowledge/Two", "Knowledge/Three",
    ]


def test_move_normalizes_titled_relative_and_reference_links():
    body = '[One](../One.md "Title") and [Ref][ref].\n\n[ref]: ../One.md "Reference"\n'
    normalized = canonical_body(body, "Knowledge/Child/Child.md", {"Knowledge/One": "Knowledge/New"})
    assert normalized == '[One](/Knowledge/New.md "Title") and [Ref][ref].\n\n[ref]: /Knowledge/New.md "Reference"\n'
    assert body_links(normalized, "_staging/proposal.md") == ["Knowledge/New"]
    assert canonical_body(normalized, "Knowledge/Child/Child.md") == normalized


def test_wikilink_migration_preserves_labels_spaces_and_code():
    body = 'See [[Knowledge/Old#Heading|Title]]. `[[Knowledge/Old]]`'
    normalized = canonical_body(body, "Knowledge/Page.md", {"Knowledge/Old": "New Folder/New Article"})
    assert normalized == 'See [Title](/New%20Folder/New%20Article.md#Heading). `[[Knowledge/Old]]`'
    assert body_links(normalized) == ["New Folder/New Article"]


def test_paths_cannot_escape_bundle_or_become_remote_edges():
    for href in ("../../escape.md", "https://example.com/a.md", "//example.com/a.md", "http://[bad", "source://abc"):
        assert article_ref(href, "Knowledge/Page.md") is None


@pytest.mark.parametrize("body", [
    "Source: [[BBC News]](source://ac960858-ce78-4df4-b77f-4492a0facfe4); "
    "reporting page: [[BBC News]](source://498eaea2-8ddc-4661-813c-05beca547e93)",
    "[Reporting from [[BBC News]]](https://example.test/story)",
    "[[BBC News]][report]\n\n[report]: source://ac960858-ce78-4df4-b77f-4492a0facfe4\n",
    "![Logo [[BBC News]]](https://example.test/logo.png)",
])
def test_existing_markdown_labels_do_not_become_phantom_article_edges(body):
    normalized = canonical_body(body, "News & Research/item.md")
    assert normalized == body
    assert body_links(normalized, "News & Research/item.md") == []
    assert canonical_body(normalized, "News & Research/item.md") == normalized


def test_link_label_preservation_keeps_real_wiki_edges_destination_moves_and_code():
    body = (
        "[[BBC News]](source://ac960858-ce78-4df4-b77f-4492a0facfe4) "
        "[[Display label]](../Old.md) [[Knowledge/Old|Related knowledge]]\n"
        "`[[Knowledge/Example]]`\n\n```markdown\n[[Knowledge/Not-an-edge]]\n```\n"
    )
    normalized = canonical_body(body, "Knowledge/Child/Page.md", {"Knowledge/Old": "Knowledge/New"})
    assert "[[BBC News]](source://ac960858-ce78-4df4-b77f-4492a0facfe4)" in normalized
    assert "[[Display label]](/Knowledge/New.md)" in normalized
    assert "[Related knowledge](/Knowledge/New.md)" in normalized
    assert "`[[Knowledge/Example]]`" in normalized
    assert "```markdown\n[[Knowledge/Not-an-edge]]\n```" in normalized
    assert body_links(normalized) == ["Knowledge/New"]
