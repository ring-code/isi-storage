# app/utility/specification_logic.py
import json
import copy
from app.products.models import Product, Category, ProductUnit, SpecificationValue, SpecificationDefinition
from app.definitions.models import ProductAttribute
from app.extensions import db
from app.utility.validation_logic import validate_value_by_datatype
from sqlalchemy.orm import joinedload


def get_definitions_for_categories(category_ids: list) -> list:
    """
    Fetches all applicable SpecificationDefinitions for a list of categories,
    correctly handling inheritance, overrides, and eager-loading to prevent errors.
    """
    if not category_ids:
        return []

    # --- STAGE 1: Gather all category IDs in the complete hierarchy ---
    all_category_ids_in_hierarchy = set()
    queue = list(Category.query.filter(Category.category_id.in_(category_ids)).all())
    
    while queue:
        category = queue.pop(0)
        if category and category.category_id not in all_category_ids_in_hierarchy:
            all_category_ids_in_hierarchy.add(category.category_id)
            if category.parent:
                queue.append(category.parent)

    # --- STAGE 2: Run one single, fully eager-loaded query ---
    # This fetches all categories in the hierarchy with their definitions AND the
    # attributes/option_lists on those definitions pre-loaded.
    all_categories_in_hierarchy = Category.query.options(
        joinedload(Category.specification_definitions).options(
            joinedload(SpecificationDefinition.attribute),
            joinedload(SpecificationDefinition.option_list)
        ),
        joinedload(Category.overridden_specifications), # Eager load for blocked_def_ids
        joinedload(Category.rule_overrides)           # Eager load for effective_override
    ).filter(
        Category.category_id.in_(all_category_ids_in_hierarchy)
    ).all()
    
    # Create a map for quick access
    category_map = {cat.category_id: cat for cat in all_categories_in_hierarchy}

    # --- STAGE 3: Process the safe, fully-loaded data ---
    final_definitions = {}
    
    # We only need to iterate through our initial set of categories
    for start_category_id in category_ids:
        start_category = category_map.get(start_category_id)
        if not start_category: continue

        blocked_def_ids = {spec_def.id for spec_def in start_category.overridden_specifications}
        
        current_cat = start_category
        while current_cat:
            for original_definition in current_cat.specification_definitions:
                if original_definition.name not in final_definitions and original_definition.id not in blocked_def_ids:
                    if current_cat == start_category or original_definition.is_inheritable:
                        
                        definition = copy.copy(original_definition)

                        temp_cat_for_override = start_category
                        effective_override = None
                        while temp_cat_for_override and temp_cat_for_override.category_id != definition.category_id:
                            override = next((o for o in temp_cat_for_override.rule_overrides if o.definition_id == definition.id), None)
                            if override:
                                effective_override = override
                                break
                            temp_cat_for_override = category_map.get(temp_cat_for_override.parent_id)

                        if effective_override:
                            definition.requires_implementation = effective_override.requires_implementation if effective_override.requires_implementation is not None else definition.requires_implementation
                            definition.forbid_override = effective_override.forbid_override if effective_override.forbid_override is not None else definition.forbid_override
                        
                        final_definitions[definition.name] = definition
            
            # Use our pre-fetched map to walk up the tree safely
            current_cat = category_map.get(current_cat.parent_id)
            
    return sorted(final_definitions.values(), key=lambda d: d.name)



def get_all_values_for_product(product: Product) -> dict:
    """
    For a given product, gets a dictionary of its final, applicable spec
    values {definition_name: value}, combining its own overrides with 
    category defaults. An override on the product always wins.
    """
    if not product.category:
        return {}

    # 1. Get all definitions that apply to the product's category
    applicable_definitions = get_definitions_for_categories(
        [product.category.category_id]
    )
    
    # 2. Get the product's own specific overrides (the "locked" values).
    # This is a dictionary of {definition_name: value}.
    product_overrides = {val.definition.name: val.value for val in product.specification_values}
    
    # 3. Get the default values from the category hierarchy.
    category_defaults = get_default_values_for_categories(
        [product.category.category_id]
    )

    final_values = {}
    for definition in applicable_definitions:
        def_name = definition.name
        
        # The final value is the product's own override, if it exists.
        # Otherwise, fall back to the category's default.
        if def_name in product_overrides:
            final_values[def_name] = product_overrides[def_name]
        else:
            final_values[def_name] = category_defaults.get(def_name)

    return final_values


