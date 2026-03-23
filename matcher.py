from db import find_similar

def find_matches(contact_id: str, limit: int = 5):
    """
    Find the top N most semantically similar contacts to a given contact.
    Returns None if the contact isn't in the vector DB yet.
    """
    return find_similar(contact_id, limit=limit)
