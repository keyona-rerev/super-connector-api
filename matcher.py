from db import find_similar, find_similar_by_vector

def find_matches(contact_id: str, limit: int = 5):
    return find_similar(contact_id, limit=limit)

def find_matches_by_vector(vector: list, limit: int = 10):
    return find_similar_by_vector(vector, limit=limit)
