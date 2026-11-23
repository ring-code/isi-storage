# app/utility/relationship_helpers.py

from sqlalchemy import inspect
from sqlalchemy.orm import ONETOMANY

def is_model_instance_in_use(instance, exclude_relationships=None) -> tuple[bool, str | None]:
    """
    Checks if a given SQLAlchemy model instance is in use by any of its
    'one-to-many' relationships.

    Args:
        instance: The SQLAlchemy model instance to check.
        exclude_relationships (list, optional): A list of relationship names
                                                (strings) to ignore during the check.

    Returns:
        Tuple: (True, "relationship_name") if it's in use.
                 (False, None) if it's safe to delete.
    """
    if exclude_relationships is None:
        exclude_relationships = []

    mapper = inspect(instance.__class__)
    
    for rel in mapper.relationships:
        # Skip relationships that are in our exclusion list.
        if rel.key in exclude_relationships:
            continue
        
        # We only care about relationships where OTHER models point TO this one.
        # These are typically 'one-to-many' relationships on our model.
        if rel.direction != ONETOMANY:
            continue

        related_objects = getattr(instance, rel.key)
        
        if (rel.lazy == 'dynamic' and related_objects.first()) or \
           (rel.lazy != 'dynamic' and related_objects):
            
            return True, rel.key

    return False, None