def get_default_values_for_categories(category_ids: list) -> dict:
    """
    Gets a dictionary of {definition_name: value} for all default values
    set on a list of categories and their parents. The most specific value wins.
    """
    if not category_ids:
        return {}

    final_values = {} # Use definition name as key to handle overrides
    categories = Category.query.filter(Category.category_id.in_(category_ids)).all()

    for category in categories:
        current_cat = category
        while current_cat:
            for spec_value in current_cat.specification_values:
                def_name = spec_value.definition.name
                if def_name not in final_values:
                    final_values[def_name] = spec_value.value
            current_cat = current_cat.parent
            
    return final_values



def sync_specs_to_attributes(product: Product):
    """
    Reads a product's final spec values and
    syncs them to global attributes where a link is defined.
    """
    if not product.category:
        return

    # These helpers correctly get the final values, whether they are strings or JSON strings
    final_values = get_all_values_for_product(product)
    all_definitions = get_definitions_for_categories([product.category.category_id])

    for definition in all_definitions:
        if definition.attribute:
            target_attribute = definition.attribute
            final_value = final_values.get(definition.name)
            
            existing_pa = ProductAttribute.query.filter_by(
                product_id=product.product_id,
                attribute_id=target_attribute.attribute_id
            ).first()

            # The value could be a plain string, a JSON string, or None
            if final_value is not None:
                if existing_pa:
                    existing_pa.value = str(final_value) # Ensure value is a string for DB
                else:
                    new_pa = ProductAttribute(
                        product=product,
                        attribute=target_attribute,
                        value=str(final_value) # Ensure value is a string for DB
                    )
                    db.session.add(new_pa)
            elif existing_pa:
                # If there's NO final value but a link exists, delete it
                db.session.delete(existing_pa)



def category_tree_has_products(category: Category) -> bool:
    """
    Recursively checks if a given category OR any of its descendants
    has any products assigned to it. Returns True if products are found,
    otherwise False.
    """
    # 1. Check the category itself for any associated products.
    # We use .first() because we only care if at least one exists.
    if category.products.first():
        return True

    # recursive check for children
    for child in category.children:
        if category_tree_has_products(child):
            return True
            
    # nothing found
    return False
  

def get_final_spec_values_for_unit(unit: ProductUnit) -> dict:
    """
    Gets the final, effective specification values for a single ProductUnit,
    following the override hierarchy: Unit > Product > Category.
    """
    # 1. Get all definitions that apply to this unit's blueprint (product)
    applicable_definitions = get_definitions_for_categories([unit.product.category_id])
    
    # 2. Get values from all three levels
    unit_values = {val.definition.name: val.value for val in unit.specification_values}
    product_values = {val.definition.name: val.value for val in unit.product.specification_values}
    category_values = get_default_values_for_categories([unit.product.category_id])
    
    final_values = {}
    for definition in applicable_definitions:
        # Apply the Chain of Command
        final_values[definition.name] = (
            unit_values.get(definition.name) or          # Level 1: Unit Override
            product_values.get(definition.name) or       # Level 2: SKU Override
            category_values.get(definition.name)         # Level 3: Category Default
        )
        
    return final_values
    

def save_specification_value(spec_def, form_data, is_from_option_list: bool, category_id: int = None) -> str | None:
    """
    Validates (if needed) and saves a default SpecificationValue for a given
    specification and category context.

    Args:
        spec_def: The SpecificationDefinition object.
        form_data: The `request.form` object from the route.
        is_from_option_list: A boolean indicating the data source.
        category_id (optional): The ID of the category to save the value on.
                                Defaults to the spec_def's own category.

    Returns:
        An error message string if validation fails, otherwise None.
    """
    # If a specific category_id isn't provided for an override,
    # default to the category where the spec is defined.
    if category_id is None:
        category_id = spec_def.category_id

    expect_multiple = False
    if is_from_option_list:
        option_list = spec_def.option_list or (spec_def.attribute and spec_def.attribute.option_list)
        if option_list:
            expect_multiple = option_list.allow_multiple_selections

    if expect_multiple:
        submitted_values = form_data.getlist('default_value_ui')
    else:
        single_value = form_data.get('default_value_ui')
        submitted_values = [single_value] if single_value is not None else []

    if not is_from_option_list:
        value_to_validate = submitted_values[0] if submitted_values else ""
        if value_to_validate.strip():
            is_valid, error = validate_value_by_datatype(value_to_validate, spec_def.data_type)
            if not is_valid:
                return error

    final_value_to_save = None
    if submitted_values:
        cleaned_values = [v for v in submitted_values if v and v.strip()]
        if cleaned_values:
            if expect_multiple:
                final_value_to_save = json.dumps(cleaned_values)
            else:
                final_value_to_save = cleaned_values[0]

    existing_value_record = SpecificationValue.query.filter_by(
        definition_id=spec_def.id,
        category_id=category_id # Uses either the passed ID or the default
    ).first()

    if final_value_to_save:
        if existing_value_record:
            existing_value_record.value = final_value_to_save
        else:
            new_value = SpecificationValue(
                definition=spec_def,
                category_id=category_id, 
                value=final_value_to_save
            )
            db.session.add(new_value)
    elif existing_value_record:
        db.session.delete(existing_value_record)
        
    return None # Success


