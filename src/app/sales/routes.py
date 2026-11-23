# isi_storage/app/sales/routes.py

import json
import logging
import subprocess
import sys
import os

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_login import login_required
from sqlalchemy.orm import joinedload
from decimal import Decimal

from app.extensions import db
from app.permissions import role_required
from .models import (
    Customer, 
    CustomerOrder,
    Address,
    OrderItem,
    Booking,
    PublicProduct,
    PublicVariation, 
    ShopCategory, 
    SaleGrade, 
    RentalGrade, 
    SaleCommercialProperty, 
    RentalCommercialProperty
) 
from app.products.models import ProductUnit
from .forms import (
    NewOrderForm, 
    AddItemToOrderForm, 
    DiscountForm, 
    AssignUnitsForm, 
    ShopCategoryForm, 
    RentalGradeForm, 
    SaleGradeForm, 
    PublicProductForm,
    CustomerForm,
    AddressForm
)
from app.utility.order_logic import check_availability, get_selectable_units_for_item
from app.utility.price_logic import calculate_item_price_and_total, calculate_order_totals
from app.utility.sync_logic import build_woocommerce_payload
from app.utility.public_product_logic import (
    get_public_products_with_active_variations, 
    refresh_variations_for_public_product, 
    get_available_rental_grades, 
    get_available_sale_grades,
    generate_unique_public_sku
)
from app.utility.form_helpers import get_all_rental_grades, get_all_sale_grades

# --- BLUEPRINT ---
sales_bp = Blueprint('sales', __name__, url_prefix='/internal/sales')


@sales_bp.route('/grades')
@login_required
@role_required('admin', 'manager')
def manage_grades():
    """
    The main hub page for viewing all Rental and Sale Grades.
    """
    all_rental_grades = RentalGrade.query.order_by(RentalGrade.name).all()
    all_sale_grades = SaleGrade.query.order_by(SaleGrade.name).all()
    return render_template(
        'grades/manage_grades.html',
        rental_grades=all_rental_grades,
        sale_grades=all_sale_grades
    )


@sales_bp.route('/grades/rental/', defaults={'grade_id': None}, methods=['GET', 'POST'])
@sales_bp.route('/internal/grades/rental/<int:grade_id>', methods=['GET', 'POST', 'DELETE'])
@login_required
@role_required('admin')
def manage_rental_grade(grade_id):
    """

    A single route for CREATING, EDITING, and DELETING a RentalGrade.
    """
    if grade_id:
        grade = RentalGrade.query.get_or_404(grade_id)
        form = RentalGradeForm(obj=grade)
    else:
        grade = None
        form = RentalGradeForm()

    if request.method == 'DELETE' or (request.form.get('_method') == 'DELETE'):
        if grade.product_units:
            flash(f"Cannot delete '{grade.name}' as it is in use.", "danger")
        else:
            db.session.delete(grade)
            db.session.commit()
            flash(f"Rental Grade '{grade.name}' deleted.", "success")
        return redirect(url_for('sales.manage_grades'))

    if form.validate_on_submit():
        is_new = not grade
        if is_new:
            grade = RentalGrade()
            db.session.add(grade)
        
        # --- Manual population  ---
        grade.name = form.name.data
        grade.first_day_price = form.first_day_price.data
        grade.next_day_price = form.next_day_price.data
        grade.tax_rate = form.tax_rate.data
        grade.shipping_class_slug = form.shipping_class_slug.data
        grade.available_in_categories = form.available_in_categories.data
        if form.color.data:
            # If the data is not a string, it must be the Color object, so get its .hex
            # Otherwise, it's already the hex string from the form.
            if not isinstance(form.color.data, str):
                grade.color = form.color.data.hex
            else:
                grade.color = form.color.data
        else:
            grade.color = None

        # --- Handle flexible properties ---
        RentalCommercialProperty.query.filter_by(rental_grade=grade).delete()
        for prop_form in form.properties.data:
            # Rule: We only care about a row if at least a key has been entered.
            if prop_form.get('key', '').strip():
                # The value is optional. If it's empty, save an empty string.
                value_to_save = prop_form.get('value', '').strip()
                
                new_prop = RentalCommercialProperty(
                    key=prop_form['key'],
                    value=value_to_save, # Save the (possibly empty) value
                    property_type='price',
                    rental_grade=grade
                )
                db.session.add(new_prop)
        
        db.session.commit()
        flash(f"Rental Grade '{grade.name}' {'created' if is_new else 'updated'}.", "success")
        return redirect(url_for('sales.manage_grades'))
    
    if request.method == 'POST' and form.errors:
        # Format the errors into a user-friendly string
        error_list = [f"{field.replace('_', ' ').title()}: {', '.join(errs)}" for field, errs in form.errors.items()]
        flash(f"Failed to save. Please correct the following errors: {'; '.join(error_list)}", "danger")

    return render_template('grades/manage_grade_form.html', form=form, grade=grade, grade_type='Rental')


