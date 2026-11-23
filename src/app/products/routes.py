# src/app/products/routes.py
from flask import Blueprint, logging, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
from werkzeug.datastructures import MultiDict

import json
import logging
import os
from .forms import CategoryForm, ProductForm, CreateSingleUnitForm, BatchCreateUnitForm, SpecificationForm, EditUnitForm
from .models import ProductPhoto, Category, Product, ProductUnit, SpecificationValue,  SpecificationDefinition, SpecificationRuleOverride
from app.definitions.models import DataType, OptionList, Attribute
from app.sales.models import ShopCategory, PublicProduct, RentalGrade, SaleGrade
from app.inventory.models import Damage
from app.extensions import db
from app.inventory.forms import AssetTagActionForm, DamageForm
from app.utility.form_helpers import get_all_shop_categories
from app.permissions import role_required
from app.utility.specification_logic import get_definitions_for_categories, sync_specs_to_attributes, get_default_values_for_categories, category_tree_has_products, save_specification_value, save_unit_spec_value, get_all_values_for_product, is_product_sku_concrete
from app.utility.attribute_logic import find_matching_attribute, save_unit_attribute_values, get_unlinked_attributes
from app.utility.shop_category_logic import save_unit_shop_categories, get_hierarchical_shop_categories, get_hierarchical_shop_category_label
from app.utility.public_product_logic import get_units_for_public_product

# Blueprint definitions
main = Blueprint('main', __name__)
api_bp = Blueprint('api', __name__, url_prefix='/api')



@main.route('/')
def home():
    return render_template('index.html')


@main.route('/internal/products')
@login_required
@role_required('admin', 'manager')
def view_products():
    """
    The main hub page for viewing all Product SKUs.
    """   
    all_products = Product.query.options(
        joinedload(Product.category),
        joinedload(Product.photos)
    ).order_by(Product.name).all()

    return render_template('products/view_products.html', products=all_products)


