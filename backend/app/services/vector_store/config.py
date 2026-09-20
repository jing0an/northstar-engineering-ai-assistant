"""Centralized local Qdrant configuration."""

import os

QDRANT_HOST = os.getenv("QDRANT_HOST", "127.0.0.1").strip() or "127.0.0.1"
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "northstar_chunks").strip() or "northstar_chunks"
