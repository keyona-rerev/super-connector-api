import os
import voyageai

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])
    return _client

def embed_profile(text: str) -> list[float]:
    """Convert a profile text string into a 1024-dim vector using Voyage AI."""
    client = _get_client()
    result = client.embed(
        [text],
        model="voyage-3-lite",
        input_type="document"
    )
    return result.embeddings[0]

def embed_query(text: str) -> list[float]:
    """Embed a search query (used when matching by need, not by profile)."""
    client = _get_client()
    result = client.embed(
        [text],
        model="voyage-3-lite",
        input_type="query"
    )
    return result.embeddings[0]
