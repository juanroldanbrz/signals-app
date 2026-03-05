import pytest
from src.crawling.agent import _html_to_markdown


def test_strips_script_tags():
    html = "<html><body><script>alert('xss')</script><p>Safe content</p></body></html>"
    result = _html_to_markdown(html)
    assert "alert" not in result
    assert "Safe content" in result


def test_strips_style_tags():
    html = "<html><head><style>body { color: red; }</style></head><body><p>Text</p></body></html>"
    result = _html_to_markdown(html)
    assert "color: red" not in result
    assert "Text" in result


def test_strips_nav_footer_header():
    html = "<html><body><nav>Nav Menu</nav><header>Site Header</header><p>Article</p><footer>Footer</footer></body></html>"
    result = _html_to_markdown(html)
    assert "Nav Menu" not in result
    assert "Site Header" not in result
    assert "Footer" not in result
    assert "Article" in result


def test_preserves_links():
    html = '<html><body><a href="https://example.com">Read more</a></body></html>'
    result = _html_to_markdown(html)
    assert "https://example.com" in result
    assert "Read more" in result


def test_preserves_headings():
    html = "<html><body><h1>Main Title</h1><h2>Subtitle</h2><p>Paragraph</p></body></html>"
    result = _html_to_markdown(html)
    assert "Main Title" in result
    assert "Subtitle" in result


def test_truncates_to_max_length():
    html = "<html><body><p>" + "x" * 50000 + "</p></body></html>"
    result = _html_to_markdown(html)
    assert len(result) <= 32000


def test_empty_html_returns_string():
    result = _html_to_markdown("")
    assert isinstance(result, str)
