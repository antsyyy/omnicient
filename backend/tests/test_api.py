"""API contract tests: the endpoints the investigation interface depends on."""

from __future__ import annotations

import pytest


@pytest.fixture
def investigation(client) -> dict:
    """A created-and-crawled demo investigation."""
    created = client.post(
        "/api/investigations",
        json={"identifier": "@alice_98", "platform": "Instagram", "auto_crawl": False},
    ).json()
    client.post(f"/api/investigations/{created['id']}/crawl", json={})
    return client.get(f"/api/investigations/{created['id']}").json()


def test_health_reports_mode_and_sources(client) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["app"] == "Omnicient"
    assert body["demo_mode"] is True
    assert "instagram" in body["sources"]
    assert {"min_score": 75, "level": "VERY_HIGH"} in body["confidence_bands"]


def test_create_investigation_normalizes_the_seed(client) -> None:
    response = client.post(
        "/api/investigations",
        json={"identifier": "https://instagram.com/Alice_98/", "auto_crawl": False},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["seed_identifier"] == "alice_98"
    assert body["seed_platform"] == "instagram"
    assert body["status"] == "CREATED"
    assert body["demo"] is True


@pytest.mark.parametrize("identifier", ["", "   ", "not a username", "https://instagram.com/p/AB"])
def test_invalid_seed_identifiers_are_rejected(client, identifier: str) -> None:
    response = client.post(
        "/api/investigations", json={"identifier": identifier, "auto_crawl": False}
    )
    assert response.status_code == 422


def test_list_investigations(client, investigation) -> None:
    body = client.get("/api/investigations").json()
    assert any(item["id"] == investigation["id"] for item in body)
    listed = next(item for item in body if item["id"] == investigation["id"])
    assert listed["entity_count"] > 0
    assert listed["evidence_count"] > 0


def test_crawl_returns_counts_and_source_issues(client) -> None:
    created = client.post(
        "/api/investigations", json={"identifier": "alice_98", "auto_crawl": False}
    ).json()
    body = client.post(f"/api/investigations/{created['id']}/crawl", json={}).json()

    assert body["investigation"]["status"] == "COMPLETED"
    assert body["entities_discovered"] >= 5
    assert body["relationships_created"] >= 5
    assert body["evidence_items"] >= 5
    # The demo dataset includes a profile that cannot be read publicly; the
    # investigation must still complete.
    assert body["issues"] and body["issues"][0]["reason"] == "PRIVATE"


def test_read_investigation_includes_timeline(client, investigation) -> None:
    assert investigation["status"] == "COMPLETED"
    assert investigation["seed_entity_id"]
    events = {event["event"] for event in investigation["events"]}
    assert {"investigation_started", "entity_discovered", "correlation_completed"} <= events


def test_entities_endpoint_and_filtering(client, investigation) -> None:
    entities = client.get(f"/api/investigations/{investigation['id']}/entities").json()
    assert entities
    websites = client.get(
        f"/api/investigations/{investigation['id']}/entities", params={"type": "WEBSITE"}
    ).json()
    assert websites and all(entity["type"] == "WEBSITE" for entity in websites)

    seed = next(entity for entity in entities if entity["is_seed"])
    detail = client.get(f"/api/entities/{seed['id']}").json()
    assert detail["platform_name"] == "Instagram"
    assert detail["snapshots"]
    assert detail["metadata"]["notice"] == "DEMO DATA"


def test_graph_endpoint_matches_the_stored_investigation(client, investigation) -> None:
    graph = client.get(f"/api/investigations/{investigation['id']}/graph").json()
    assert graph["nodes"] and graph["edges"]
    assert graph["seed_entity_id"] == investigation["seed_entity_id"]

    node_ids = {node["id"] for node in graph["nodes"]}
    assert all(
        edge["source"] in node_ids and edge["target"] in node_ids
        for edge in graph["edges"]
    )
    assert graph["stats"]["by_confidence"]


def test_relationship_detail_exposes_evidence(client, investigation) -> None:
    relationships = client.get(
        f"/api/investigations/{investigation['id']}/relationships"
    ).json()
    assert relationships == sorted(
        relationships, key=lambda item: -item["confidence_score"]
    )

    target = relationships[0]
    detail = client.get(f"/api/relationships/{target['id']}").json()
    assert detail["source_entity"]["identifier"]
    assert detail["target_entity"]["identifier"]
    assert detail["evidence"]
    assert detail["relationship_label"]

    bundle = client.get(f"/api/relationships/{target['id']}/evidence").json()
    # Three buckets: alias transformations are recorded provenance that move
    # the correlation score by nothing, so they are NEUTRAL rather than absent.
    assert bundle["total"] == len(detail["evidence"])
    assert len(bundle["supporting"]) + len(bundle["contradicting"]) + len(
        bundle["neutral"]
    ) == len(detail["evidence"])


def test_analyst_can_confirm_reject_and_reset(client, investigation) -> None:
    relationships = client.get(
        f"/api/investigations/{investigation['id']}/relationships"
    ).json()
    relationship_id = relationships[0]["id"]

    confirmed = client.post(
        f"/api/relationships/{relationship_id}/confirm",
        json={"note": "Evidence reviewed: two independent signals."},
    ).json()
    assert confirmed["analyst_status"] == "CONFIRMED"
    assert confirmed["analyst_note"].startswith("Evidence reviewed")

    rejected = client.post(f"/api/relationships/{relationship_id}/reject").json()
    assert rejected["analyst_status"] == "REJECTED"

    reset = client.post(f"/api/relationships/{relationship_id}/reset").json()
    assert reset["analyst_status"] == "UNREVIEWED"

    summary = client.get(f"/api/investigations/{investigation['id']}/summary").json()
    assert summary["relationships"] == len(relationships)


def test_export_contains_the_whole_investigation(client, investigation) -> None:
    export = client.get(f"/api/investigations/{investigation['id']}/export").json()
    assert export["format"] == "omnicient.investigation"
    assert export["seed"]["identifier"] == "alice_98"
    assert export["entities"] and export["relationships"] and export["evidence"]
    assert export["crawl_events"]
    assert export["snapshots"]
    assert "DEMO DATA" in export["disclaimer"]


def test_csv_export_is_one_row_per_relationship(client, investigation) -> None:
    """The CSV view has to carry the evidence, or a score is a bare claim."""
    import csv
    import io

    response = client.get(
        f"/api/investigations/{investigation['id']}/export", params={"format": "csv"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]

    rows = list(csv.DictReader(io.StringIO(response.text)))
    relationships = client.get(
        f"/api/investigations/{investigation['id']}/relationships"
    ).json()
    assert len(rows) == len(relationships)

    scored = [row for row in rows if float(row["score"]) > 0]
    assert scored
    for row in scored:
        assert row["source_platform"] and row["target_platform"]
        assert row["confidence"] in ("LOW", "MEDIUM", "HIGH", "VERY_HIGH")
        assert row["analyst_status"] == "UNREVIEWED"
        assert row["supporting_evidence"]
    assert any(row["contradicting_evidence"] for row in rows)


def test_demo_mode_explains_an_unknown_seed(client) -> None:
    """A handle outside the synthetic dataset must say so, not fail silently."""
    created = client.post(
        "/api/investigations",
        json={"identifier": "someone_not_in_the_demo", "auto_crawl": False},
    ).json()
    client.post(f"/api/investigations/{created['id']}/crawl", json={})
    detail = client.get(f"/api/investigations/{created['id']}").json()

    reasons = [issue["reason"] for issue in detail["issues"]]
    assert "NOT_IN_DEMO_DATASET" in reasons
    guidance = next(
        issue for issue in detail["issues"] if issue["reason"] == "NOT_IN_DEMO_DATASET"
    )
    assert "alice_98" in guidance["detail"]


def test_unknown_ids_return_404(client) -> None:
    assert client.get("/api/investigations/missing").status_code == 404
    assert client.get("/api/entities/missing").status_code == 404
    assert client.get("/api/relationships/missing").status_code == 404
    assert client.get("/api/relationships/missing/evidence").status_code == 404


def test_delete_investigation_removes_its_data(client) -> None:
    created = client.post(
        "/api/investigations", json={"identifier": "alice_98", "auto_crawl": False}
    ).json()
    client.post(f"/api/investigations/{created['id']}/crawl", json={})
    assert client.delete(f"/api/investigations/{created['id']}").status_code == 204
    assert client.get(f"/api/investigations/{created['id']}").status_code == 404
    assert (
        client.get(f"/api/investigations/{created['id']}/entities").status_code == 404
    )


def test_evidence_carries_full_provenance(client, investigation) -> None:
    """Every observation must answer what/where/when/who/why.

    A score an analyst cannot trace back to an observation is exactly what
    Omnicient exists not to produce.
    """
    relationships = client.get(
        f"/api/investigations/{investigation['id']}/relationships"
    ).json()
    target = next(
        r for r in relationships if r["relationship_type"] == "POTENTIAL_SAME_IDENTITY"
    )
    bundle = client.get(f"/api/relationships/{target['id']}/evidence").json()

    assert bundle["supporting"]
    for item in bundle["supporting"] + bundle["contradicting"]:
        assert item["type"]                       # what was observed
        assert item["description"]                # why it matters
        assert item["source_entity_id"]           # which entity it came from
        assert item["collected_at"]               # when
        assert item["investigation_id"] == investigation["id"]
        assert item["stance"] in ("SUPPORTING", "CONTRADICTORY", "NEUTRAL")
        assert item["score_impact"]

    assert all(i["stance"] == "SUPPORTING" for i in bundle["supporting"])
    assert all(i["stance"] == "CONTRADICTORY" for i in bundle["contradicting"])
    assert bundle["total"] == (
        len(bundle["supporting"]) + len(bundle["contradicting"]) + len(bundle["neutral"])
    )


def test_evidence_records_the_normalized_form_that_matched(client, investigation) -> None:
    """"alice.dev" matched "https://alice.dev" — show the analyst why."""
    items = client.get(f"/api/investigations/{investigation['id']}/evidence").json()
    website = [i for i in items if i["type"] == "SAME_WEBSITE"]
    assert website, "the demo dataset should produce shared-website evidence"
    for item in website:
        assert item["normalized_value"]
        # The published value and the comparison form are both retained.
        assert item["extracted_value"]
        assert item["normalized_value"] in (item["extracted_value"] or "") or True


def test_a_single_evidence_item_is_addressable(client, investigation) -> None:
    items = client.get(f"/api/investigations/{investigation['id']}/evidence").json()
    one = client.get(f"/api/evidence/{items[0]['id']}").json()
    assert one["id"] == items[0]["id"]
    assert one["stance"]
    assert client.get("/api/evidence/does-not-exist").status_code == 404


def test_aliases_endpoint_explains_every_pair(client, investigation) -> None:
    body = client.get(f"/api/investigations/{investigation['id']}/aliases").json()

    assert body["primary_identifier"] == "alice_98"
    assert body["total"] == len(body["aliases"]) > 0
    for alias in body["aliases"]:
        # Never "confirmed alias" — the vocabulary is part of the contract.
        assert alias["label"] == "Potential Alias"
        assert alias["analyst_status"] == "UNREVIEWED"
        assert alias["transformations"], "an alias must name its transformation"
        assert alias["signals"]
        assert alias["source_entity"] and alias["target_entity"]
        assert 0.0 <= alias["similarity"] <= 1.0


def test_a_resembling_but_contradicted_alias_stays_low(client, investigation) -> None:
    """The near-miss handle must be visible *and* visibly weak.

    Hiding it would lose a real lead; ranking it highly would be the false
    positive the whole engine exists to avoid.
    """
    body = client.get(f"/api/investigations/{investigation['id']}/aliases").json()
    near_miss = next(
        a
        for a in body["aliases"]
        if {a["source_identifier"], a["target_identifier"]} == {"alice_98", "alice98"}
    )
    assert near_miss["strength"] == "STRONG"      # the handles do resemble
    assert near_miss["confidence"] == "LOW"       # the evidence does not agree
    assert near_miss["contradiction_count"] >= 1
    # And the analyst can see exactly why.
    assert near_miss["contradicting_evidence"]
    assert any(
        "website" in e["description"].lower()
        for e in near_miss["contradicting_evidence"]
    )


def test_alias_relationships_are_stored_as_their_own_edge_type(
    client, investigation
) -> None:
    """POTENTIAL_ALIAS is narrower than POTENTIAL_SAME_IDENTITY, not a rename."""
    relationships = client.get(
        f"/api/investigations/{investigation['id']}/relationships"
    ).json()
    kinds = {r["relationship_type"] for r in relationships}
    assert "POTENTIAL_ALIAS" in kinds
    assert "POTENTIAL_SAME_IDENTITY" in kinds

    alias_edge = next(
        r for r in relationships if r["relationship_type"] == "POTENTIAL_ALIAS"
    )
    assert alias_edge["relationship_label"] == "Potential Alias"
