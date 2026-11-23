# app/utility/attribute_logic.py

from app.products.models import SpecificationDefinition, ProductUnit, ProductUnitAttribute
from app.definitions.models import Attribute
from app.extensions import db
from .specification_logic import get_definitions_for_categories


def get_unlinked_attributes(category_id: int):
    """
    Returns a list of all Global Attributes that are NOT already used by a
    synced specification in the given category's inheritance chain.
    
    This is used to populate the "Sync to Attribute" dropdown to prevent
    creating duplicate synced specs (e.g., two "Color" specs in the same chain).
    """
    if not category_id:
        return []

    # 1. Find all specifications that apply to this category (own and inherited).
    applicable_definitions = get_definitions_for_categories([category_id])

    # 2. Get the IDs of all attributes that are already linked to one of these specs.
    linked_attribute_ids = {
        spec.attribute_id for spec in applicable_definitions if spec.attribute_id
    }

    # 3. Return all attributes whose IDs are NOT in the list of already-linked IDs.
    return Attribute.query.filter(
        Attribute.attribute_id.notin_(linked_attribute_ids)
    ).order_by(Attribute.name).all()


def find_matching_attribute(spec_def: SpecificationDefinition) -> Attribute | None:
    """
    Finds a single global Attribute that is an exact match for a given
    SpecificationDefinition based on name and all data type fields.

    Args:
        spec_def: The SpecificationDefinition object to find a match for.

    Returns:
        The matching Attribute object if exactly one is found, otherwise None.
    """
    query = Attribute.query.filter(
        Attribute.name == spec_def.name,
        Attribute.data_type_id == spec_def.data_type_id,
    )

    matches = query.all()

    if len(matches) == 1:
        return matches[0]
    
    return None


def save_unit_attribute_values(unit: ProductUnit, form_data):
    """
    Processes and saves all unlinked global attribute values for a specific ProductUnit,
    reading directly from request.form data.

    Args:
        unit: The ProductUnit object being modified.
        form_data: The `request.form` object from the route.
    """
    all_attributes = Attribute.query.all()
    
    for attribute in all_attributes:
        input_name = f'attr_{attribute.attribute_id}'
        submitted_value = form_data.get(input_name)

        existing_attr_value = ProductUnitAttribute.query.filter_by(
            unit_id=unit.unit_id,
            attribute_id=attribute.attribute_id
        ).first()

        
        if submitted_value and submitted_value.strip():
            if existing_attr_value:
                existing_attr_value.value = submitted_value.strip()
            else:
                new_pa = ProductUnitAttribute(
                    unit=unit,
                    attribute=attribute,
                    value=submitted_value.strip()
                )
                db.session.add(new_pa)
        elif existing_attr_value:
            db.session.delete(existing_attr_value)