def save_unit_spec_value(unit, spec_def, form_data) -> str | None:
    """
    Validates (if needed) and saves a SpecificationValue for a specific ProductUnit.
    Reads directly from request.form data.

    Args:
        unit: The ProductUnit object.
        spec_def: The SpecificationDefinition object.
        form_data: The `request.form` object from the route.

    Returns:
        An error message string if validation fails, otherwise None.
    """
    spec_def = db.session.merge(spec_def)
    is_from_option_list = bool(spec_def.option_list or (spec_def.attribute and spec_def.attribute.option_list))
    
    expect_multiple = False
    if is_from_option_list:
        option_list = spec_def.option_list or (spec_def.attribute and spec_def.attribute.option_list)
        if option_list:
            expect_multiple = option_list.allow_multiple_selections

    # Get the submitted value(s) from the input named `spec_{spec_def.id}`
    input_name = f'spec_{spec_def.id}'
    if expect_multiple:
        submitted_values = form_data.getlist(input_name)
    else:
        single_value = form_data.get(input_name)
        submitted_values = [single_value] if single_value is not None else []

    # Validate the value(s) ONLY if it's a simple type
    if not is_from_option_list:
        value_to_validate = submitted_values[0] if submitted_values else ""
        if value_to_validate.strip():
            is_valid, error = validate_value_by_datatype(value_to_validate, spec_def.data_type)
            if not is_valid:
                return error

    # Format the value for the database
    final_value_to_save = None
    if submitted_values:
        cleaned_values = [v for v in submitted_values if v and v.strip()]
        if cleaned_values:
            final_value_to_save = json.dumps(cleaned_values) if expect_multiple else cleaned_values[0]

    # Find the existing record for this specific unit
    existing_value_record = SpecificationValue.query.filter_by(
        definition_id=spec_def.id,
        unit_id=unit.unit_id
    ).first()

    # Perform the final DB operation
    if final_value_to_save:
        if existing_value_record:
            existing_value_record.value = final_value_to_save
        else:
            new_value = SpecificationValue(
                definition=spec_def,
                unit=unit, # Link directly to the unit object
                value=final_value_to_save
            )
            db.session.add(new_value)
    elif existing_value_record:
        db.session.delete(existing_value_record)
        
    return None # Success


def is_product_sku_concrete(product: Product) -> bool:
    """
    Checks if a single Product SKU is fully concrete by ensuring all its
    specifications have a final, non-empty value.
    """
    # Use your existing powerful helper to get all final values
    final_values = get_all_values_for_product(product)
    
    # Get all applicable definitions to know what to check against
    applicable_definitions = get_definitions_for_categories([product.category.category_id])

    # If the number of final values is less than the number of definitions,
    # it's inherently abstract.
    if len(final_values) < len(applicable_definitions):
        return False

    # Check if any of the values are None or an empty string
    if any(v is None or str(v).strip() == '' for v in final_values.values()):
        return False
        
    return True


def get_concrete_skus():
    """
    Returns a list of all Product SKUs that are fully concrete and can be
    used for batch creation.
    """
    all_products = Product.query.order_by(Product.name).all()
    
    # Filter the list, keeping only the products that pass the check
    concrete_products = [p for p in all_products if is_product_sku_concrete(p)]
    
    return concrete_products