# /app/utility/public_product_logic.py

from app.products.models import Product, ProductUnit
from app.sales.models import PublicProduct, PublicVariation, SaleGrade, RentalGrade
from app.extensions import db
from app.utility.hashing_logic import build_stable_variation_hash
from sqlalchemy.orm import joinedload
from flask import abort
import re

def get_units_for_public_product(public_product_id: int) -> list[ProductUnit]:
    """
    Finds all ProductUnit instances that logically belong to a PublicProduct.

    This function bridges the "Sales Layer" (PublicProduct) and the "Physical Layer"
    (ProductUnit) by querying for units that match both the commercial grade and
    one of the manufacturing SKUs (variations) of the given PublicProduct.

    Args:
        public_product_id: The primary key of the PublicProduct to find units for.

    Returns:
        A list of ProductUnit objects, ordered by serial number. Returns an
        empty list if the PublicProduct has no variations or no matching units are found.
        Aborts with a 404 error if the public_product_id is invalid.
    """
    public_product = PublicProduct.query.get(public_product_id)
    if not public_product:
        # It's better to abort here than to let get_or_404 handle it,
        # as this is a helper function.
        abort(404, description=f"PublicProduct with id {public_product_id} not found.")
    
    manufacturing_ids = [v.manufacturing_product_id for v in public_product.variations]
    if not manufacturing_ids:
        return []

    query = ProductUnit.query.filter(
        ProductUnit.product_id.in_(manufacturing_ids)
    )

    if public_product.grade_type == 'rental_grade':
        query = query.filter(ProductUnit.rental_grade_id == public_product.grade_id)
    elif public_product.grade_type == 'sale_grade':
        query = query.filter(ProductUnit.sale_grade_id == public_product.grade_id)

    # Eagerly load related data needed for display in the template
    return query.options(
        joinedload(ProductUnit.product),
        joinedload(ProductUnit.space)
    ).order_by(ProductUnit.serial_number).all()


def get_available_rental_grades(public_product_id=None):
    """
    Returns a query of all RentalGrades that are not yet used by a PublicProduct.
    If editing, it includes the current PublicProduct's own grade.
    """
    # Find IDs of all rental grades already in use
    used_grade_ids = [
        sp.grade_id for sp in PublicProduct.query.filter_by(grade_type='rental_grade').all()
    ]
    
    query = RentalGrade.query.filter(RentalGrade.id.notin_(used_grade_ids))
    
    # If we are editing, we must add the current grade back into the list
    if public_product_id:
        current_sp = PublicProduct.query.get(public_product_id)
        if current_sp and current_sp.grade_type == 'rental_grade':
            # This is a bit complex, but it merges the two queries
            current_grade_query = RentalGrade.query.filter_by(id=current_sp.grade_id)
            query = query.union(current_grade_query)

    return query.order_by(RentalGrade.name)


def get_available_sale_grades(public_product_id=None):
    """
    Returns a query of all SaleGrades that are not yet used by a PublicProduct.
    If editing, it includes the current PublicProduct's own grade.
    """
    used_grade_ids = [
        sp.grade_id for sp in PublicProduct.query.filter_by(grade_type='sale_grade').all()
    ]
    
    query = SaleGrade.query.filter(SaleGrade.id.notin_(used_grade_ids))
    
    if public_product_id:
        current_sp = PublicProduct.query.get(public_product_id)
        if current_sp and current_sp.grade_type == 'sale_grade':
            current_grade_query = SaleGrade.query.filter_by(id=current_sp.grade_id)
            query = query.union(current_grade_query)

    return query.order_by(SaleGrade.name)


def generate_unique_public_sku(name: str, existing_public_product_id: int = None) -> str:
    """
    Generates a unique public SKU from a product name.

    It cleans the name, converts it to a URL-friendly slug, and ensures it
    doesn't already exist in the database. If it does, it appends a counter.

    Args:
        name: The public-facing name of the PublicProduct.
        existing_public_product_id: If editing an existing product, provide its ID
                                     to exclude it from the uniqueness check.

    Returns:
        A unique, URL-friendly SKU string.
    """
    if not name:
        return ""

    # 1. Convert to uppercase and replace spaces with hyphens
    base_sku = name.upper().replace(' ', '-')
    
    # 2. Remove any characters that are not A-Z, 0-9, or hyphen
    base_sku = re.sub(r'[^A-Z0-9-]+', '', base_sku)
    
    # 3. Collapse multiple hyphens into one (e.g., '---' -> '-')
    base_sku = re.sub(r'-+', '-', base_sku)

    # --- Uniqueness Check ---
    generated_sku = base_sku
    counter = 1
    
    # Build the initial query
    query = PublicProduct.query.filter(PublicProduct.public_sku == generated_sku)

    # If we are editing, exclude the current object from the check
    if existing_public_product_id:
        query = query.filter(PublicProduct.id != existing_public_product_id)

    # Loop while the generated SKU is found in the database
    while query.first():
        generated_sku = f"{base_sku}-{counter}"
        counter += 1
        # Update the query to check for the new, suffixed SKU
        query = PublicProduct.query.filter(PublicProduct.public_sku == generated_sku)
        if existing_public_product_id:
            query = query.filter(PublicProduct.id != existing_public_product_id)

    return generated_sku