@sales_bp.route('/grades/sale/', defaults={'grade_id': None}, methods=['GET', 'POST'])
@sales_bp.route('/grades/sale/<int:grade_id>', methods=['GET', 'POST', 'DELETE'])
@login_required
@role_required('admin')
def manage_sale_grade(grade_id):
    """
    A single route for CREATING, EDITING, and DELETING a SaleGrade.
    """
    if grade_id:
        grade = SaleGrade.query.get_or_404(grade_id)
        form = SaleGradeForm(obj=grade)
    else:
        grade = None
        form = SaleGradeForm()
    
    if request.method == 'DELETE' or (request.form.get('_method') == 'DELETE'):
        if grade.product_units:
            flash(f"Cannot delete '{grade.name}' as it is in use.", "danger")
        else:
            db.session.delete(grade)
            db.session.commit()
            flash(f"Sale Grade '{grade.name}' deleted.", "success")
        return redirect(url_for('sales.manage_grades'))

    if form.validate_on_submit():
        is_new = not grade
        if is_new:
            grade = SaleGrade()
            db.session.add(grade)

        grade.name = form.name.data
        grade.sale_price = form.sale_price.data
        grade.tax_rate = form.tax_rate.data
        grade.shipping_class_slug = form.shipping_class_slug.data
        grade.is_convertible_to_rental = form.is_convertible_to_rental.data
        grade.available_in_categories = form.available_in_categories.data
        if form.color.data:
            # If the data is not a string, it must be the Color object, so get its .hex
            # Otherwise, it's already the hex string from the form.
            if not isinstance(form.color.data, str):
                grade.color = form.color.data.hex
            else:
                grade.color = form.color.data
        else:
            grade.color = None

        # --- Handle flexible properties ---
        SaleCommercialProperty.query.filter_by(sale_grade=grade).delete()
        for prop_form in form.properties.data:
            if prop_form.get('key', '').strip():
                value_to_save = prop_form.get('value', '').strip()
                new_prop = SaleCommercialProperty(
                    key=prop_form['key'],
                    value=value_to_save,
                    property_type='price',
                    sale_grade=grade
                )
                db.session.add(new_prop)

        db.session.commit()
        flash(f"Sale Grade '{grade.name}' {'created' if is_new else 'updated'}.", "success")
        return redirect(url_for('sales.manage_grades'))
    
    if request.method == 'POST' and form.errors:
        # Format the errors into a user-friendly string
        error_list = [f"{field.replace('_', ' ').title()}: {', '.join(errs)}" for field, errs in form.errors.items()]
        flash(f"Failed to save. Please correct the following errors: {'; '.join(error_list)}", "danger")

    return render_template('grades/manage_grade_form.html', form=form, grade=grade, grade_type='Sale')


@sales_bp.route('/public-products')
@login_required
@role_required('admin', 'manager')
def view_public_products():
    """Displays the main hub for managing Public Products."""
    
    # Call the helper to get the annotated list of sales products
    all_public_products = get_public_products_with_active_variations()

    used_variation_ids = {item.public_variation_id for item in OrderItem.query.all()}
    
    for pp in all_public_products:
        pp.is_in_use = False
        variation_ids = {v.id for v in pp.variations}
        if variation_ids.intersection(used_variation_ids):
            pp.is_in_use = True

    rental_grades = RentalGrade.query
    sale_grades = SaleGrade.query

    is_sync_configured = bool(os.getenv('WP_API_BASE_URL'))
    
    return render_template(
        'public_products/view_public_products.html',
        public_products=all_public_products,
        rental_grades=rental_grades,
        sale_grades=sale_grades,
        is_sync_configured=is_sync_configured
    )


@sales_bp.route('/public-products/<int:public_product_id>/refresh-variations', methods=['POST'])
@login_required
@role_required('admin')
def refresh_public_product_variations(public_product_id):
    """
    Handles the "Refresh" button click for a PublicProduct.
    """
    public_product = PublicProduct.query.get_or_404(public_product_id)
    
    refresh_variations_for_public_product(public_product)
    
    db.session.commit()
    
    flash(f"Variations for '{public_product.name}' have been refreshed based on its grade.", "success")
    return redirect(url_for('sales.view_public_products'))


