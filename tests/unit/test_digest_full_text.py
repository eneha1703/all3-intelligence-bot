from all3_radar.digest.full_text import extract_article_text, fetch_article_text


def test_extract_article_text_prefers_json_ld_article_body() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {"@type":"NewsArticle","articleBody":"Australia mid-rise approvals rose sharply while structural timber consumption fell. LVL imports rose and prefabricated dwelling imports grew, showing timber is losing share to rival delivery systems."}
        </script>
      </head>
      <body><p>Subscribe to our newsletter.</p></body>
    </html>
    """

    result = extract_article_text(html, max_chars=500)

    assert result.status == "json_ld"
    assert result.text is not None
    assert "structural timber consumption fell" in result.text
    assert "Subscribe" not in result.text


def test_extract_article_text_uses_article_blocks_and_filters_page_noise() -> None:
    html = """
    <html>
      <body>
        <nav>Subscribe now for updates</nav>
        <article>
          <p>Figure AI said three humanoids sorted packages autonomously for 24 hours with zero failures.</p>
          <p>The test is useful because it shows continuous operation, but it does not yet prove reliability across changing warehouse environments.</p>
        </article>
        <footer>Privacy policy and all rights reserved.</footer>
      </body>
    </html>
    """

    result = extract_article_text(html, max_chars=500)

    assert result.status == "html_blocks"
    assert result.text is not None
    assert "24 hours with zero failures" in result.text
    assert "Privacy policy" not in result.text


def test_extract_article_text_ignores_person_bio_json_ld_and_prefers_article_node() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@graph": [
            {
              "@type": "Person",
              "description": "Greg Bock is an award-winning investigative journalist with more than 25 years of experience in print, digital, and broadcast news. His coverage has reached audiences across the United States through major media groups."
            },
            {
              "@type": "NewsArticle",
              "articleBody": "Australia's mid-rise approvals jumped while structural timber consumption fell, showing timber is losing practical share where housing growth is strongest."
            }
          ]
        }
        </script>
      </head>
      <body></body>
    </html>
    """

    result = extract_article_text(html, max_chars=500)

    assert result.status == "json_ld"
    assert result.text is not None
    assert "timber is losing practical share" in result.text
    assert "award-winning investigative journalist" not in result.text


def test_extract_article_text_rejects_bio_only_json_ld_and_falls_back_to_html() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@graph": [
            {
              "@type": "Person",
              "description": "Jason Ross is an in-house emcee and available for corporate host and MC work after more than 15 years in building and construction."
            }
          ]
        }
        </script>
      </head>
      <body>
        <article>
          <p>Timber is losing share in the mid-rise segment even as demand shifts toward denser housing formats.</p>
          <p>That matters because developers are choosing delivery systems, not just materials.</p>
        </article>
      </body>
    </html>
    """

    result = extract_article_text(html, max_chars=500)

    assert result.status == "html_blocks"
    assert result.text is not None
    assert "developers are choosing delivery systems" in result.text
    assert "available for corporate host" not in result.text


def test_fetch_article_text_returns_fetch_failure_status() -> None:
    def failing_fetcher(url: str, timeout_seconds: int) -> str:
        raise TimeoutError("slow")

    result = fetch_article_text("https://example.com/story", fetch_text_fn=failing_fetcher)

    assert result.text is None
    assert result.status == "fetch_failed:TimeoutError"