def get_public_products_with_active_variations():
    """
    Fetches all PublicProducts and annotates them with a list of "active" variations.

    An "active" variation is an internal SKU (Product) that has at least one
    physical unit (ProductUnit) assigned to the PublicProduct's specific grade.

    Returns:
        A list of PublicProduct objects, where each object has a new attribute
        `.active_variations` containing the filtered list of PublicVariation objects.
    """
    # 1. Find all unique pairs of (product_id, grade_id) that actually exist in the ProductUnit table.
    active_rental_pairs = db.session.query(ProductUnit.product_id, ProductUnit.rental_grade_id).filter(ProductUnit.rental_grade_id.isnot(None)).distinct()
    active_rental_set = {(pid, gid) for pid, gid in active_rental_pairs}

    active_sale_pairs = db.session.query(ProductUnit.product_id, ProductUnit.sale_grade_id).filter(ProductUnit.sale_grade_id.isnot(None)).distinct()
    active_sale_set = {(pid, gid) for pid, gid in active_sale_pairs}

    # 2. Fetch all PublicProducts with their variations pre-loaded.
    all_public_products = PublicProduct.query.options(
        joinedload(PublicProduct.variations).joinedload(PublicVariation.manufacturing_product)
    ).order_by(PublicProduct.name).all()

    # 3. For each PublicProduct, filter its variations in Python using our sets.
    for sp in all_public_products:
        sp.active_variations = []
        for variation in sp.variations:
            # Check if the variation's (product_id, grade_id) pair exists in our active sets
            if sp.grade_type == 'rental_grade':
                if (variation.manufacturing_product_id, sp.grade_id) in active_rental_set:
                    sp.active_variations.append(variation)
            elif sp.grade_type == 'sale_grade':
                if (variation.manufacturing_product_id, sp.grade_id) in active_sale_set:
                    sp.active_variations.append(variation)
    
    return all_public_products


def refresh_variations_for_public_product(public_product: PublicProduct):
    """
    Recalculates and syncs the PublicVariation records for a given PublicProduct.
    It finds all internal Product SKUs whose category makes them eligible for the PublicProduct's
    Grade, and then creates, updates, or deletes PublicVariation records to match.
    """
    if not public_product or not public_product.grade_object:
        return

    grade = public_product.grade_object

    # 1. Find all eligible internal Product SKUs for this grade.
    eligible_product_ids = {
        p.product_id for p in Product.query.filter(
            Product.category_id.in_([c.category_id for c in grade.available_in_categories])
        ).all()
    }
    
    # 2. Get the manufacturing product IDs of currently linked variations.
    existing_variation_mfg_ids = {v.manufacturing_product_id for v in public_product.variations}
    
    # 3. Determine which variations to add and which to delete.
    ids_to_add = eligible_product_ids - existing_variation_mfg_ids
    ids_to_delete = existing_variation_mfg_ids - eligible_product_ids

    # 4. Perform the database operations.
    
    if ids_to_delete:
        PublicVariation.query.filter(
            PublicVariation.public_product_id == public_product.id,
            PublicVariation.manufacturing_product_id.in_(ids_to_delete)
        ).delete(synchronize_session=False)

    # Now, handle additions with the correct hashing logic.
    newly_created_variations = []
    for product_id_to_add in ids_to_add:
        # We don't need to query for the manufacturing_product object here.
        new_variation = PublicVariation(
            public_product_id=public_product.id,
            manufacturing_product_id=product_id_to_add
        )
        db.session.add(new_variation)
        newly_created_variations.append(new_variation)

    # 5. Flush. This is necessary before we can generate a hash based on those IDs.
    if newly_created_variations:
        db.session.flush()

    # 6. Now that the variations have IDs, generate and assign the stable hash.
    for variation in newly_created_variations:
        variation.isi_variation_id = build_stable_variation_hash(variation)

    # The calling route is responsible for the final db.session.commit()