@main.route('/manage_product/', defaults={'product_id': None}, methods=['GET', 'POST'])
@main.route('/manage_product/<int:product_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'manager')
def manage_product(product_id):
    """
    A single route for both CREATING and EDITING a Product SKU.
    """
    if product_id:
        product = Product.query.get_or_404(product_id)
        form = ProductForm(obj=product)
        form.id.data = product.product_id
    else:
        product = None
        form = ProductForm()

    form.shop_categories.choices = [
        (cat.id, get_hierarchical_shop_category_label(cat)) 
        for cat in get_hierarchical_shop_categories()
    ]

    if form.validate_on_submit():
        if product:
            selected_category = product.category
        else:
            selected_category = form.category.data
        
        if not product:
            product = Product(created_by=current_user.id)
            db.session.add(product)
        
        # --- Update basic product fields ---
        product.name = form.name.data
        product.description_txt = form.description_txt.data
        product.category = selected_category
        prefix_from_form = form.serial_number_prefix.data
        product.serial_number_prefix = prefix_from_form.strip().rstrip('-') if prefix_from_form else None
        product.damage_template = form.damage_template.data
        product.standard_production_cost = form.standard_production_cost.data

        selected_shop_cat_ids = form.shop_categories.data
        if selected_shop_cat_ids:
            product.shop_categories = ShopCategory.query.filter(
                ShopCategory.id.in_(selected_shop_cat_ids)
            ).all()
        else:
            product.shop_categories = []

        # SpecificationValues
        spec_definitions = get_definitions_for_categories([selected_category.category_id])
        
        for definition in spec_definitions:
            if definition.forbid_override:
                continue

            input_name = f'spec_{definition.id}'
            lock_state = request.form.get(f'spec_lock_{definition.id}', 'unlocked') # Default to unlocked

            # If the user wants to inherit (unlocked), we must DELETE any existing override.
            if lock_state == 'unlocked':
                SpecificationValue.query.filter_by(
                    product_id=product.product_id, 
                    definition_id=definition.id
                ).delete()
                continue # Move to the next definition


            effective_option_list = definition.option_list or (definition.attribute and definition.attribute.option_list)
            is_multi_select = effective_option_list and effective_option_list.allow_multiple_selections
            
            if is_multi_select:
                submitted_values = request.form.getlist(input_name)
                final_value_to_save = json.dumps(submitted_values) if submitted_values else None
            else:
                submitted_value = request.form.get(input_name)
                final_value_to_save = submitted_value.strip() if submitted_value and submitted_value.strip() else None

            existing_spec_value = SpecificationValue.query.filter_by(product_id=product.product_id, definition_id=definition.id).first()

            if final_value_to_save:
                if existing_spec_value:
                    existing_spec_value.value = final_value_to_save
                else:
                    new_spec_value = SpecificationValue(product=product, definition=definition, value=final_value_to_save)
                    db.session.add(new_spec_value)
            elif existing_spec_value:
                db.session.delete(existing_spec_value)

        # Sync spec values to their linked attributes 
        sync_specs_to_attributes(product)

            
        # Handle photo uploads.
        if form.photos.data:
            for photo_file in form.photos.data:
                if photo_file and photo_file.filename != '':
                        filename = secure_filename(photo_file.filename)
                        photo_path = os.path.join('app/static/photos/', filename)
                        photo_file.save(photo_path)
                        new_photo = ProductPhoto(product_id=product.product_id, photo_filename=filename)
                        db.session.add(new_photo)
            
        db.session.commit()
        flash(f"Product SKU '{product.name}' saved successfully.", "success")
        return redirect(url_for('main.view_products', product_id=product.product_id))

    if form.errors:
            flash(f"Failed to create product. Please check errors: {form.errors}", "danger")

    if request.method == 'GET' and product:
        form.shop_categories.data = [cat.id for cat in product.shop_categories]

    # --- Prepare data for the template ---
    category_details_url_template = url_for('api.get_category_details', category_id='CATEGORY_ID')
    
    # Data for re-rendering the edit form with its current values
    spec_values = {}
    if product:
        for sv in product.specification_values:
            spec_values[sv.definition_id] = sv.value


    return render_template(
        'products/manage_product.html', 
        form=form,
        product=product,
        category_details_url_template=category_details_url_template,
        spec_values=spec_values,
    )


@api_bp.route('/category-details/<category_id>')
@login_required
def get_category_details(category_id):
    """
    API endpoint to fetch all data needed to dynamically build the product form.
    """
    try:
        cat_id = int(category_id)
    except ValueError:
        return jsonify({'error': 'Invalid category ID'}), 404
    
    category = Category.query.get_or_404(cat_id)

    # --- 1. Get Specification Definitions and their effective rules/values ---
    
    # Get all definitions applicable to this category and its parents
    definitions = get_definitions_for_categories([category.category_id])
    
    # Get all default values from this category and its parents
    default_values = get_default_values_for_categories([category.category_id])
    
    spec_data = []
    for spec_def in definitions:
        # The key for default_values is the definition name.
        default_value = default_values.get(spec_def.name, '')

        # We need to check if the current category has a rule_override for this spec
        rule_override = SpecificationRuleOverride.query.filter_by(
            category_id=category.category_id, 
            definition_id=spec_def.id
        ).first()

        # The effective rule is the override if it exists, otherwise the base definition's rule.
        is_final = rule_override.forbid_override if (rule_override and rule_override.forbid_override is not None) else spec_def.forbid_override
        
        # Determine the final `is_abstract` 
        is_abstract_rule = rule_override.requires_implementation if (rule_override and rule_override.requires_implementation is not None) else spec_def.requires_implementation
        # A spec is considered "abstract" in this context if the rule requires implementation AND there is no default value provided yet.
        is_abstract = is_abstract_rule and not default_value

        # Get the effective OptionList for this spec
        effective_option_list = spec_def.option_list or (spec_def.attribute.option_list if spec_def.attribute else None)
        
        spec_data.append({
            'id': spec_def.id,
            'name': spec_def.name,
            'default_value': default_value, 
            'data_type': spec_def.data_type.to_json(),
            'option_list': effective_option_list.to_json() if effective_option_list else None,
            'is_final': is_final,
            'is_abstract': is_abstract 
        })

   
    # --- 2. Get Shop Categories ---
    shop_categories_query = get_all_shop_categories()
    shop_cat_data = [{'id': cat.id, 'name': cat.name, 'parent_id': cat.parent_id} for cat in shop_categories_query]
    
    return jsonify({
        'category_name': category.name,
        'specifications': spec_data,
        'shop_categories': shop_cat_data
    })


@main.route('/delete_product/<int:product_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)

    if product.product_units.first():
        flash(f"Cannot delete Product SKU '{product.name}'. It is still in use by one or more Product Units. Please delete or re-assign those units first.", "danger")
        return redirect(url_for('main.view_products'))

    db.session.delete(product)
    db.session.commit()
    flash(f"Product '{product.name}' deleted successfully!", 'success')
    return redirect(url_for('main.view_products'))


@main.route('/internal/categories', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_categories():
    form = CategoryForm()
    edit_cat_id = request.args.get('edit_cat', type=int)
    edit_category = Category.query.get_or_404(edit_cat_id) if edit_cat_id else None

    if form.validate_on_submit():
        if edit_category:
            edit_category.name = form.name.data
            flash(f"Category '{edit_category.name}' updated successfully.", "success")
        else: # Create
            new_category = Category(
                name=form.name.data,
                parent_id=form.parent_id.data.category_id if form.parent_id.data else None
            )
            db.session.add(new_category)
            flash(f"Category '{new_category.name}' created. You may now fulfill any inherited contracts.", "success")
        
        db.session.commit()
        return redirect(url_for('main.manage_categories'))

    if request.method == 'GET' and edit_category:
        form.process(obj=edit_category)

    # --- DATA FOR TEMPLATE ---
    all_categories = Category.query.filter(Category.parent_id.is_(None)).order_by(Category.name).all()
    
    return render_template(
        'categories/manage_categories.html',
        all_categories=all_categories,
        get_definitions_for_categories=get_definitions_for_categories,
        get_default_values_for_categories=get_default_values_for_categories,
        form=form,
        edit_category=edit_category
    )


@api_bp.route('/categories/<int:category_id>/rename', methods=['POST'])
@login_required
@role_required('admin')
def rename_category(category_id):
    category = Category.query.get_or_404(category_id)
    new_name = request.json.get('name', '').strip()

    if not new_name:
        return jsonify({'success': False, 'message': 'Name cannot be empty.'}), 400

    # Check for uniqueness
    existing = Category.query.filter(Category.name == new_name, Category.category_id != category_id).first()
    if existing:
        return jsonify({'success': False, 'message': f"A category with the name '{new_name}' already exists."}), 409 # Conflict

    category.name = new_name
    db.session.commit()
    return jsonify({'success': True, 'newName': new_name})


@main.route('/delete_category/<int:category_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_category(category_id):
    category = Category.query.get_or_404(category_id)

    if category_tree_has_products(category): 
        flash(f"Cannot delete Category '{category.name}'. It, or one of its sub-categories, is still assigned to one or more products.", "danger")
        return redirect(url_for('main.manage_categories'))

    db.session.delete(category)
    db.session.commit()
    
    flash(f"Category '{category.name}' and all its children have been deleted.", 'success')
    return redirect(url_for('main.manage_categories'))


@main.route('/internal/categories/<int:category_id>/spec/', defaults={'spec_def_id': None}, methods=['GET', 'POST'])
@main.route('/internal/categories/<int:category_id>/spec/<int:spec_def_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_specification(category_id, spec_def_id):
    """
    A single, unified route for creating specs, editing base definitions,
    and managing overrides on child categories.
    """
    category = Category.query.get_or_404(category_id)
    spec_def = SpecificationDefinition.query.get_or_404(spec_def_id) if spec_def_id else None

    # --- Determine Context ---
    is_edit_mode = bool(spec_def)
    is_base_edit = is_edit_mode and (spec_def.category_id == category.category_id)

    # --- Initialize the Unified Form with Context ---
    form = SpecificationForm(category=category, spec_def=spec_def)
    form.linked_attribute.query = get_unlinked_attributes(category_id=category_id)
    form.category_id.data = category_id
    if is_edit_mode:
        form.id.data = spec_def_id

    # --- Handle Form Submission ---
    if request.method == 'POST':
        # If this is a base edit on a category with children, the inheritance
        # checkboxes are disabled and won't be in the form submission.
        # We must manually re-populate them from the database object
        # BEFORE validation to prevent incorrect validation failures.
        if is_base_edit and category.children:
            form.is_inheritable.data = spec_def.is_inheritable
            form.requires_implementation.data = spec_def.requires_implementation
            form.forbid_override.data = spec_def.forbid_override

        if form.validate_on_submit():
            try:
                # --- CREATE LOGIC ---
                if not is_edit_mode:
                    is_creating_synced = bool(form.linked_attribute.data)
                    if is_creating_synced:
                        linked_attr = form.linked_attribute.data
                        new_spec = SpecificationDefinition(name=linked_attr.name, category=category, attribute=linked_attr, data_type=linked_attr.data_type, option_list=linked_attr.option_list)
                    else: # Creating Unsynced
                        option_list = form.option_list.data
                        effective_data_type = option_list.item_data_type if option_list else form.data_type.data
                        new_spec = SpecificationDefinition(name=form.name.data, category=category, data_type=effective_data_type, option_list=option_list)
                    
                    new_spec.is_inheritable = form.is_inheritable.data
                    new_spec.requires_implementation = form.requires_implementation.data
                    new_spec.forbid_override = form.forbid_override.data
                    is_enforced_not_final = new_spec.requires_implementation and not new_spec.forbid_override
                    is_on_definition_level = (new_spec.category_id == category_id)

                    if is_on_definition_level and is_enforced_not_final and request.form.get('default_value_ui'):
                        raise ValueError("A default value cannot be set for a spec that is 'Enforced' but not 'Final'. This is a contract for children to fulfill.")

                    if new_spec.forbid_override and not request.form.get('default_value_ui'):
                        raise ValueError("A Default Value is required when the specification is marked as Final.")

                    db.session.add(new_spec)
                    db.session.flush() 
                    spec_to_process = new_spec

                # --- EDIT LOGIC ---
                else:
                    spec_to_process = spec_def
                    if is_base_edit:
                        # Name is only editable if unsynced. Inheritance rules are handled by the pre-validation step.
                        if not spec_to_process.attribute:
                            spec_to_process.name = form.name.data
                        spec_to_process.is_inheritable = form.is_inheritable.data
                        spec_to_process.requires_implementation = form.requires_implementation.data
                        spec_to_process.forbid_override = form.forbid_override.data
                        is_enforced_not_final = spec_to_process.requires_implementation and not spec_to_process.forbid_override
                        is_on_definition_level = (spec_to_process.category_id == category_id)

                        if is_on_definition_level and is_enforced_not_final and request.form.get('default_value_ui'):
                            raise ValueError("A default value cannot be set for a spec that is 'Enforced' but not 'Final'. This is a contract for children to fulfill.")
                    else: # Creating/editing an override on a child
                        rule_override = SpecificationRuleOverride.query.filter_by(definition_id=spec_def.id, category_id=category.category_id).first()
                        if not rule_override:
                            rule_override = SpecificationRuleOverride(definition=spec_def, category=category)
                            db.session.add(rule_override)
                        rule_override.forbid_override = form.forbid_override.data

                # --- UNIVERSAL: Save the Default Value ---
                is_list = bool(spec_to_process.option_list or (spec_to_process.attribute and spec_to_process.attribute.option_list))
                error_msg = save_specification_value(spec_to_process, request.form, is_list, category.category_id)
                if error_msg:
                    raise ValueError(f"Invalid Default Value: {error_msg}")

                db.session.commit()
                flash(f"Specification '{spec_to_process.name}' saved successfully.", "success")
                return redirect(url_for('main.manage_categories'))

            except ValueError as e:
                db.session.rollback()
                flash(str(e), "danger")
            except IntegrityError as e:
                db.session.rollback()
                logging.error(f"IntegrityError on spec save for category {category_id}: {e}")
                flash("Error saving specification. A value may be a duplicate or invalid.", "danger")
    
    # --- Handle GET Request or Failed POST Validation ---
    if request.method == 'GET' and is_edit_mode:
        source_object = SpecificationRuleOverride.query.filter_by(definition_id=spec_def.id, category_id=category.category_id).first() or spec_def
        form.process(obj=source_object)
        form.name.data = spec_def.name
        
    # --- Prepare Data for Template ---
    current_value = ""
    if is_edit_mode:
        value_record = SpecificationValue.query.filter_by(definition_id=spec_def_id, category_id=category_id).first()
        current_value = value_record.value if value_record else ""

    effective_option_list = None
    effective_data_type = None
    if is_edit_mode:
        effective_option_list = spec_def.option_list or (spec_def.attribute and spec_def.attribute.option_list)
        effective_data_type = effective_option_list.item_data_type if effective_option_list else spec_def.data_type

    attribute_data_map = {}
    if not is_edit_mode:
        unlinked_attributes = get_unlinked_attributes(category_id=category_id)
        for attr in unlinked_attributes:
            attribute_data_map[str(attr.attribute_id)] = {'data_type': attr.data_type.to_json() if attr.data_type else None, 'option_list': attr.option_list.to_json() if attr.option_list else None}
    
    all_data_types = DataType.query.all()
    data_type_map = {str(dt.id): dt.to_json() for dt in all_data_types}
    all_option_lists = OptionList.query.all()
    option_list_map = {str(ol.id): ol.to_json() for ol in all_option_lists}

    return render_template(
        'specifications/manage_specification.html', 
        form=form,
        category=category,
        spec_def=spec_def,
        is_edit_mode=is_edit_mode,
        is_base_edit=is_base_edit,
        current_value=current_value,
        effective_data_type_json=json.dumps(effective_data_type.to_json() if effective_data_type else None),
        effective_option_list_json=json.dumps(effective_option_list.to_json() if effective_option_list else None),
        data_type_map_json=json.dumps(data_type_map),
        option_list_map_json=json.dumps(option_list_map),
        attribute_data_map_json=json.dumps(attribute_data_map)
    )


@main.route('/internal/specs/<int:spec_def_id>/sync', methods=['POST'])
@login_required
@role_required('admin')
def sync_specification(spec_def_id):
    """
    Action to create a link between an unsynced spec and a matching global attribute.
    """
    spec_def = SpecificationDefinition.query.get_or_404(spec_def_id)
    category_id_context = spec_def.category_id
    
    # Use helper to find a match
    matching_attribute = find_matching_attribute(spec_def)

    if matching_attribute:
        spec_def.attribute = matching_attribute
        db.session.commit()
        flash(f"Specification successfully synced with global attribute '{matching_attribute.name}'.", "success")
    else:
        flash("Sync failed: Could not find a unique global attribute with the exact same name and data types. Please go to the Attributes page and create one first.", "danger")

    # Redirect back to the same edit page, which will now render the "synced" view
    return redirect(url_for('main.manage_specification', spec_def_id=spec_def_id, category_id=category_id_context))


@main.route('/internal/specs/<int:spec_def_id>/unlink', methods=['POST'])
@login_required
@role_required('admin')
def unsync_specification(spec_def_id):
    """
    Action to break the link between a spec and its global attribute.
    """
    # CSRF protection is handled by the form in the template
    spec_def = SpecificationDefinition.query.get_or_404(spec_def_id)
    category_id_context = spec_def.category_id

    spec_def.attribute_id = None
    db.session.commit()
    flash(f"Specification '{spec_def.name}' has been unlinked and can now be edited freely.", "info")
    # Redirect back to the same edit page, which will now render the "unsynced" view
    return redirect(url_for('main.manage_specification', spec_def_id=spec_def_id, category_id=category_id_context))


@main.route('/internal/categories/<int:category_id>/manage_spec_value', methods=['POST'])
@login_required
@role_required('admin')
def manage_spec_value(category_id):
    """
    Handles creating, updating, or deleting a SpecificationValue (a default answer)
    for a specific category.
    """
    category = Category.query.get_or_404(category_id)
    definition_id = request.form.get('definition_id', type=int)
    value = request.form.get('value', '').strip()
    
    if not definition_id:
        flash("Missing specification definition context.", "danger")
        return redirect(url_for('main.manage_categories'))

    definition = SpecificationDefinition.query.get(definition_id)
    if not definition:
        flash("Specification Definition not found.", "danger")
        return redirect(url_for('main.manage_categories'))

    # An abstract contract cannot have a value on the same category where it is defined.
    is_own_abstract_def = (definition.category_id == category.category_id and definition.requires_implementation)
    if is_own_abstract_def:
        flash(f"Cannot set a default value for '{definition.name}' on this category because it is defined here as an abstract contract.", "danger")
        return redirect(url_for('main.manage_categories'))

    existing_value = SpecificationValue.query.filter_by(
        category_id=category.category_id,
        definition_id=definition_id
    ).first()

    if 'delete_value' in request.form:
        if existing_value:
            db.session.delete(existing_value)
            db.session.commit()
            flash("Default value has been removed.", "success")
        else:
            flash("No default value to remove.", "warning")
    elif value:
        if existing_value:
            existing_value.value = value
            flash("Default value has been updated.", "success")
        else:
            new_value = SpecificationValue(
                category_id=category.category_id,
                definition_id=definition_id,
                value=value
            )
            db.session.add(new_value)
            flash("Default value has been set.", "success")
        db.session.commit()
    else:
        flash("Value cannot be empty.", "danger")

    return redirect(url_for('main.manage_categories'))


@main.route('/internal/categories/<int:category_id>/hide_spec_def/<int:spec_def_id>', methods=['POST'])
@login_required
@role_required('admin')
def hide_spec_def(category_id, spec_def_id):
    category = Category.query.get_or_404(category_id)
    spec_def_to_hide = SpecificationDefinition.query.get_or_404(spec_def_id)

    # CRITICAL SAFETY CHECK: A required specification cannot be hidden.
    if spec_def_to_hide.requires_implementation:
        flash(f"Cannot hide '{spec_def_to_hide.name}'. Required specifications cannot be hidden.", "danger")
        return redirect(url_for('main.manage_categories'))

    if spec_def_to_hide not in category.overridden_specifications:
        category.overridden_specifications.append(spec_def_to_hide)
        db.session.commit()
        flash(f"Specification '{spec_def_to_hide.name}' is now hidden for category '{category.name}'.", "info")
    
    return redirect(url_for('main.manage_categories'))


@main.route('/internal/categories/<int:category_id>/reset_overrides', methods=['POST'])
@login_required
@role_required('admin')
def reset_spec_overrides(category_id):
    category = Category.query.get_or_404(category_id)
    if category.overridden_specifications:
        category.overridden_specifications.clear()
        db.session.commit()
        flash(f"All hidden specifications have been restored for '{category.name}'.", "success")
    
    return redirect(url_for('main.manage_categories'))


@main.route('/internal/specifications/delete/<int:spec_def_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_specification_definition(spec_def_id):
    """Deletes a SpecificationDefinition, but only if no products are using it."""
    spec_def_to_delete = SpecificationDefinition.query.get_or_404(spec_def_id)
    
    # Find if any SpecificationValue linked to this definition also has a product_id.
    usage_check = SpecificationValue.query.filter(
        SpecificationValue.definition_id == spec_def_id,
        SpecificationValue.product_id.isnot(None) 
    ).first()

    if usage_check:
        flash(
            f"Cannot delete '{spec_def_to_delete.name}'. It is in use by one or more products as an override. "
            "Please remove the value from those products first.", 
            "danger"
        )
    else:
        db.session.delete(spec_def_to_delete)
        db.session.commit()
        flash(f"Specification Definition '{spec_def_to_delete.name}' has been deleted.", "success")
        
    return redirect(url_for('main.manage_categories'))


@main.route('/internal/categories/<int:category_id>/set-spec-inline/<int:definition_id>', methods=['POST'])
@login_required
@role_required('admin')
def set_spec_inline(category_id, definition_id):
    """
    Handles the submission from the inline value-editing form in the category table.
    """
    category = Category.query.get_or_404(category_id)
    definition = SpecificationDefinition.query.get_or_404(definition_id)

    current_value = get_default_values_for_categories([category_id]).get(definition.name)

    is_enforced_not_final = definition.requires_implementation and not definition.forbid_override
    is_on_definition_level = (definition.category_id == category_id)
    
    if is_on_definition_level and is_enforced_not_final:
        flash("A base default value cannot be set for a spec that is 'Enforced' but not 'Final'. This is a contract for children to fulfill.", "danger")
        return redirect(url_for('main.manage_categories', _anchor=f"category-name-{category_id}"))

    # The lock applies if all three conditions are met:
    if category.children and definition.requires_implementation and not current_value:
        flash("Cannot set a base default value for an Enforced spec on a category that already has children.", "danger")
        return redirect(url_for('main.manage_categories', _anchor=f"category-name-{category_id}"))


    form_data = MultiDict([('default_value_ui', v) for v in request.form.getlist('value')])

    is_list = bool(definition.option_list or (definition.attribute and definition.attribute.option_list))
    error = save_specification_value(definition, form_data, is_list, category_id)
    
    if error:
        flash(f"Error setting value for '{definition.name}': {error}", "danger")
    else:
        db.session.commit()
        flash(f"Default value for '{definition.name}' updated.", "success")

    # Redirect back to the main page. The anchor will try to jump to the right category.
    return redirect(url_for('main.manage_categories', _anchor=f"category-name-{category_id}"))


@api_bp.route('/categories/<int:category_id>/finalize-spec/<int:definition_id>', methods=['POST'])
@login_required
@role_required('admin')
def finalize_spec(category_id, definition_id):
    """
    Sets a specification as "Final" for a given category context.
    It requires that a default value already exists for this context.
    """
    category = Category.query.get_or_404(category_id)
    definition = SpecificationDefinition.query.get_or_404(definition_id)
    
    # 1. Check if a value already exists for this spec in this category's context.
    existing_value = SpecificationValue.query.filter_by(
        definition_id=definition_id,
        category_id=category_id
    ).first()

    if not existing_value or not existing_value.value.strip():
        return jsonify({'success': False, 'message': 'Cannot finalize a specification that has no default value set.'}), 400

    is_base_edit = (definition.category_id == category_id)

    try:
        # 2. Set the "Final" Rule (value is already saved)
        if is_base_edit:
            definition.requires_implementation = True
            definition.forbid_override = True
        else:
            rule_override = SpecificationRuleOverride.query.filter_by(definition_id=definition_id, category_id=category_id).first()
            if not rule_override:
                rule_override = SpecificationRuleOverride(definition=definition, category=category)
                db.session.add(rule_override)
            rule_override.forbid_override = True

        db.session.commit()
        return jsonify({'success': True, 'message': f"Specification '{definition.name}' has been finalized."})

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error finalizing spec {definition_id}: {e}")
        return jsonify({'success': False, 'message': 'An unexpected server error occurred.'}), 500


@api_bp.route('/categories/<int:category_id>/unfinalize-spec/<int:definition_id>', methods=['POST'])
@login_required
@role_required('admin')
def unfinalize_spec(category_id, definition_id):
    """
    Removes the "Final" rule from a specification for a given category context,
    reverting it to "Enforced (Overridable)".
    """
    category = Category.query.get_or_404(category_id)
    definition = SpecificationDefinition.query.get_or_404(definition_id)
    is_base_edit = (definition.category_id == category_id)

    try:
        if is_base_edit:
            # On the base definition, just flip the flag.
            # The value remains, but is now editable.
            definition.forbid_override = False
        else:
            # On a child override, we find the rule and set its forbid_override to False.
            # This makes it revert to inheriting the rule from its parent again.
            rule_override = SpecificationRuleOverride.query.filter_by(
                definition_id=definition_id,
                category_id=category_id
            ).first()
            if rule_override:
                rule_override.forbid_override = False
        
        db.session.commit()
        return jsonify({'success': True, 'message': f"Specification '{definition.name}' is no longer final."})

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error un-finalizing spec {definition_id} for category {category_id}: {e}")
        return jsonify({'success': False, 'message': 'An unexpected error occurred.'}), 500


@main.route('/internal/units/<int:unit_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'manager', 'user')
def edit_unit(unit_id):
    unit = ProductUnit.query.options(
        joinedload(ProductUnit.product).joinedload(Product.category),
        joinedload(ProductUnit.rental_grade), 
        joinedload(ProductUnit.sale_grade),
        joinedload(ProductUnit.space),
        joinedload(ProductUnit.product).joinedload(Product.damage_template),
        joinedload(ProductUnit.damages)
    ).get_or_404(unit_id)

    damage_form = DamageForm() # For the damage modal/form

    if request.method == 'POST':
        # --- Handle Main Details Form Submission ---
        if 'submit_main_details' in request.form:
            # We need to re-instantiate the form with the POST data
            form = EditUnitForm(request.form, product=unit.product)
            if form.validate_on_submit():
                # Get the old and new grade IDs before saving
                old_rental_id = unit.rental_grade_id
                old_sale_id = unit.sale_grade_id
                # Update the unit object
                unit.condition = form.condition.data
                unit.space = form.space.data
                unit.actual_production_cost = form.actual_production_cost.data
                unit.description = form.description.data
                unit.rental_grade = form.rental_grade_id.data
                unit.sale_grade = form.sale_grade_id.data
                
                # Save any specification overrides submitted with the form
                spec_definitions = get_definitions_for_categories([unit.product.category_id])
                for definition in spec_definitions:
                    # The lock state tells us if an override should be created/deleted
                    lock_state = request.form.get(f'spec_lock_{definition.id}')
                    if lock_state == 'unlocked':
                        SpecificationValue.query.filter_by(unit_id=unit.unit_id, definition_id=definition.id).delete()
                    elif lock_state == 'locked':
                        error = save_unit_spec_value(unit, definition, request.form)
                        if error:
                            flash(f"Invalid value for '{definition.name}': {error}", "danger")

                save_unit_attribute_values(unit, request.form)

                # Find all PublicProducts linked to the old OR new grade
                affected_sp_ids = set()
                if old_rental_id:
                    affected_sp_ids.update([sp.id for sp in PublicProduct.query.filter_by(grade_type='rental_grade', grade_id=old_rental_id).all()])
                if old_sale_id:
                    affected_sp_ids.update([sp.id for sp in PublicProduct.query.filter_by(grade_type='sale_grade', grade_id=old_sale_id).all()])
                if unit.rental_grade_id:
                    affected_sp_ids.update([sp.id for sp in PublicProduct.query.filter_by(grade_type='rental_grade', grade_id=unit.rental_grade_id).all()])
                if unit.sale_grade_id:
                    affected_sp_ids.update([sp.id for sp in PublicProduct.query.filter_by(grade_type='sale_grade', grade_id=unit.sale_grade_id).all()])
                    

                db.session.commit()
                flash("Unit updated successfully. Related sales products have been refreshed.", "success")
                
                db.session.commit()
                flash("Unit core details updated successfully.", "success")
                return redirect(url_for('main.edit_unit', unit_id=unit.unit_id))
        
        # --- Handle Damage Form Submission ---
        elif 'submit_damage' in request.form:
            damage_form = DamageForm(request.form)
            if damage_form.validate_on_submit():
                new_damage = Damage(
                    product_unit=unit,
                    description=damage_form.description.data,
                    severity=damage_form.severity.data,
                    x_coordinate=damage_form.x_coordinate.data or None,
                    y_coordinate=damage_form.y_coordinate.data or None
                )
                unit.damage_count = unit.damage_count + 1 # Manually increment
                db.session.add(new_damage)
                db.session.commit()
                flash("Damage report added successfully.", "success")
                return redirect(url_for('main.edit_unit', unit_id=unit.unit_id))
            
    # Instantiate the form, populating it from the `unit` object
    form = EditUnitForm(obj=unit, product=unit.product)
    action_form = AssetTagActionForm()
    
    # Manually set the .data for the QuerySelectFields to be the full Objects.
    form.rental_grade_id.data = unit.rental_grade
    form.sale_grade_id.data = unit.sale_grade

    # --- Prepare Data for GET request (or failed POST) ---
    product_details_url = url_for('api.get_product_details', product_id=unit.product_id)
    
    # Get this unit's specific spec and attribute values to pass to the JS
    unit_spec_values = {val.definition_id: val.value for val in unit.specification_values}
    unit_attr_values = {val.attribute_id: val.value for val in unit.attribute_values}

    return render_template(
        'units/edit_unit.html', 
        unit=unit,
        form=form,
        damage_form=damage_form,
        action_form=action_form,
        product_details_url=product_details_url,
        unit_spec_values=unit_spec_values,
        unit_attr_values=unit_attr_values
    )


@main.route('/internal/units/find')
@login_required
def find_unit():
    """
    Renders the live search page for finding a product unit.
    The actual search is handled by the /api/units/search endpoint.
    """
    return render_template('units/find_unit.html')


@api_bp.route('/units/search')
@login_required
def search_units():
    """
    Performs a live search for product units by serial number.
    Accepts a query parameter 'q'.
    """
    search_term = request.args.get('q', '').strip()

    if not search_term:
        # Return an empty list if the search term is empty
        return jsonify([])

    # Query the database
    # .ilike() is case-insensitive
    # The '%' is a wildcard for "starts with"
    # We use joinedload to efficiently get the parent Product's name
    # We limit the results to a reasonable number for performance
    units = ProductUnit.query.options(
        joinedload(ProductUnit.product),
        joinedload(ProductUnit.rental_grade),
        joinedload(ProductUnit.sale_grade)
    ).filter(
        ProductUnit.serial_number.ilike(f"{search_term}%")
    ).order_by(ProductUnit.serial_number).limit(20).all()

    # Serialize the results
    results = []
    for unit in units:
        # Determine the grade name. A unit can only have one or the other.
        grade_name = ""
        grade_color = None
        if unit.rental_grade:
            grade_name = unit.rental_grade.name
            grade_color = unit.rental_grade.color
        elif unit.sale_grade:
            grade_name = unit.sale_grade.name
            grade_color = unit.sale_grade.color

        results.append({
            'unit_id': unit.unit_id,
            'serial_number': unit.serial_number,
            'product_name': unit.product.name if unit.product else 'N/A',
            'grade_name': grade_name,
            'grade_color': grade_color
        })

    return jsonify(results)


@main.route('/internal/products/<int:product_id>/units')
@login_required
@role_required('admin', 'manager')
def view_units_for_product(product_id):
    """Displays a list of all ProductUnits for a given parent Product SKU."""
    product = Product.query.get_or_404(product_id)
    
    # Fetch all units for this product, eagerly loading related data for performance
    units = product.product_units.options(
        joinedload(ProductUnit.rental_grade),
        joinedload(ProductUnit.sale_grade),
        joinedload(ProductUnit.space)
    ).order_by(ProductUnit.serial_number).all()

    # Check if the parent SKU is concrete to enable/disable the batch create button
    is_concrete = is_product_sku_concrete(product)

    return render_template(
        'units/view_units_for_product.html',
        product=product,
        units=units,
        is_concrete=is_concrete
    )


@main.route('/internal/public-products/<int:public_product_id>/units')
@login_required
@role_required('admin', 'manager')
def view_units_for_public_product(public_product_id):
    """Displays a list of all ProductUnits that belong to a given PublicProduct."""
    public_product = PublicProduct.query.get_or_404(public_product_id)
    
    # Use helper to get the logically associated units
    units = get_units_for_public_product(public_product_id)
    all_rental_grades = RentalGrade.query
    all_sale_grades = SaleGrade.query

    return render_template(
        'public_products/view_units_for_public_product.html',
        public_product=public_product,
        units=units,
        rental_grades=all_rental_grades,
        sale_grades=all_sale_grades
    )


@main.route('/internal/units/batch-create', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'manager')
def batch_create_units():
    """
    A dedicated page for the batch creation of multiple, identical product units.
    """
    form = BatchCreateUnitForm()

    product_id_from_url = request.args.get('product_id', type=int)
    if request.method == 'GET' and product_id_from_url:
        product = Product.query.get(product_id_from_url)
        if product:
            form.product_id.data = product

    if form.validate_on_submit():
        parent_product = form.product_id.data
        quantity_to_create = form.quantity.data        
        start_number = form.serial_start_number.data
        
        try:
            units_created = []
            # Loop from the start number for the specified quantity
            for i in range(quantity_to_create):
                current_number = start_number + i

                raw_prefix = form.serial_number_prefix.data or ""
                raw_suffix = form.serial_number_suffix.data or ""
            
                clean_prefix = raw_prefix.strip().strip('-')
                clean_suffix = raw_suffix.strip().strip('-')
                
                parts = [clean_prefix, clean_suffix, str(current_number)]
                serial_number = '-'.join(filter(None, parts))
                            
                # Critical backend safety check for uniqueness
                if ProductUnit.query.filter_by(serial_number=serial_number).first():
                    raise IntegrityError(f"Generated serial number '{serial_number}' already exists in the database.")

                new_unit = ProductUnit(
                    product=parent_product,
                    serial_number=serial_number,
                    condition='available',
                    rental_grade=form.rental_grade_id.data,
                    sale_grade=form.sale_grade_id.data,
                    space=form.space.data,
                    actual_production_cost = form.actual_production_cost.data
                )
                db.session.add(new_unit)
                db.session.flush()
                save_unit_attribute_values(new_unit, request.form)
                units_created.append(serial_number)

            db.session.commit()
            flash(f"{len(units_created)} unit(s) created successfully: {', '.join(units_created)}", "success")
            return redirect(url_for('main.view_products'))

        except (IntegrityError, ValueError) as e:
            db.session.rollback()
            flash(f"Error creating units: {str(e)}", "danger")
            
    elif request.method == 'POST' and form.errors:
        flash(f"Failed to save units. Please correct the errors: {form.errors}", "danger")

    # Prepare data for the template's AJAX call
    product_details_url_template = url_for('api.get_product_details', product_id='PRODUCT_ID')

    return render_template(
        'units/batch_create_units.html',
        form=form,
        product_details_url_template=product_details_url_template
    )


@main.route('/internal/units/create-single', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'manager', 'user')
def create_single_unit():
    """
    A dedicated page for creating a single, potentially unique product unit.
    This is the workflow for fulfilling abstract specifications.
    """
    form = CreateSingleUnitForm()

    product_id_from_url = request.args.get('product_id', type=int)
    if request.method == 'GET' and product_id_from_url:
        product = Product.query.get(product_id_from_url)
        if product:
            form.product_id.data = product

    if form.validate_on_submit():
        parent_product = form.product_id.data
        
        # --- Assemble and validate the final serial number ---
        raw_prefix = form.serial_number_prefix.data or ""
        raw_suffix = form.serial_number_suffix.data or ""
        raw_value = form.serial_number_value.data or ""

        clean_prefix = raw_prefix.strip().strip('-')
        clean_suffix = raw_suffix.strip().strip('-')
        clean_value = raw_value.strip().strip('-')

        parts = [clean_prefix, clean_suffix, clean_value]
        final_serial_number = '-'.join(filter(None, parts))

        # --- Backend safety checks ---
        if not final_serial_number:
            flash("Serial number cannot be empty.", "danger")
        elif ProductUnit.query.filter_by(serial_number=final_serial_number).first():
            flash(f"The serial number '{final_serial_number}' is already in use.", "danger")
        else:
            try:
                new_unit = ProductUnit(
                    product=parent_product,
                    serial_number=final_serial_number,
                    condition='available', 
                    description=form.description.data,
                    rental_grade=form.rental_grade_id.data,
                    sale_grade=form.sale_grade_id.data,
                    space=form.space.data,
                    actual_production_cost = form.actual_production_cost.data
                )
                db.session.add(new_unit)
                db.session.flush() # Flush to get the new_unit.unit_id

                # --- Process SPECIFICATION values using our universal helper ---
                spec_definitions = get_definitions_for_categories([parent_product.category_id])
                for definition in spec_definitions:
                    if definition.forbid_override: continue
                    
                    error = save_unit_spec_value(new_unit, definition, request.form)
                    if error:
                        raise ValueError(f"Invalid value for '{definition.name}': {error}")
                
                save_unit_attribute_values(new_unit, request.form)
                save_unit_shop_categories(new_unit, request.form)

                db.session.commit()
                flash(f"Unit '{new_unit.serial_number}' created successfully.", "success")
                return redirect(url_for('main.view_products'))
            
            except (ValueError, IntegrityError) as e:
                db.session.rollback()
                flash(f"Error creating unit: {str(e)}", "danger")

    # If form validation fails, flash the errors
    if request.method == 'POST' and form.errors:
        flash(f"Failed to save unit. Please correct the errors: {form.errors}", "danger")

    # Prepare data for the template's AJAX call
    product_details_url_template = url_for('api.get_product_details', product_id='PRODUCT_ID')

    return render_template(
        'units/create_single_unit.html', 
        form=form,
        product_details_url_template=product_details_url_template
    )


# api for JS
@api_bp.route('/product-details/<product_id>')
@login_required
def get_product_details(product_id):
    """
    API endpoint to fetch all data needed to dynamically build the ProductUnit form.
    """
    try:
        prod_id = int(product_id)
    except ValueError:
        return jsonify({'error': 'Invalid product ID'}), 404
    
    product = Product.query.get_or_404(product_id)
    category = product.category

    # 1. Get all applicable specifications for the product's category
    definitions = get_definitions_for_categories([category.category_id])
    
    final_spec_values = get_all_values_for_product(product)

    spec_data = []
    for spec_def in definitions:
        effective_option_list = spec_def.option_list or (spec_def.attribute.option_list if spec_def.attribute else None)
        
        # We need to determine the effective rules for this spec, just like in the other API
        rule_override = SpecificationRuleOverride.query.filter_by(
            category_id=category.category_id, 
            definition_id=spec_def.id
        ).first()

        is_final = rule_override.forbid_override if (rule_override and rule_override.forbid_override is not None) else spec_def.forbid_override
        
        is_abstract_rule = rule_override.requires_implementation if (rule_override and rule_override.requires_implementation is not None) else spec_def.requires_implementation
        
        # A spec is abstract if the rule says so AND the parent SKU hasn't provided a value.
        final_value = final_spec_values.get(spec_def.name)
        is_abstract = is_abstract_rule and not final_value

        spec_data.append({
            'id': spec_def.id,
            'name': spec_def.name,
            'value': final_value or '',
            'is_abstract': is_abstract,
            'is_final': is_final,
            'data_type': spec_def.data_type.to_json(),
            'option_list': effective_option_list.to_json() if effective_option_list else None
        })

    # 2. Get global attributes that are NOT already handled by a synced spec
    synced_attribute_ids = {spec.attribute_id for spec in definitions if spec.attribute_id}
    unlinked_attributes = Attribute.query.filter(Attribute.attribute_id.notin_(synced_attribute_ids)).all()
    attr_data = [attr.to_json() for attr in unlinked_attributes]

    # 3. Get the available Commercial Grades for the product's category
    rental_grades = [{'id': grade.id, 'name': grade.name} for grade in category.available_rental_grades]
    sale_grades = [{'id': grade.id, 'name': grade.name} for grade in category.available_sale_grades]
    
    # 4. Find the highest serial number for this prefix to suggest the next one.
    next_serial_number_suggestion = ""
    prefix_to_check = product.serial_number_prefix or ''
    if prefix_to_check:
        all_serials_for_prefix = db.session.query(ProductUnit.serial_number).filter(
            ProductUnit.serial_number.like(f"{prefix_to_check}%")
        ).all()
        
        highest_num = 0
        for serial_tuple in all_serials_for_prefix:
            serial = serial_tuple[0]
            try:
                num_part_str = serial.split('-')[-1]
                if num_part_str.isdigit():
                    num_part = int(num_part_str)
                    if num_part > highest_num:
                        highest_num = num_part
            except (ValueError, IndexError):
                continue
        
        # The suggestion should only be the number, the JS will assemble the full string
        next_serial_number_suggestion = str(highest_num + 1)
    
    return jsonify({
        'product_name': product.name,
        'specifications': spec_data,
        'unlinked_attributes': attr_data,
        'available_rental_grades': rental_grades,
        'available_sale_grades': sale_grades,
        'serial_number_prefix': product.serial_number_prefix or '',
        'next_serial_suggestion': next_serial_number_suggestion,
        'standard_production_cost': product.standard_production_cost if product.standard_production_cost is not None else ''
    })


@main.route('/delete_unit/<int:unit_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_unit(unit_id):
    unit = ProductUnit.query.get_or_404(unit_id)
    parent_product_id = unit.product_id
    db.session.delete(unit)
    db.session.commit()
    flash(f"Product unit with serial number '{unit.serial_number}' deleted successfully!", 'success')
    return redirect(url_for('main.view_units_for_product', product_id=parent_product_id))





