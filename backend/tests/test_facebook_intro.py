"""The Intro block on a public Facebook profile.

The structures here are trimmed copies of what facebook.com actually served to
an anonymous request, so the parser is tested against the shape it really
meets rather than one invented to suit it.
"""

from __future__ import annotations

import json

from app.sources.facebook import FacebookAdapter
from app.sources.facebook_intro import classify, parse_intro, unwrap_link


def row(text: str, *, ranges: list[dict] | None = None, plaintext: str | None = None):
    """One timeline_context_item, shaped as Facebook publishes it."""
    item: dict = {
        "subtitle": None,
        "title": {"ranges": ranges or [], "color_ranges": [], "text": text},
    }
    if plaintext is not None:
        item["plaintext_title"] = {"ranges": [], "text": plaintext}
    return {
        "renderer": {"__typename": "ContextItemDefaultRenderer", "context_item": item}
    }


def page(*rows: dict) -> str:
    """A page whose embedded JSON carries these rows, plus noise around them."""
    blobs = ",".join(
        f'"timeline_context_item":{json.dumps(r["renderer"] and r)[1:-1]}'
        if False
        else json.dumps({"timeline_context_item": r})
        for r in rows
    )
    return (
        '<html><head><meta property="og:title" content="Someone"/></head>'
        f'<body><script type="application/json" data-sjs>[{blobs}]</script></body>'
        "</html>"
    )


def entity(url: str, typename: str = "User") -> dict:
    return {"entity": {"__typename": typename, "url": url}, "offset": 0, "length": 1}


# ---------------------------------------------------------------------------
# Reading the rows
# ---------------------------------------------------------------------------


def test_the_rows_are_read_out_of_the_embedded_json() -> None:
    html = page(
        row("Works at Biohub", ranges=[entity("https://www.facebook.com/biohub")]),
        row("Lives in Palo Alto, California"),
    )
    intro = parse_intro(html)

    assert [r.text for r in intro.rows] == [
        "Works at Biohub",
        "Lives in Palo Alto, California",
    ]
    assert intro.current_organization == "Biohub"
    assert intro.location == "Palo Alto, California"


def test_a_page_without_an_intro_yields_nothing() -> None:
    """The normal case for a personal profile, whose Intro needs a login.

    It has to come back empty rather than half-guessed: inventing an employer
    for someone because a word appeared in the page would be exactly the kind
    of claim this project exists not to make.
    """
    intro = parse_intro("<html><body>no intro here</body></html>")

    assert not intro
    assert intro.rows == []
    assert intro.current_organization is None
    assert intro.as_metadata() == {}


def test_one_malformed_row_does_not_cost_the_others() -> None:
    html = page(row("Works at Biohub")).replace(
        '"timeline_context_item": {"renderer"',
        '"timeline_context_item": {"renderer"',
    )
    broken = (
        '<script>"timeline_context_item":{"renderer":{oops</script>' + html
    )
    assert parse_intro(broken).current_organization == "Biohub"


def test_a_repeated_row_is_recorded_once() -> None:
    html = page(row("Works at Biohub"), row("Works at Biohub"))
    assert len(parse_intro(html).rows) == 1


# ---------------------------------------------------------------------------
# Reading each row correctly
# ---------------------------------------------------------------------------


def test_each_kind_of_row_is_classified() -> None:
    cases = {
        "Works at Biohub": ("work", "Biohub", None),
        "Founder and CEO at Meta": ("work", "Meta", "Founder and CEO"),
        "Former Director of Engineering at TAI Inc.": (
            "past_work",
            "TAI Inc.",
            "Director of Engineering",
        ),
        "Studied Computer Science at Harvard University": (
            "education",
            "Harvard University",
            "Computer Science",
        ),
        "Went to Brindavan College": ("education", "Brindavan College", None),
        "Lives in Palo Alto, California": ("location", "Palo Alto, California", None),
        "From Dobbs Ferry, New York": ("hometown", "Dobbs Ferry, New York", None),
        "Married to Priscilla Chan": ("relationship", "Priscilla Chan", "Married to"),
        "Joined September 2015": ("joined", "September 2015", None),
        "Profile · Digital creator": ("category", "Digital creator", None),
        "Page · Public figure": ("category", "Public figure", None),
    }
    for text, expected in cases.items():
        assert classify(text) == expected, text


def test_former_roles_are_not_read_as_current_employment() -> None:
    """"Former Director at X" must never become "works at X"."""
    html = page(
        row("Former Director of Engineering at TAI Inc."),
        row("Works at Upaya"),
    )
    intro = parse_intro(html)

    assert intro.current_organization == "Upaya"
    # Both still count as organizations worth correlating on.
    assert intro.organizations == ["Upaya", "TAI Inc."]


