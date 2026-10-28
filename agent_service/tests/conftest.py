import os
import sys
from pathlib import Path

# Offline mode for every test: scripted LLM, hashed embeddings, demo data, no auth.
os.environ.update({"LLM_PROVIDER": "fake", "EMBEDDING_PROVIDER": "hash", "AUTH_DISABLED": "true",
                   "POLYGON_API_KEY": "", "FIREBASE_SERVICE_ACCOUNT": "", "CHECKPOINT_DB_URL": "",
                   "INDEX_DIR": str(Path(__file__).parent / "_no_index")})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from bullrun_agent import rag  # noqa: E402
from bullrun_agent.llm import HashEmbeddings  # noqa: E402
from bullrun_agent.rag.chunking import chunk_filing  # noqa: E402
from bullrun_agent.rag.store import HybridIndex  # noqa: E402

# Synthetic 10-K-shaped text (not real filing content) for retrieval tests.
FAKE_10K = """
TABLE OF CONTENTS
Item 1. Business
Item 1A. Risk Factors
Item 7. Management's Discussion and Analysis

PART I
Item 1. Business

Acme Chips designs graphics processors and data center accelerators. Our data center platform
serves cloud providers, enterprises and research institutions across many regions of the world.

Our gaming segment sells graphics cards through retail partners and system builders worldwide.

Item 1A. Risk Factors

We depend on third-party foundries to manufacture our products, and supply constraints at those
foundries could limit our ability to meet customer demand for accelerators in future quarters.

Government export controls may restrict our ability to sell advanced products to customers in
certain countries, which could reduce our revenue and harm our competitive position materially.

Item 7. Management's Discussion and Analysis

Data center revenue grew significantly year over year, driven by demand for accelerated computing
platforms from hyperscale cloud customers and enterprise AI deployments around the world.

Item 9. Changes in and Disagreements with Accountants

None.
"""


@pytest.fixture
def fake_index():
    chunks = chunk_filing(FAKE_10K, {"ticker": "ACME", "form": "10-K", "filed": "2026-02-20",
                                     "url": "https://example.com/acme-10k"}, size=300, overlap=50)
    idx = HybridIndex.build(chunks, HashEmbeddings())
    rag.set_index(idx)
    yield idx
    rag.set_index(None)
