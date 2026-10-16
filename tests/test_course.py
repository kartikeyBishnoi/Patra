"""The course map and the agent descriptions, checked rather than trusted.

A map that names a module which does not exist, or claims a topic is built
when nothing points at it, is worse than no map: it is a claim an examiner
will check and find false.
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
HANDOUT_TOPICS = 10


@pytest.fixture(scope="module")
def course():
    return yaml.safe_load(
        (ROOT / "data" / "course.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def agents():
    return yaml.safe_load(
        (ROOT / "data" / "agents.yaml").read_text(encoding="utf-8"))


# ---- the course map ----

def test_every_handout_topic_is_on_the_map(course):
    numbers = sorted(t["number"] for t in course["topics"])
    assert numbers == list(range(1, HANDOUT_TOPICS + 1)), numbers


def test_every_topic_says_where_it_stands(course):
    for topic in course["topics"]:
        assert topic["status"] in ("built", "part", "argued"), topic["id"]
        assert topic["features"], topic["id"]


def test_every_cited_file_exists(course):
    """The part an examiner will actually check."""
    missing = []
    for topic in course["topics"]:
        for feature in topic["features"]:
            for path in feature["code"].split(","):
                path = path.strip()
                if not path or not (ROOT / path).exists():
                    missing.append((topic["id"], path))
    assert not missing, missing


def test_the_gaps_are_on_the_map(course):
    """A map with no gaps is not a map of anything. Generative models,
    transformers and language models are absent on purpose, and the map has
    to say so rather than quietly omit them."""
    argued = {t["id"] for t in course["topics"] if t["status"] == "argued"}
    assert {"genmodels", "transformer", "llm"} <= argued


def test_an_argued_topic_gives_a_reason_not_an_excuse(course):
    for topic in course["topics"]:
        if topic["status"] != "argued":
            continue
        for feature in topic["features"]:
            assert len(feature["what"]) > 120, topic["id"]
            assert "because" in feature["what"] or "." in feature["what"]


def test_search_and_csp_are_claimed_only_because_they_exist(course):
    """These two were the real gaps against the handout, so the modules
    behind them had better be there."""
    from patra.csp.solve import solve          # noqa: F401
    from patra.search.graph import a_star      # noqa: F401

    by_id = {t["id"]: t for t in course["topics"]}
    assert by_id["search"]["status"] == "built"
    assert by_id["planning"]["status"] == "built"
    cited = " ".join(f["code"] for f in by_id["search"]["features"])
    assert "patra/search" in cited
    cited = " ".join(f["code"] for f in by_id["planning"]["features"])
    assert "patra/csp" in cited


# ---- the agents ----

PEAS = ("performance", "measure", "environment", "sensors", "actuators")
KINDS = {"simple reflex", "model-based reflex", "goal-based", "utility-based"}


def test_every_agent_has_a_full_peas(agents):
    for agent in agents["agents"]:
        for part in PEAS:
            assert agent.get(part), (agent["id"], part)


def test_every_agent_has_a_type_the_course_names(agents):
    for agent in agents["agents"]:
        assert agent["kind"] in KINDS, (agent["id"], agent["kind"])


def test_all_four_agent_types_appear(agents):
    """The course lists four. A project with only one kind has not thought
    about the question."""
    assert {a["kind"] for a in agents["agents"]} == KINDS


def test_the_agents_that_read_the_world_cannot_conclude(agents):
    """The architecture in one assertion. A reflex agent allowed to conclude
    is the failure this whole project is built to prevent, so the two that
    read speech and photographs are reflex agents and neither decides."""
    reading = {"reader", "eye"}
    for agent in agents["agents"]:
        if agent["id"] in reading:
            assert agent["kind"] == "simple reflex", agent["id"]
            assert "propos" in agent["actuators"].lower(), agent["id"]


def test_every_agent_points_at_code_that_exists(agents):
    for agent in agents["agents"]:
        for path in agent["code"].split(","):
            assert (ROOT / path.strip()).exists(), (agent["id"], path)


def test_the_expert_system_parts_are_all_named(agents):
    parts = {p["part"].lower() for p in agents["expert_system"]}
    for wanted in ("knowledge base", "inference engine", "working memory",
                   "explanation facility"):
        assert wanted in parts, wanted


def test_every_expert_system_part_points_at_code(agents):
    for part in agents["expert_system"]:
        assert (ROOT / part["code"].strip()).exists(), part["part"]
