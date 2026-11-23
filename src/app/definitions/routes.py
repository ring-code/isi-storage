# src/app/definitions/routes.py

import json

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from sqlalchemy import inspect
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError

from app.permissions import role_required
from app.extensions import db
from app.utility.relationship_helpers import is_model_instance_in_use
from app.utility.validation_logic import validate_value_by_datatype
from .forms import DataTypeForm, CreateOptionListForm, EditOptionListForm, AttributeForm
from .models import DataType, OptionList, OptionListItem, Attribute


# --- BLUEPRINT ---
def_bp = Blueprint('definitions', __name__, url_prefix='/internal/definitions')


@def_bp.route('/data_types', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_data_types():
    form = DataTypeForm()
    edit_id = request.args.get('edit', type=int)
    edit_type = DataType.query.get_or_404(edit_id) if edit_id else None

    if edit_type and request.method == 'POST':
        form.display_type.data = edit_type.display_type
    
    if form.validate_on_submit():
        if edit_type: # UPDATE
            edit_type.name = form.name.data
            edit_type.validation_rules = json.loads(form.validation_rules.data) if form.validation_rules.data else None
            flash(f"Data Type '{edit_type.name}' updated.", "success")
        else: # CREATE
            new_type = DataType(
                name=form.name.data,
                display_type=form.display_type.data,
                validation_rules=json.loads(form.validation_rules.data) if form.validation_rules.data else None
            )
            db.session.add(new_type)
            flash(f"Data Type '{new_type.name}' created.", "success")

        db.session.commit()
        return redirect(url_for('definitions.manage_data_types'))
    
    # --- Populate form for GET requests ---
    if request.method == 'GET' and edit_type:
        form.process(obj=edit_type)
        # Manually format the JSON for pretty printing in the textarea
        form.validation_rules.data = json.dumps(edit_type.validation_rules, indent=2) if edit_type.validation_rules else ''

    mapper = inspect(DataType)
    loading_options = []
    # loop through the relationships and build the loading options intelligently.
    for rel in mapper.relationships:
        if rel.lazy != 'dynamic':
            loading_options.append(joinedload(getattr(DataType, rel.key)))

    # apply only the valid loading options to the query.
    all_data_types = DataType.query.options(*loading_options).order_by(DataType.name).all()

    # attach the flag.
    for dt in all_data_types:
        in_use, _ = is_model_instance_in_use(dt)
        dt.is_deletable = not in_use


    return render_template(
        'data_types/manage_data_types.html',
        form=form,
        all_data_types=all_data_types,
        edit_type=edit_type
    )


@def_bp.route('/data_types/delete/<int:data_type_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_data_type(data_type_id):
    """
    Deletes a DataType, but only if it's not currently in use by ANY other model.
    """
    type_to_delete = DataType.query.get_or_404(data_type_id)

    in_use, relationship_name = is_model_instance_in_use(type_to_delete)

    if in_use:
        flash(f"Cannot delete Data Type '{type_to_delete.name}'. It is currently in use by the '{relationship_name}' relationship.", "danger")
        return redirect(url_for('definitions.manage_data_types'))

    # If the check passes, it's safe to delete.
    db.session.delete(type_to_delete)
    db.session.commit()
    flash(f"Data Type '{type_to_delete.name}' has been deleted.", "success")
    return redirect(url_for('definitions.manage_data_types'))


@def_bp.route('/option-lists', methods=['GET'])
@login_required
@role_required('admin')
def manage_option_lists():
    """
    The main hub page for viewing all OptionLists.
    """
    # Eagerly load all relationships on the OptionList model.
    mapper = inspect(OptionList)
    loading_options = [joinedload(getattr(OptionList, rel.key)) for rel in mapper.relationships]
    all_option_lists = OptionList.query.options(*loading_options).order_by(OptionList.name).all()
    
    # loop through and attach the deletable flag using our generic helper.
    for o_list in all_option_lists:
        # exclude the 'items' relationship from the check.
        in_use, _ = is_model_instance_in_use(o_list, exclude_relationships=['items', 'item_data_type'])
        o_list.is_deletable = not in_use

    
    return render_template(
        'option_lists/manage_option_lists.html',
        all_option_lists=all_option_lists
    )


@def_bp.route('/option-lists/create', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def create_option_list():
    form = CreateOptionListForm()
    
    if form.validate_on_submit():
        new_list = OptionList(
            name=form.name.data,
            item_data_type=form.item_data_type.data,
            allow_multiple_selections=form.allow_multiple_selections.data,
            display_hint=form.display_hint.data, 
            selection_rules=json.loads(form.selection_rules.data) if form.selection_rules.data else None
        )
        db.session.add(new_list)
        db.session.flush()

        for item_data in form.items.data:
            if item_data.get('value', '').strip():
                new_item = OptionListItem(value=item_data['value'], option_list_id=new_list.id)
                db.session.add(new_item)
        
        db.session.commit()
        flash(f"Option List '{new_list.name}' created successfully.", "success")
        return redirect(url_for('definitions.manage_option_lists'))


    all_data_types = DataType.query.all()
    data_type_map = {str(dt.id): dt.to_json() for dt in all_data_types}
    
    return render_template(
        'option_lists/create_option_list.html',
        form=form,
        data_type_map_json=json.dumps(data_type_map)
    )


@def_bp.route('/option-lists/<int:list_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_option_list(list_id):
    option_list = OptionList.query.get_or_404(list_id)
    # Pass the object to the form's constructor.
    form = EditOptionListForm(option_list=option_list)

    if form.validate_on_submit():
        option_list.name = form.name.data
        if not option_list.allow_multiple_selections:
             option_list.display_hint = form.display_hint.data
        
        for item_data in form.items.data:
            value = item_data.get('value', '').strip()
            item_id = item_data.get('id')
            
            if value and not item_id:
                is_valid, error_msg = validate_value_by_datatype(value, option_list.item_data_type)
                if not is_valid:
                    flash(f"Invalid new item value '{value}': {error_msg}", "danger")
                    db.session.rollback() 
                    return redirect(url_for('definitions.edit_option_list', list_id=list_id))

                new_item = OptionListItem(value=value, option_list_id=option_list.id)
                db.session.add(new_item)
        
        db.session.commit()
        flash(f"Option List '{option_list.name}' updated successfully.", "success")
        return redirect(url_for('definitions.manage_option_lists'))
    
    # On a GET request, populate the form with data from the object.
    if request.method == 'GET':
        form.process(obj=option_list)

    all_data_types = DataType.query.all()
    data_type_map = {str(dt.id): dt.to_json() for dt in all_data_types}
    existing_items = [{'id': item.id, 'value': item.value} for item in option_list.items]
    
    return render_template(
        'option_lists/edit_option_list.html',
        form=form,
        option_list=option_list, 
        data_type_map_json=json.dumps(data_type_map),
        existing_items_json=json.dumps(existing_items)
    )


@def_bp.route('/internal/option-lists/<int:list_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def delete_option_list(list_id):
    option_list = OptionList.query.get_or_404(list_id)

    # Exclude 'items' because we want to be able to delete a list even if it has items.
    # Exclude 'item_data_type' because that's a dependency pointing outwards, not inwards.
    in_use, relationship_name = is_model_instance_in_use(option_list, exclude_relationships=['items', 'item_data_type'])
    
    if in_use:
        flash(f"Cannot delete '{option_list.name}'. It is in use by the '{relationship_name}' relationship.", "danger")
        return redirect(url_for('definitions.manage_option_lists'))

    db.session.delete(option_list)
    db.session.commit()
    flash(f"Option List '{option_list.name}' has been deleted.", "success")
    return redirect(url_for('definitions.manage_option_lists'))


@def_bp.route('/internal/attributes')
@login_required
@role_required('admin')
def view_attributes():
    """The main hub page for viewing all global attributes."""
    all_attributes = Attribute.query.order_by(Attribute.name).all()
    return render_template(
        'attributes/view_attributes.html',
        all_attributes=all_attributes
    )


@def_bp.route('/internal/attributes/manage/', defaults={'attribute_id': None}, methods=['GET', 'POST'])
@def_bp.route('/internal/attributes/manage/<int:attribute_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_attribute(attribute_id):
    """Handles both creating and editing a global Attribute."""
    attribute = Attribute.query.get_or_404(attribute_id) if attribute_id else None
    form = AttributeForm(obj=attribute)

    if form.validate_on_submit():
        is_new = not attribute
        
        try:
            if not is_new:
                # --- EDIT LOGIC ---
                attribute.name = form.name.data
                attribute.sync_behavior = form.sync_behavior.data
            
            else: # --- CREATE LOGIC ---
                option_list = form.option_list.data
                if option_list:
                    data_type_to_set = option_list.item_data_type
                    option_list_to_set = option_list
                else:
                    data_type_to_set = form.data_type.data
                    option_list_to_set = None

                attribute = Attribute(
                    name=form.name.data,
                    sync_behavior=form.sync_behavior.data,
                    data_type=data_type_to_set,
                    option_list=option_list_to_set
                )
                db.session.add(attribute)

            db.session.commit()
            flash(f"Attribute '{attribute.name}' has been saved.", "success")
            return redirect(url_for('definitions.view_attributes'))

        except IntegrityError:
            db.session.rollback()
            flash("Error: An integrity error occurred. The attribute name may already exist.", "danger")

    # This final return statement handles all GET requests and failed POST validations.
    return render_template('attributes/manage_attribute.html', form=form, attribute=attribute)


@def_bp.route('/delete_attribute/<int:attribute_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_attribute(attribute_id):
    """
    Handles deletion of an attribute, with safety checks.
    """
    attribute = Attribute.query.get_or_404(attribute_id)

    if attribute.product_attributes: 
        flash(f"Cannot delete Attribute '{attribute.name}'. It has been assigned as a value to one or more products.", "danger")
        return redirect(url_for('definitions.view_attributes'))
    
    if attribute.specification_definitions:
        flash(f"Cannot delete Attribute '{attribute.name}'. It is linked as a sync target by a Specification Definition.", "danger")
        return redirect(url_for('definitions.view_attributes'))
    
    db.session.delete(attribute)
    db.session.commit()
    
    flash(f"Attribute '{attribute.name}' deleted successfully!", "success")
    return redirect(url_for('definitions.view_attributes'))
