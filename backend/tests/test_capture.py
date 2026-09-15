"""The dataset capture tool, and the two judgements it encodes.

This is developer tooling rather than application code, but it decides what
counts as ground truth, and a mislabelled pair is worse than a missing one -
it teaches the calibration the wrong thing and every measurement downstream
inherits it.
"""

from __future__ import annotations

import json

import pytest

from calibration.capture import _canonical, _clusters, suggest


@pytest.mark.parametrize(
    "first,second",
    [
        ("https://github.com/simonw", "http://github.com/simonw"),
        ("https://www.github.com/simonw", "https://github.com/simonw"),
        ("https://github.com/simonw/", "https://github.com/simonw"),
        ("https://GitHub.com/SimonW", "https://github.com/simonw"),
    ],
)
def test_addresses_for_the_same_profile_compare_equal(first: str, second: str) -> None:
    """A site publishes one form and links another; neither changes who it is."""
    assert _canonical(first) == _canonical(second)


def test_different_profiles_do_not_collapse() -> None:
    assert _canonical("https://github.com/simonw") != _canonical("https://github.com/simon")


def test_a_declaration_chain_becomes_one_party() -> None:
    """A declares B, B declares C: A and C are the same party.

    Those implied pairs are the point of the exercise. Neither profile names
    the other, so the model has to infer the connection instead of reading it.
    """
    found = {("a", "b"): ["x"], ("b", "c"): ["y"]}

    assert _clusters(found) == [{"a", "b", "c"}]


def test_a_lone_declared_pair_is_not_a_cluster() -> None:
    """Two profiles that declare each other imply no third pair."""
    assert _clusters({("a", "b"): ["x"]}) == []


def test_a_shared_employer_is_not_a_declaration(tmp_path, capsys, monkeypatch) -> None:
    """The fault the first run of this tool actually had.

    Indexing the websites a profile lists, as well as its own address, matched
    two Automattic employees through wordpress.com and two more through
    automattic.com. A shared employer is a link both profiles publish and
    neither one asserts - and labelling those pairs 'same' would have taught
    the calibration that colleagues are one person.
    """
    profiles = {
        "github:alice": {
            "platform": "github",
            "url": "https://github.com/alice",
            "websites": ["https://example-corp.com"],
            "external_links": ["https://example-corp.com"],
        },
        "instagram:bob": {
            "platform": "instagram",
            "url": "https://instagram.com/bob",
            "websites": ["https://example-corp.com"],
            "external_links": ["https://example-corp.com"],
        },
    }
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(profiles))
    monkeypatch.setattr("calibration.capture.PROFILES", path)

    suggest()

    assert "No declared links" in capsys.readouterr().out


def test_a_link_to_the_other_profile_is_a_declaration(tmp_path, capsys, monkeypatch) -> None:
    profiles = {
        "github:alice": {
            "platform": "github",
            "url": "https://github.com/alice",
            "external_links": ["https://instagram.com/alice"],
        },
        "instagram:alice": {
            "platform": "instagram",
            "url": "https://instagram.com/alice",
            "external_links": [],
        },
    }
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(profiles))
    monkeypatch.setattr("calibration.capture.PROFILES", path)

    suggest()

    assert "github:alice  <->  instagram:alice" in capsys.readouterr().out


def test_two_accounts_on_one_platform_are_not_a_cross_platform_declaration(
    tmp_path, capsys, monkeypatch
) -> None:
    """A project account linking a maintainer's account on the same site is a
    reference, not a second identity for the same party."""
    profiles = {
        "github:project": {
            "platform": "github",
            "url": "https://github.com/project",
            "external_links": ["https://github.com/alice"],
        },
        "github:alice": {
            "platform": "github",
            "url": "https://github.com/alice",
            "external_links": [],
        },
    }
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(profiles))
    monkeypatch.setattr("calibration.capture.PROFILES", path)

    suggest()

    assert "No declared links" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The guard on the test database itself
# ---------------------------------------------------------------------------


def test_the_suite_refuses_to_wipe_an_unnamed_database_holding_data(monkeypatch) -> None:
    """conftest starts from an empty graph, which means deleting what is there.

    Correct for a scratch database, catastrophic for a live one, and Neo4j
    Community serves a single database - so with NEO4J_TEST_URI unset the
    tests land on exactly the graph the application is using. That destroyed
    real investigations several times during development before the guard
    existed.
    """
    import tests.conftest as conftest

    monkeypatch.setattr(conftest, "AIMED_AT_TEST_TARGET", False)
    monkeypatch.setattr(conftest, "WIPE_ANYWAY", False)

    class _Session:
        def run(self, *_args, **_kwargs):
            class _Result:
                @staticmethod
                def single():
                    return {"nodes": 137, "investigations": 1}

            return _Result()

    class _Scope:
        def __enter__(self):
            return type("Repo", (), {"session": _Session()})()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("app.database.repository_scope", lambda: _Scope())

    with pytest.raises(Exception) as caught:
        conftest._guard_the_database()

    assert "Refusing to wipe" in str(caught.value)
    assert "137 node(s)" in str(caught.value)


def test_the_guard_stands_aside_for_a_named_test_target(monkeypatch) -> None:
    """Naming NEO4J_TEST_URI is the opt-in, and has to keep working -
    a guard that blocks the documented path would just get deleted."""
    import tests.conftest as conftest

    monkeypatch.setattr(conftest, "AIMED_AT_TEST_TARGET", True)

    def _explode():
        raise AssertionError("the guard queried a database it was told to trust")

    monkeypatch.setattr("app.database.repository_scope", _explode)

    conftest._guard_the_database()