@sales_bp.route('/public-products/manage/', defaults={'public_product_id': None}, methods=['GET', 'POST'])
@sales_bp.route('/public-products/manage/<int:public_product_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_single_public_product(public_product_id):
    """Handles the creation and editing of a PublicProduct."""
    public_product = PublicProduct.query.get_or_404(public_product_id) if public_product_id else None
    
    # 1. Instantiate the form. If it's a POST request, it's populated from the form data.
    #    If it's a GET request for an edit, we pass `obj=public_product`.
    form = PublicProductForm(request.form, obj=public_product)

    # 2. Set dynamic choices, which is always needed.
    # form.shop_categories.choices = [(cat.id, get_hierarchical_shop_category_label(cat)) for cat in get_hierarchical_shop_categories()]
    if not public_product: # Filter available grades only on CREATE page
        form.rental_grade.query_factory = get_available_rental_grades
        form.sale_grade.query_factory = get_available_sale_grades

    # 3. Handle POST submission
    if form.validate_on_submit():
        # Determine if we're creating or editing
        is_new = not public_product
        
        if is_new:
            # Create the instance, but DON'T add it to the session yet.
            public_product = PublicProduct()

            # Populate all required fields.
            selected_grade = form.rental_grade.data or form.sale_grade.data
            public_product.grade_id = selected_grade.id
            public_product.final_tax_rate = selected_grade.tax_rate or Decimal('0.00')

            if isinstance(selected_grade, RentalGrade):
                public_product.grade_type = 'rental_grade'
                public_product.final_first_day_price = selected_grade.first_day_price
                public_product.final_next_day_price = selected_grade.next_day_price
            else: # SaleGrade
                public_product.grade_type = 'sale_grade'
                public_product.final_sale_price = selected_grade.sale_price

        
        # Set name from form
        public_product.name = form.name.data
        
        # Set public SKU 
        if form.public_sku.data:
            public_product.public_sku = form.public_sku.data
        else:
            public_product_id_for_check = public_product.id if not is_new else None
            public_product.public_sku = generate_unique_public_sku(public_product.name, existing_public_product_id=public_product_id_for_check)

        if is_new:
            db.session.add(public_product)
        
        # --- Sync and Commit ---
        db.session.commit()

        refresh_variations_for_public_product(public_product)
        db.session.commit() # Commit the sync changes
        
        flash(f"Sales Product '{public_product.name}' saved successfully.", "success")
        return redirect(url_for('sales.view_public_products'))

    # 4. Handle initial page load (GET for an EDIT)
    # If it's not a POST, and we are editing, we need to pre-populate the relationship fields.
    if request.method != 'POST' and public_product:
        grade_obj = public_product.grade_object
        if isinstance(grade_obj, RentalGrade):
            form.rental_grade.data = grade_obj
        elif isinstance(grade_obj, SaleGrade):
            form.sale_grade.data = grade_obj
    
    # --- Prepare data for the template's JavaScript ---
    grade_details_map = {}
    for grade in get_all_rental_grades():
        key = f"rental_{grade.id}"
        grade_details_map[key] = {
            'type': 'Rental',
            'price1': f"€{grade.first_day_price:.2f}" if grade.first_day_price is not None else "N/A",
            'price2': f"€{grade.next_day_price:.2f}" if grade.next_day_price is not None else "N/A",
            'tax': f"{grade.tax_rate * 100:.2f}%" if grade.tax_rate is not None else "N/A",
            'color': grade.color
        }
    for grade in get_all_sale_grades():
        key = f"sale_{grade.id}"
        grade_details_map[key] = {
            'type': 'Sale',
            'price1': f"€{grade.sale_price:.2f}" if grade.sale_price is not None else "N/A",
            'tax': f"{grade.tax_rate * 100:.2f}%" if grade.tax_rate is not None else "N/A",
            'color': grade.color
        }

    # Data for the Jinja template to look up grade names in Edit mode
    rental_grades_query = RentalGrade.query
    sale_grades_query = SaleGrade.query

    return render_template(
        'public_products/manage_single_public_product.html', 
        form=form,
        public_product=public_product,
        grade_details_map_json=json.dumps(grade_details_map),
        rental_grades=rental_grades_query,
        sale_grades=sale_grades_query
    )


@sales_bp.route('/public-products/delete/<int:public_product_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_public_product(public_product_id):
    """Deletes a PublicProduct and its associated variations."""
    public_product = PublicProduct.query.get_or_404(public_product_id)

    variation_ids = [v.id for v in public_product.variations]
    if variation_ids and OrderItem.query.filter(OrderItem.public_variation_id.in_(variation_ids)).first():
        flash(f"Cannot delete Public Product '{public_product.name}'. It is part of one or more existing orders.", "danger")
        return redirect(url_for('sales.view_public_products'))
    
    db.session.delete(public_product)
    db.session.commit()
    
    flash(f"Sales Product '{public_product.name}' has been deleted.", "success")
    return redirect(url_for('sales.view_public_products'))


def get_shop_category_descendants(category: ShopCategory) -> list:
    """Recursively gets all descendant shop categories."""
    descendants = []
    for child in category.children:
        descendants.append(child)
        descendants.extend(get_shop_category_descendants(child))
    return descendants


@sales_bp.route('/shop_categories', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'manager')
def manage_shop_categories():
    form = ShopCategoryForm(request.form)
    edit_category = None
    edit_id = request.args.get('edit', type=int)

    if edit_id:
        edit_category = ShopCategory.query.get_or_404(edit_id)
        descendant_ids = [c.id for c in get_shop_category_descendants(edit_category)]
        descendant_ids.append(edit_id)
        form.parent.query_factory = lambda: ShopCategory.query.filter(
            ShopCategory.id.notin_(descendant_ids)
        ).order_by(ShopCategory.name).all()
        # Pass the ID to the form for the validator
        form.id.data = edit_category.id 

    if request.method == 'POST':
        # We need to manually set the id on POST as well for the validator
        if edit_category:
            form.id.data = edit_category.id

        if form.validate_on_submit():
            if edit_category: # UPDATE
                edit_category.name = form.name.data
                edit_category.parent = form.parent.data
                flash(f"Shop Category '{edit_category.name}' updated.", "success")
            else: # CREATE
                new_category = ShopCategory(name=form.name.data, parent=form.parent.data)
                db.session.add(new_category)
                flash(f"Shop Category '{new_category.name}' created.", "success")
            
            db.session.commit()
            return redirect(url_for('sales.manage_shop_categories'))
        else:
            flash("Could not save shop category. Please check the form for errors.", "danger")
    
    if request.method == 'GET' and edit_category:
        form.process(obj=edit_category)

    all_shop_categories = ShopCategory.query.filter(ShopCategory.parent_id.is_(None)).order_by(ShopCategory.name).all()
    
    return render_template(
        'shop_categories/manage_shop_categories.html', 
        form=form,
        all_shop_categories=all_shop_categories,
        edit_category=edit_category
    )


@sales_bp.route('/shop_categories/delete/<int:shop_category_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_shop_category(shop_category_id):
    category_to_delete = ShopCategory.query.get_or_404(shop_category_id)

    # Safety Check 1: Prevent deletion if products are directly assigned.
    if category_to_delete.products:
        flash(f"Cannot delete '{category_to_delete.name}'. It is still directly assigned to one or more products. Please un-assign them first.", "danger")
        return redirect(url_for('sales.manage_shop_categories'))

    # Manually re-parent only the DIRECT children to NULL.
    # The grandchildren's parent_id (pointing to the children) are unaffected.
    for child in category_to_delete.children:
        child.parent_id = None
    
    # Now that no children are pointing to it, it's safe to delete.
    db.session.delete(category_to_delete)
    db.session.commit()
    
    flash(f"Shop Category '{category_to_delete.name}' deleted. Its children have been promoted to top-level categories.", "success")
    return redirect(url_for('sales.manage_shop_categories'))


@sales_bp.route('/new', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'manager')
def new_order():
    """Handles the creation of a new parent CustomerOrder."""
    form = NewOrderForm()
    if form.validate_on_submit():
        # Find or create the customer
        customer = form.customer.data
        if not customer:
            # Check if a guest with this email already exists
            customer = Customer.query.filter_by(email=form.guest_email.data).first()
            if not customer:
                customer = Customer(
                    email=form.guest_email.data,
                    first_name=form.guest_first_name.data,
                    last_name=form.guest_last_name.data
                )
                db.session.add(customer)
        
        new_customer_order = CustomerOrder(
            status='Draft', # New orders start as a Draft
            order_type=form.order_type.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            customer=customer
        )
        # Set total/subtotal to 0 for now
        new_customer_order.subtotal = 0
        new_customer_order.total = 0

        db.session.add(new_customer_order)
        db.session.commit()
        
        flash("New order created. Please add items.", "success")
        return redirect(url_for('sales.add_items_to_order', customer_order_id=new_customer_order.id))
        
    return render_template('sales/new_order.html', form=form)


@sales_bp.route('/<int:customer_order_id>/add-items', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'manager')
def add_items_to_order(customer_order_id):
    # Use options() and joinedload() to force a fresh query that includes
    # all related order_items and their nested relationships.
    customer_order = CustomerOrder.query.options(
        joinedload(CustomerOrder.order_items).joinedload(OrderItem.public_variation).joinedload(PublicVariation.public_product),
        joinedload(CustomerOrder.order_items).joinedload(OrderItem.public_variation).joinedload(PublicVariation.manufacturing_product)
    ).get_or_404(customer_order_id)
    form = AddItemToOrderForm()
    
    # Dynamically populate the variation choices for the JS
    target_grade_type = customer_order.order_type + '_grade' # 'rental' -> 'rental_grade'
    
    # 2. Filter the QuerySelectField in the FORM
    form.public_product.query = PublicProduct.query.filter_by(grade_type=target_grade_type).order_by(PublicProduct.name)

    # 3. Build the variation map for JavaScript using the SAME filtered query
    public_products_for_map = form.public_product.query.options(
        joinedload(PublicProduct.variations).joinedload(PublicVariation.manufacturing_product)
    ).all()
    
    variation_map = {
        pp.id: [{'id': var.id, 'name': var.manufacturing_product.name} for var in pp.variations]
        for pp in public_products_for_map
    }
    # On a POST request, we must repopulate the variation choices BEFORE validation.
    if request.method == 'POST':
        # Get the submitted public_product ID from the form data
        selected_pp_id = request.form.get('public_product', type=int)
        if selected_pp_id:
            # Find the PublicProduct and its variations
            selected_pp = next((p for p in public_products_for_map if p.id == selected_pp_id), None)
            if selected_pp:
                # Set the choices for the public_variation field
                form.public_variation.choices = [
                    (var.id, var.manufacturing_product.name)
                    for var in selected_pp.variations
                ]

    if form.validate_on_submit():
        variation = PublicVariation.query.get(form.public_variation.data)
        quantity = form.quantity.data
        
         # Check if an item for this variation already exists in the order
        existing_item = next((item for item in customer_order.order_items if item.public_variation_id == variation.id), None)

        if existing_item:
            # LOGIC FOR UPDATING AN EXISTING ITEM
            new_quantity = existing_item.quantity + quantity
            is_available, message = check_availability(variation, new_quantity, customer_order.start_date, customer_order.end_date)
            if not is_available:
                 flash(f"Cannot add quantity: {message}", "danger")
            else:
                existing_item.quantity = new_quantity
                flash('Updated quantity for existing item.', 'info')
        else:
            # LOGIC FOR ADDING A NEW ITEM
            is_available, message = check_availability(variation, quantity, customer_order.start_date, customer_order.end_date)
            if not is_available:
                flash(f"Cannot add item: {message}", "danger")
            else:
                # 1. Calculate the correct price BEFORE creating the object.
                price_data = calculate_item_price_and_total(
                    variation.id,
                    quantity,
                    customer_order.order_type,
                    customer_order.start_date,
                    customer_order.end_date
                )
                
                # 2. Create the new item with the correct, final prices.
                new_item = OrderItem(
                    customer_order=customer_order,
                    public_variation_id=variation.id,
                    quantity=quantity,
                    price_per_item=price_data['price_per_item'],
                    line_total=price_data['line_total']
                )
                db.session.add(new_item)
                flash('Added new item to the order.', 'success')
        
        # --- Recalculate and commit ONCE ---
        # Whether we added a new item or updated a quantity, we recalculate the whole order.
        # This handles all updates to item prices and order totals in the session.
        totals = calculate_order_totals(customer_order)
        
        # Update the parent CustomerOrder with the new totals.
        customer_order.subtotal_net = totals['subtotal_net']
        customer_order.tax_amount = totals['tax_amount']
        customer_order.grand_total = totals['grand_total']
        
        # A single commit saves the new/updated item, all updated line totals,
        # and the updated order totals in one transaction. No refresh needed.
        db.session.commit()

        return redirect(url_for('sales.add_items_to_order', customer_order_id=customer_order_id))
    
    # --- Final render logic ---
    discount_form = DiscountForm(obj=customer_order)
    return render_template(
        'sales/add_items_to_order.html', 
        form=form, 
        customer_order=customer_order,
        variation_map_json=json.dumps(variation_map),
        discount_form=discount_form
    )


@sales_bp.route('/<int:customer_order_id>/remove-item/<int:order_item_id>', methods=['POST'])
@login_required
@role_required('admin', 'manager')
def remove_item_from_order(customer_order_id, order_item_id):
    order = CustomerOrder.query.get_or_404(customer_order_id)
    item = OrderItem.query.get_or_404(order_item_id)

    if item.customer_order_id != order.id:
        abort(403)
        
    if order.status != 'Draft':
        flash("Items can only be removed from orders in 'Draft' status.", "warning")
        return redirect(url_for('sales.add_items_to_order', customer_order_id=order.id))

    try:
        db.session.delete(item)
        
        # Recalculate totals after deleting the item
        totals = calculate_order_totals(order)
        order.subtotal_net = totals['subtotal_net']
        order.tax_amount = totals['tax_amount']
        
        # Check if the existing discount is still valid against the new subtotal.
        if order.discount_amount and order.discount_amount > order.subtotal_net:
            flash(f"The previous discount of €{order.discount_amount:.2f} was larger than the new subtotal and has been removed.", "warning")
            order.discount_amount = None
            order.discount_reason = None
            # Recalculate the grand total again without the discount.
            order.grand_total = order.subtotal_net + order.tax_amount
        else:
            # If the discount is still valid, use the recalculated grand total.
            order.grand_total = totals['grand_total']
        
        db.session.commit()
        flash("Item removed from order.", "success")
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error removing item {order_item_id}: {e}")
        flash("An error occurred while removing the item.", "danger")

    return redirect(url_for('sales.add_items_to_order', customer_order_id=customer_order_id))


@sales_bp.route('/<int:customer_order_id>/apply-discount', methods=['POST'])
@login_required
@role_required('admin', 'manager')
def apply_discount(customer_order_id):
    """Applies a manual discount to a CustomerOrder."""
    customer_order = CustomerOrder.query.get_or_404(customer_order_id)
    form = DiscountForm()

    if form.validate_on_submit():
        discount = form.discount_amount.data
        
        # Validation: Discount cannot be greater than the subtotal
        if discount > customer_order.subtotal_net:
            flash("Error: Discount amount cannot be greater than the order subtotal.", "danger")
        else:
            customer_order.discount_amount = discount
            customer_order.discount_reason = form.discount_reason.data

            # Recalculate the grand total
            new_grand_total = (
                (customer_order.subtotal_net or Decimal('0.00')) +
                (customer_order.tax_amount or Decimal('0.00')) +
                (customer_order.shipping_cost or Decimal('0.00')) -
                (customer_order.discount_amount or Decimal('0.00'))
            )
            customer_order.grand_total = new_grand_total
            
            db.session.commit()
            flash("Discount applied successfully.", "success")
    else:
        # If form validation fails, flash the errors
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in {field.replace('_', ' ').title()}: {error}", "danger")

    return redirect(url_for('sales.add_items_to_order', customer_order_id=customer_order_id))


@sales_bp.route('/<int:customer_order_id>/confirm', methods=['POST'])
@login_required
@role_required('admin', 'manager')
def confirm_order(customer_order_id):
    """
    Confirms a 'Draft' order, changing its status to 'Pending Fulfillment'
    after re-validating that all items are still in stock.
    """
    order = CustomerOrder.query.get_or_404(customer_order_id)

    if order.status != 'Draft':
        flash("Only orders in 'Draft' status can be confirmed.", "warning")
        return redirect(url_for('sales.add_items_to_order', customer_order_id=order.id))
    
    if not order.order_items:
        flash("Cannot confirm an order with no items.", "danger")
        return redirect(url_for('sales.add_items_to_order', customer_order_id=order.id))

    try:
        # --- Re-validate availability for ALL items at the moment of confirmation ---
        for item in order.order_items:
            is_available, message_or_stock = check_availability(
                item.public_variation,
                item.quantity,
                order.start_date,
                order.end_date,
                exclude_order_id=order.id # Exclude this order from the check
            )
            if not is_available:
                raise ValueError(f"Confirmation failed: {message_or_stock} for item '{item.public_variation.public_product.name}'.")

        # If all items are available, confirm the order
        order.status = 'Pending Fulfillment'
        db.session.commit()
        flash("Order has been confirmed and stock is now reserved.", "success")
        return redirect(url_for('sales.list_unfulfilled_orders'))

    except ValueError as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for('sales.add_items_to_order', customer_order_id=order.id))


@sales_bp.route('/<int:customer_order_id>/revert-to-draft', methods=['POST'])
@login_required
@role_required('admin', 'manager')
def revert_to_draft(customer_order_id):
    """
    Reverts a 'Pending Fulfillment' order back to 'Draft' status, releasing
    the virtual stock allocation and allowing edits and cancelling the order.
    """
    order = CustomerOrder.query.get_or_404(customer_order_id)

    # You can only revert an order that is pending and has no physical bookings yet.
    if order.status != 'Pending Fulfillment':
        flash("Only orders in 'Pending Fulfillment' status can be reverted to a draft.", "warning")
        return redirect(url_for('sales.list_unfulfilled_orders'))

    # Double-check that no items have accidentally been fulfilled
    if any(item.booking for item in order.order_items):
        flash("Cannot revert an order that has already been partially or fully fulfilled.", "danger")
        return redirect(url_for('sales.list_unfulfilled_orders'))

    try:
        order.status = 'Draft'
        db.session.commit()
        flash(f"Order #{order.id} has been reverted to a draft. Stock has been released and you can now edit the items.", "success")
        # Redirect the user to the edit page where they can now make changes
        return redirect(url_for('sales.add_items_to_order', customer_order_id=order.id))
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error reverting order {customer_order_id} to draft: {e}")
        flash("An error occurred while reverting the order.", "danger")
        return redirect(url_for('sales.list_unfulfilled_orders'))


@sales_bp.route('/<int:customer_order_id>/cancel', methods=['POST'])
@login_required
@role_required('admin', 'manager')
def cancel_order(customer_order_id):
    """Cancels/Deletes a CustomerOrder, but only if it's a Draft."""
    order = CustomerOrder.query.get_or_404(customer_order_id)

    if order.status != 'Draft':
        flash("Only orders in 'Draft' status can be canceled.", "warning")
        return redirect(url_for('sales.list_unfulfilled_orders'))

    try:
        # SQLAlchemy's cascade="all, delete-orphan" will automatically delete child OrderItems
        db.session.delete(order)
        db.session.commit()
        flash(f"Draft Order #{order.id} has been canceled and deleted.", "success")
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error canceling order {customer_order_id}: {e}")
        flash("An error occurred while canceling the order.", "danger")

    return redirect(url_for('sales.list_unfulfilled_orders'))


@sales_bp.route('/unfulfilled')
@login_required
@role_required('admin', 'manager')
def list_unfulfilled_orders():
    """Displays a list of all customer orders that need to be fulfilled."""
    # Eagerly load customer data for display
    orders_to_fulfill = CustomerOrder.query.options(
        joinedload(CustomerOrder.customer)
    ).filter(
        CustomerOrder.status.in_(['Pending Fulfillment', 'Partially Fulfilled', 'Draft'])
    ).order_by(CustomerOrder.created_at.desc()).all()
    
    return render_template('sales/unfulfilled_list.html', orders=orders_to_fulfill)


@sales_bp.route('/<int:customer_order_id>/fulfill', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'manager')
def fulfill_order(customer_order_id):
    customer_order = CustomerOrder.query.get_or_404(customer_order_id)

    form = AssignUnitsForm()

    if form.validate_on_submit():
        try:
            items_to_process = [item for item in customer_order.order_items if not item.booking]
            
            # --- VALIDATION PHASE ---
            for item in items_to_process:
                selected_unit_ids = {int(uid) for uid in request.form.getlist(f'item_{item.id}_units') if uid}
                
                if customer_order.order_type == 'rental' and len(selected_unit_ids) != item.quantity:
                    raise ValueError(f"For item '{item.public_variation.manufacturing_product.name}', you must select exactly {item.quantity} units.")
                
                available_units_for_item = get_selectable_units_for_item(item)
                available_ids = {unit.unit_id for unit in available_units_for_item}

                if not selected_unit_ids.issubset(available_ids):
                    raise ValueError(f"One or more selected units for '{item.public_variation.manufacturing_product.name}' are no longer available.")

            # --- FULFILLMENT PHASE ---
            if customer_order.order_type == 'rental':
                # 1. Aggregate all selected unit IDs from all items ONCE.
                all_selected_unit_ids = set()
                for item in items_to_process:
                    item_unit_ids = {int(uid) for uid in request.form.getlist(f'item_{item.id}_units') if uid}
                    all_selected_unit_ids.update(item_unit_ids)

                # Only create a booking if units were actually selected for fulfillment.
                if all_selected_unit_ids:
                    all_units_to_book = ProductUnit.query.filter(ProductUnit.unit_id.in_(all_selected_unit_ids)).all()
                    
                    # 2. Create booking.
                    new_booking = Booking(
                        start_date=customer_order.start_date,
                        end_date=customer_order.end_date,
                        units=all_units_to_book
                    )
                    db.session.add(new_booking)

                    # 3. Assign booking to all processed items.
                    for item in items_to_process:
                        item.booking = new_booking
            
            else: # Sale Order logic
                for item in items_to_process:
                    selected_unit_ids = {int(uid) for uid in request.form.getlist(f'item_{item.id}_units') if uid}
                    if not selected_unit_ids: continue
                    units_to_sell = ProductUnit.query.filter(ProductUnit.unit_id.in_(selected_unit_ids)).all()
                    for unit in units_to_sell:
                        unit.condition = 'sold'

            # --- Update order status  ---
            if customer_order.order_type == 'sale':
                customer_order.status = 'Sale Completed'
            else: # Rental
                is_fully_fulfilled = all(item.booking is not None for item in customer_order.order_items)
                customer_order.status = 'Fulfilled' if is_fully_fulfilled else 'Partially Fulfilled'

            db.session.commit()
            flash("Order has been successfully fulfilled.", "success")
            return redirect(url_for('sales.list_bookings')) # Redirecting to bookings list is better here

        except ValueError as e:
            db.session.rollback()
            flash(str(e), "danger")
            return redirect(url_for('sales.fulfill_order', customer_order_id=customer_order_id))

    # For the GET request, pass the helper to the template
    return render_template(
        'sales/fulfill_order.html', 
        customer_order=customer_order,
        form=form,
        get_available_units=get_selectable_units_for_item
    )


@sales_bp.route('/bookings')
@login_required
@role_required('admin', 'manager')
def list_bookings():
    """Renders a page showing a list of all active bookings."""
    
    # Eagerly load all the nested data the template will need in one efficient query
    all_bookings = Booking.query.options(
        joinedload(Booking.units).joinedload(ProductUnit.space),
        joinedload(Booking.order_items).joinedload(OrderItem.customer_order).joinedload(CustomerOrder.customer),
        joinedload(Booking.order_items).joinedload(OrderItem.public_variation).joinedload(PublicVariation.public_product),
        joinedload(Booking.order_items).joinedload(OrderItem.public_variation).joinedload(PublicVariation.manufacturing_product)
    ).order_by(Booking.start_date.desc()).all()
    
    return render_template('sales/list_bookings.html', bookings=all_bookings)


@sales_bp.route('/bookings/<int:booking_id>/cancel', methods=['POST'])
@login_required
@role_required('admin', 'manager')
def cancel_booking(booking_id):
    """
    Cancels a booking, unlinking it from all its associated OrderItems and
    reverting the parent CustomerOrder's status.
    """
    # Eagerly load the relationships we'll need to modify
    booking = Booking.query.options(
        joinedload(Booking.order_items).joinedload(OrderItem.customer_order)
    ).get_or_404(booking_id)

    try:
        # Check if this booking is actually linked to any order items
        if booking.order_items:
            # All items in a booking will belong to the same order.
            # We can safely get the parent order from the first item.
            customer_order = booking.order_items[0].customer_order

            # Unlink the booking from ALL associated order items
            for item in booking.order_items:
                item.booking = None
            
            # Now delete the booking itself
            db.session.delete(booking)
            
            # Check if any OTHER items in this order are still fulfilled (have a booking)
            # This check is now robust because we've already unlinked the current items.
            any_other_items_fulfilled = any(item.booking is not None for item in customer_order.order_items)
            
            if any_other_items_fulfilled:
                customer_order.status = 'Partially Fulfilled'
            else:
                # If no other items are fulfilled, the whole order is back to pending.
                customer_order.status = 'Pending Fulfillment'

            flash_message = f"Booking #{booking_id} has been canceled. The associated order item(s) are now pending fulfillment."
        
        else:
            # If the booking was an orphan (no order items), just delete it
            db.session.delete(booking)
            flash_message = f"Orphaned Booking #{booking_id} has been deleted."

        db.session.commit()
        flash(flash_message, "success")

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error canceling booking #{booking_id}: {e}")
        flash("An error occurred while canceling the booking.", "danger")

    return redirect(url_for('sales.list_bookings'))


@sales_bp.route('/availability-summary') 
def get_availability_summary():
    """
    Gathers all product data, structured for WooCommerce, by calling dedicated helpers.
    This is an internal endpoint for the sync script.
    """
    try:
        products_payload = build_woocommerce_payload()
        return jsonify(products_payload)
    except Exception as e:
        logging.error(f"❌ CRITICAL ERROR building WooCommerce payload: {e}")
        logging.exception(e) 
        return jsonify({"error": "An internal error occurred."}), 500
    

@sales_bp.route('/debug-sync-payload')
def debug_sync_payload():
    """A temporary route to view the raw JSON payload for WC sync."""
    payload = build_woocommerce_payload()
    
    # The `json.dumps` with an indent makes it easy to read in the browser
    pretty_payload = json.dumps(payload, indent=2, default=str) # `default=str` handles Decimals
    
    # Return it as plain text wrapped in <pre> for nice formatting
    return f"<pre>{pretty_payload}</pre>"


@sales_bp.route('/public-products/run-sync', methods=['POST'])
@login_required
@role_required('admin')
def run_full_sync():
    """
    Triggers the command-line sync script (sync_to_wp.py) as a
    background process.
    """
    try:
        # Get the path to the Python executable that is currently running the Flask app.
        # This is more robust than just assuming 'python3'.
        python_executable = sys.executable
        
        # Get the root directory of your application project.
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        
        # Construct the full path to your sync script.
        script_path = os.path.join(project_root, 'app', 'sync_to_wp.py')

        # Use subprocess.Popen to run the script as a new, independent process.
        # We don't wait for it to finish.
        print(f"--- Triggering sync script: {python_executable} {script_path} ---")
        subprocess.Popen([python_executable, script_path])

        flash("Sync process started in the background. It may take a few moments for changes to appear in WooCommerce.", "info")

    except Exception as e:
        # Log the error for debugging.
        logging.error(f"Failed to start sync process: {e}")
        flash(f"Error: Could not start the sync process. Check the server logs for details.", "danger")

    # Immediately redirect the user back to the product list.
    return redirect(url_for('sales.view_public_products'))


@sales_bp.route('/customers')
@login_required
@role_required('admin', 'manager')
def view_customers():
    """Main hub for viewing all customers."""
    # Eagerly load the orders to easily show an "Order Count" in the table
    customers = Customer.query.options(db.joinedload(Customer.orders)).order_by(Customer.last_name).all()
    return render_template('sales/customers/view_customers.html', customers=customers)


@sales_bp.route('/customers/<int:customer_id>')
@login_required
@role_required('admin', 'manager')
def customer_dashboard(customer_id):
    """
    Detailed dashboard for a single customer. Shows their info, addresses, and order history.
    """
    customer = Customer.query.options(
        db.joinedload(Customer.addresses),
        db.joinedload(Customer.orders).joinedload(CustomerOrder.order_items)
    ).get_or_404(customer_id)
    
    return render_template('sales/customers/customer_dashboard.html', customer=customer)


@sales_bp.route('/customers/manage/', defaults={'customer_id': None}, methods=['GET', 'POST'])
@sales_bp.route('/customers/manage/<int:customer_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'manager')
def manage_customer(customer_id):
    """Creates or edits core customer details."""
    customer = Customer.query.get_or_404(customer_id) if customer_id else None
    form = CustomerForm(obj=customer)
    if customer:
        form.id.data = customer.id

    if form.validate_on_submit():
        is_new = not customer
        if is_new:
            customer = Customer()
            db.session.add(customer)

        customer.first_name = form.first_name.data
        customer.last_name = form.last_name.data
        customer.email = form.email.data
        customer.phone = form.phone.data

        db.session.commit()
        flash(f"Customer '{customer.first_name} {customer.last_name}' saved.", "success")
        return redirect(url_for('sales.customer_dashboard', customer_id=customer.id))

    return render_template('sales/customers/manage_customer.html', form=form, customer=customer)


@sales_bp.route('/customers/<int:customer_id>/address/manage/', defaults={'address_id': None}, methods=['GET', 'POST'])
@sales_bp.route('/customers/<int:customer_id>/address/manage/<int:address_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'manager')
def manage_address(customer_id, address_id):
    """Adds or edits an address for a specific customer."""
    customer = Customer.query.get_or_404(customer_id)
    address = Address.query.get_or_404(address_id) if address_id else None
    
    # Security check: Ensure the address belongs to this customer
    if address and address.customer_id != customer.id:
        abort(403)

    form = AddressForm(obj=address)

    if form.validate_on_submit():
        if not address:
            address = Address(customer_id=customer.id)
            db.session.add(address)

        form.populate_obj(address) # Quick way to map form data to an object
        
        db.session.commit()
        flash("Address saved successfully.", "success")
        return redirect(url_for('sales.customer_dashboard', customer_id=customer.id))

    return render_template('sales/customers/manage_address.html', form=form, customer=customer, address=address)