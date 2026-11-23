# app/inventory/routes.py

from flask import Blueprint, flash, redirect, request, url_for, render_template
from flask_login import login_required
from app.permissions import role_required
from app.extensions import db
from app.products.models import ProductUnit
from sqlalchemy.orm import joinedload
from .models import AssetTag, Damage, Space
from .forms import AssetTagActionForm, SpaceForm

# blueprint for inventory-related routes
inventory_bp = Blueprint('inventory', __name__, url_prefix='/internal/inventory')

@inventory_bp.route('/unit/<int:unit_id>/generate-tag', methods=['POST'])
@login_required
@role_required('admin', 'manager')
def generate_and_assign_tag(unit_id):
    """
    Creates a brand new AssetTag and assigns it to a unit that doesn't have one.
    """
    form = AssetTagActionForm()
    if form.validate_on_submit():
        unit = ProductUnit.query.get_or_404(unit_id)

        # Safety check: Only proceed if the unit doesn't already have a tag.
        if unit.asset_tag:
            flash("This unit already has an assigned asset tag.", "warning")
            return redirect(url_for('main.edit_unit', unit_id=unit_id))

        try:
            new_tag = AssetTag(status='active', unit=unit)
            db.session.add(new_tag)
            db.session.commit()
            flash(f"Successfully generated and assigned new QR Code: {new_tag.code_value}", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred while generating the tag: {e}", "danger")
        
    else:
        # This will catch CSRF errors
        flash("Invalid request. Could not generate tag.", "danger")

    return redirect(url_for('main.edit_unit', unit_id=unit_id))


@inventory_bp.route('/unit/<int:unit_id>/reassign-tag', methods=['POST'])
@login_required
@role_required('admin', 'manager')
def decommission_and_reassign_tag(unit_id):
    """
    Decommissions a unit's old tag and assigns a brand new one.
    """
    form = AssetTagActionForm()
    if form.validate_on_submit():
        unit = ProductUnit.query.get_or_404(unit_id)
        
        try:
            # Decommission the old tag, if it exists
            if unit.asset_tag:
                old_tag = unit.asset_tag
                old_tag.status = 'decommissioned'
                old_tag.unit = None # Unlink it from the unit
                flash(f"Decommissioned old tag: {old_tag.code_value}", "info")

            # Create and assign the new tag
            new_tag = AssetTag(status='active', unit=unit)
            db.session.add(new_tag)
            db.session.commit()
            flash(f"Successfully assigned new QR Code: {new_tag.code_value}", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred while reassigning the tag: {e}", "danger")
            
    else:
        flash("Invalid request. Could not reassign tag.", "danger")

    return redirect(url_for('main.edit_unit', unit_id=unit_id))


@inventory_bp.route('/tag/<int:tag_id>/print')
@login_required
@role_required('admin', 'manager')
def print_tag(tag_id):
    """
    Displays a minimalist, print-friendly page for a single AssetTag.
    """
    tag = AssetTag.query.get_or_404(tag_id)
    return render_template('inventory/print_tag.html', tag=tag)


@inventory_bp.route('/scan-tag')
@login_required
@role_required('admin', 'manager', 'user') # Allow all logged-in users to scan
def scan_tag():
    """
    Renders the dedicated page for scanning a QR code with the device's camera.
    """
    lookup_url = url_for('inventory.find_unit_by_tag')
    return render_template('inventory/scan_tag.html', lookup_url=lookup_url)


@inventory_bp.route('/find-by-tag')
@login_required
@role_required('admin', 'manager', 'user')
def find_unit_by_tag():
    """
    Receives a 'code' from a QR scan, finds the associated unit,
    and redirects the user to that unit's edit page.
    """
    # 1. Get the scanned code value from the URL query parameter (e.g., ?code=...).
    scanned_code = request.args.get('code')

    if not scanned_code:
        flash("No code provided in the request.", "warning")
        return redirect(url_for('main.home'))

    # 2. Perform a direct, exact lookup in the AssetTag table.
    found_tag = AssetTag.query.filter_by(code_value=scanned_code).first()

    # 3. Handle the result.
    if found_tag and found_tag.unit_id:
        flash(f"QR Code found. Loading unit: {found_tag.unit.serial_number}", "success")
        return redirect(url_for('main.edit_unit', unit_id=found_tag.unit_id))
    
    elif found_tag and not found_tag.unit_id:
        # EDGE CASE: The tag exists but is not assigned to any unit.
        flash(f"Asset Tag '{scanned_code}' was found but is not assigned to a unit.", "warning")
        return redirect(url_for('inventory.scan_tag'))

    else:
        flash(f"Error: QR Code '{scanned_code}' not found in the system.", "danger")
        return redirect(url_for('inventory.scan_tag')) 


@inventory_bp.route('/delete_damage/<int:damage_id>', methods=['POST'])
@login_required
@role_required('admin', 'manager')
def delete_damage(damage_id):
    damage = Damage.query.get_or_404(damage_id)
    unit_id = damage.unit_id


    db.session.delete(damage)
    db.session.commit()
    flash("Damage deleted successfully!", 'success')
    return redirect(url_for('main.edit_unit', unit_id=unit_id))


@inventory_bp.route('/spaces', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'manager')
def manage_spaces():
    """
    Main hub for viewing all spaces and the form to create/edit them.
    """
    form = SpaceForm()
    edit_id = request.args.get('edit', type=int)
    edit_space = Space.query.get_or_404(edit_id) if edit_id else None

    if form.validate_on_submit():
        if edit_space:
            # Update existing
            edit_space.name = form.name.data
            edit_space.description = form.description.data
            flash(f"Space '{edit_space.name}' updated successfully.", "success")
        else:
            # Create new
            new_space = Space(
                name=form.name.data,
                description=form.description.data
            )
            db.session.add(new_space)
            flash(f"Storage Space '{new_space.name}' created.", "success")
        
        db.session.commit()
        return redirect(url_for('inventory.manage_spaces'))
        
    elif request.method == 'POST' and form.errors:
        flash("Could not save space. Please check the form for errors.", "danger")

    # Populate form for GET request on an edit
    if request.method == 'GET' and edit_space:
        form.process(obj=edit_space)


    all_spaces = Space.query.order_by(Space.name).all()
    
    return render_template(
        'inventory/manage_spaces.html',
        all_spaces=all_spaces,
        form=form,
        edit_space=edit_space
    )


@inventory_bp.route('/spaces/delete/<int:space_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_space(space_id):
    """
    Deletes a space, but ONLY if it is empty (contains no units).
    """
    space_to_delete = Space.query.get_or_404(space_id)

    # SAFETY CHECK: Do not allow deletion if units are assigned here.
    # Because of the dynamic backref, space.product_units is a query.
    if space_to_delete.product_units.first():
        flash(f"Cannot delete '{space_to_delete.name}'. You must move all items out of this space first.", "danger")
        return redirect(url_for('inventory.manage_spaces'))

    db.session.delete(space_to_delete)
    db.session.commit()
    flash(f"Storage Space '{space_to_delete.name}' has been deleted.", "success")
    
    return redirect(url_for('inventory.manage_spaces'))


@inventory_bp.route('/spaces/<int:space_id>/inventory')
@login_required
@role_required('admin', 'manager', 'user')
def view_space_inventory(space_id):
    """
    Detailed view showing a sortable table of ALL units currently in this specific space.
    """
    space = Space.query.get_or_404(space_id)
    
    units_in_space = space.product_units.options(
        joinedload(ProductUnit.product),
        joinedload(ProductUnit.rental_grade),
        joinedload(ProductUnit.sale_grade)
    ).order_by(ProductUnit.serial_number).all()

    return render_template(
        'inventory/space_inventory.html', 
        space=space, 
        units=units_in_space
    )