def test_organizations_are_listed_current_first() -> None:
    html = page(
        row("Studied M.S. Data Science at University of Greenwich"),
        row("Former Senior Engineer at CloudFactory"),
        row("Works at Deerwalk"),
    )
    assert parse_intro(html).organizations == [
        "Deerwalk",
        "CloudFactory",
        "University of Greenwich",
    ]


# ---------------------------------------------------------------------------
# The part an investigation most wants: links to other platforms
# ---------------------------------------------------------------------------


def test_an_outbound_link_is_unwrapped_from_the_redirector() -> None:
    """Stored wrapped, every external link would read as a Facebook one."""
    wrapped = (
        "https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.instagram.com"
        "%2Fprabhatacharya19%2F&h=AUAtgvFPPlKb&s=1"
    )
    assert unwrap_link(wrapped) == "https://www.instagram.com/prabhatacharya19/"


def test_a_link_that_is_not_wrapped_is_left_alone() -> None:
    assert unwrap_link("https://example.com/a") == "https://example.com/a"
    assert unwrap_link("https://www.facebook.com/biohub") == (
        "https://www.facebook.com/biohub"
    )


def test_a_linked_account_on_another_platform_is_published_as_a_link() -> None:
    """The strongest thing an Intro can offer: the profile says where else it is."""
    html = page(
        row(
            "prabhatacharya19",
            ranges=[
                entity(
                    "https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.instagram.com"
                    "%2Fprabhatacharya19%2F&h=AUA",
                    typename="ExternalUrl",
                )
            ],
        ),
        row("Works at Deerwalk", ranges=[entity("https://www.facebook.com/deerwalk")]),
    )
    intro = parse_intro(html)

    assert intro.external_links == ["https://www.instagram.com/prabhatacharya19/"]
    # The Facebook page for the employer is not an "external" link.
    assert "facebook.com" not in " ".join(intro.external_links)


def test_a_row_that_is_itself_an_address_counts_as_a_link() -> None:
    """A website row links nowhere in the JSON but is still a published link."""
    html = page(row("nationalgeographic.com"))
    assert parse_intro(html).external_links == ["https://nationalgeographic.com"]


def test_the_linked_url_is_preferred_over_the_text_of_the_row() -> None:
    """The row text is a display form; the range carries the real address.

    This matters for a row like "gatesnot.es/AI", whose text the bare-domain
    extractor does not recognise - `.es` is outside its gTLD list - but whose
    range carries the full wrapped URL. The link survives because the range is
    read first; the text is only a fallback.
    """
    html = page(
        row(
            "gatesnot.es/AI",
            ranges=[
                entity(
                    "https://l.facebook.com/l.php?u=http%3A%2F%2Fgatesnot.es%2FAI&h=A",
                    typename="ExternalUrl",
                )
            ],
        )
    )
    assert parse_intro(html).external_links == ["http://gatesnot.es/AI"]


# ---------------------------------------------------------------------------
# What reaches the rest of the investigation
# ---------------------------------------------------------------------------


def test_the_adapter_publishes_the_intro_into_the_profile() -> None:
    """Organization and location feed scoring; the rows feed the analyst."""
    html = page(
        row("Works at Biohub", ranges=[entity("https://www.facebook.com/biohub")]),
        row("Lives in Palo Alto, California"),
        row("Studied Computer Science at Harvard University"),
    ).replace(
        '<meta property="og:title" content="Someone"/>',
        '<meta property="og:title" content="Mark Zuckerberg"/>'
        '<meta property="og:description" content="Mark Zuckerberg. 5 likes."/>',
    )
    adapter = FacebookAdapter()

    assert adapter.extract_organization({}, html) == "Biohub"
    assert adapter.extract_location({}, html) == "Palo Alto, California"

    metadata = adapter.extract_metadata({}, html)
    assert metadata["intro_location"] == "Palo Alto, California"
    assert metadata["intro_organizations"] == ["Biohub", "Harvard University"]
    # The verbatim lines travel too, so an analyst reads what was published
    # rather than only this module's reading of it.
    assert "Works at Biohub" in metadata["intro"]


def test_an_intro_free_page_leaves_the_profile_fields_empty() -> None:
    adapter = FacebookAdapter()
    html = '<html><meta property="og:title" content="Someone"/></html>'

    assert adapter.extract_organization({}, html) is None
    assert adapter.extract_location({}, html) is None
    assert "intro" not in adapter.extract_metadata({}, html)
