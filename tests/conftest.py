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
