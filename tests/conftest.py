from pathlib import Path

import pytest

from patra.encode.loader import (
    load_axioms,
    load_documents,
    load_households,
    load_schema,
    load_schemes,
)
from patra.engine import Engine

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="session")
def schema():
    return load_schema(DATA / "attributes.yaml")


@pytest.fixture(scope="session")
def schemes(schema):
    return load_schemes(DATA / "schemes", schema)


@pytest.fixture(scope="session")
def by_id(schemes):
    return {s.id: s for s in schemes}


@pytest.fixture(scope="session")
def documents():
    return load_documents(DATA / "documents.yaml")


@pytest.fixture(scope="session")
def axioms(schema):
    return load_axioms(DATA / "axioms.yaml", schema)


@pytest.fixture(scope="session")
def households(schema):
    return {h.id: h for h in load_households(DATA / "cases" / "households.yaml", schema)}


@pytest.fixture
def engine(schema, axioms, documents):
    return Engine(schema, axioms, documents)


@pytest.fixture(scope="session")
def cues():
    import yaml
    return yaml.safe_load((DATA / "cues.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def signatures():
    import yaml
    return yaml.safe_load((DATA / "papers.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def extractor(schema, cues):
    from patra.nlp.extract import Extractor
    return Extractor(schema, cues)


@pytest.fixture
def guard(engine, schema):
    from patra.guard import Guard
    return Guard(engine, schema)


@pytest.fixture
def profile_of(schema, households):
    """A household flattened for a named member, as the reasoner sees it."""
    from patra.model.household import project

    def make(household_id, member_id=None):
        household = households[household_id]
        if member_id is None and household.members:
            member_id = household.members[0].id
        return project(household, schema, member_id)

    return make


@pytest.fixture(scope="session")
def offices():
    from patra.camp.model import load_offices
    return load_offices(DATA / "offices.yaml")


@pytest.fixture(scope="session")
def village(schema):
    return load_households(DATA / "cases" / "village.yaml", schema)


@pytest.fixture(scope="session")
def needs(schema, schemes, documents, offices, village, axioms):
    """The village survey, computed once for the whole session.

    It is the better part of a minute, so a per-test fixture would make the
    suite unusable. A cut-down village keeps it to a few seconds while still
    exercising the same code.
    """
    from patra.camp.model import survey
    from patra.engine import Engine

    engine = Engine(schema, axioms, documents)
    return survey(engine, schema, schemes, documents, offices, village[:30])
