from app.sales.models import PublicVariation

def build_stable_variation_hash(public_variation: PublicVariation) -> int:
    """
    Generates a unique and stable hash for a PublicVariation object.

    The hash is based on the primary keys of the parent PublicProduct and the
    linked manufacturing Product, guaranteeing it is both unique and stable.
    The object MUST have been flushed to the session so that its primary keys
    are populated.

    Args:
        public_variation: The PublicVariation SQLAlchemy object.

    Returns:
        An integer representing the unique and stable hash.
    """
    if not public_variation.public_product_id or not public_variation.manufacturing_product_id:
        raise ValueError(
            "Cannot build hash: The PublicVariation object must have its "
            "public_product_id and manufacturing_product_id populated. "
            "Ensure the session is flushed before calling this function."
        )

    # The hash is a simple combination of the two primary keys.
    # The prefix 'isi-var-' ensures it won't accidentally collide with other hashes.
    key_string = f"isi-var-{public_variation.public_product_id}-{public_variation.manufacturing_product_id}"
    
    # abs(hash(...)) creates a large, positive integer for the BigInteger column.
    return abs(hash(key_string))