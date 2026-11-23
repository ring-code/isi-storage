# src/app/utility/order_logic.py

import logging
from datetime import datetime
from sqlalchemy import func
from app.extensions import db
from app.products.models import ProductUnit
from app.sales.models import RentalGrade, SaleGrade
from app.associations import booking_unit_association
from app.sales.models import Customer, Address, CustomerOrder, OrderItem, Booking, PublicVariation
from app.utility.price_logic import calculate_item_price_and_total


def check_availability(variation: PublicVariation, quantity: int, start_date=None, end_date=None, exclude_order_id: int = None):
    """
    Checks the available stock for a given PublicVariation, considering both
    physical bookings and virtual (unfulfilled) order allocations.

    Args:
        variation: The PublicVariation object being ordered.
        quantity: The integer quantity requested.
        start_date (optional): The start date for a rental period.
        end_date (optional): The end date for a rental period.
        exclude_order_id (optional): The ID of a CustomerOrder to exclude from the
                                     virtual allocation check. This is used when
                                     re-validating an order that is being confirmed.

    Returns:
        A tuple of (bool, str|int): 
        (True, available_stock_count) if successful.
        (False, error_message) if not available.
    """
    if variation.public_product.grade_type == 'rental_grade':
        grade = RentalGrade.query.get(variation.public_product.grade_id)
    elif variation.public_product.grade_type == 'sale_grade':
        grade = SaleGrade.query.get(variation.public_product.grade_id)
    else:
        return False, "Associated grade not found."

    if not grade:
        return False, "Associated grade not found."

    # --- Step 1: Find the total PHYSICAL stock for this variation ---
    total_physical_stock_query = ProductUnit.query.filter(
        ProductUnit.product_id == variation.manufacturing_product_id,
        ProductUnit.condition == 'available'
    )
    if variation.public_product.grade_type == 'rental_grade':
        total_physical_stock_query = total_physical_stock_query.filter(ProductUnit.rental_grade_id == variation.public_product.grade_id)
    else: # Sale Grade
        total_physical_stock_query = total_physical_stock_query.filter(ProductUnit.sale_grade_id == variation.public_product.grade_id)
    
    total_physical_stock = total_physical_stock_query.count()

    # --- Step 2: For SALE orders, the check is simple ---
    if variation.public_product.grade_type == 'sale_grade':
        # Find quantity from other 'Pending Fulfillment' sale orders
        virtual_allocations = db.session.query(func.sum(OrderItem.quantity)).join(CustomerOrder).filter(
            OrderItem.public_variation_id == variation.id,
            CustomerOrder.status == 'Pending Fulfillment'
        ).scalar() or 0
        
        available_stock = total_physical_stock - virtual_allocations
        
        if available_stock >= quantity:
            return True, available_stock
        else:
            return False, f"Only {available_stock} unit(s) are available for sale."

    # --- Step 3: For RENTAL orders, the check is more complex ---
    if not start_date or not end_date:
        return False, "Start and end dates are required for rental availability."

    # A) Find units committed in PHYSICAL bookings during the conflicting period.
    conflicting_bookings_query = Booking.query.join(Booking.units).filter(
        ProductUnit.product_id == variation.manufacturing_product_id,
        ProductUnit.rental_grade_id == variation.public_product.grade_id,
        Booking.end_date >= start_date,
        Booking.start_date <= end_date
    )
    # Get a set of the unique unit IDs that are physically booked
    physically_booked_unit_ids = {unit.unit_id for booking in conflicting_bookings_query.all() for unit in booking.units}

    # B) Find quantity committed in VIRTUAL allocations (other pending orders).
    virtual_allocations_query = db.session.query(func.sum(OrderItem.quantity)).join(CustomerOrder).filter(
        OrderItem.public_variation_id == variation.id,
        CustomerOrder.status == 'Pending Fulfillment',
        CustomerOrder.end_date >= start_date,
        CustomerOrder.start_date <= end_date
    )
    # If we're confirming an order, we must exclude its own items from this check.
    if exclude_order_id:
        virtual_allocations_query = virtual_allocations_query.filter(CustomerOrder.id != exclude_order_id)
    
    virtual_allocations = virtual_allocations_query.scalar() or 0
    
    # C) Calculate final availability.
    # The total number of units that *could* be rented out is the total physical stock.
    # From this pool, some are already physically booked, and others are virtually reserved.
    available_stock = total_physical_stock - len(physically_booked_unit_ids) - virtual_allocations

    if available_stock >= quantity:
        return True, available_stock
    else:
        return False, f"Only {available_stock} unit(s) are available for the selected period."


def get_selectable_units_for_item(order_item: OrderItem) -> list[ProductUnit]:
    """
    Finds all available ProductUnits that can fulfill a given OrderItem.

    This is the core picking logic. It finds all physical units that match
    the ordered variation's SKU and Grade, and for rentals, excludes any
    units that are already booked during the required date range.

    Args:
        order_item: The OrderItem to find available units for.

    Returns:
        A list of available and eligible ProductUnit objects.
    """
    variation = order_item.public_variation
    order = order_item.customer_order

    if not variation or not order:
        return []

    # 1. Base query: Find all physical units that match the variation's
    #    MANUFACTURING SKU and the variation's parent PUBLIC PRODUCT's grade.
    base_query = ProductUnit.query.filter(
        ProductUnit.product_id == variation.manufacturing_product_id,
        ProductUnit.condition == 'available'
    )
    if variation.public_product.grade_type == 'rental_grade':
        base_query = base_query.filter(ProductUnit.rental_grade_id == variation.public_product.grade_id)
    else: # Sale Grade
        base_query = base_query.filter(ProductUnit.sale_grade_id == variation.public_product.grade_id)

    # For sales, the base query is all we need.
    if order.order_type == 'sale':
        return base_query.order_by(ProductUnit.serial_number).all()

    # --- For RENTALS, we must also exclude units with conflicting bookings ---
    if not order.start_date or not order.end_date:
        return []

    # Get the list of all eligible units first.
    all_eligible_units = base_query.all()
    if not all_eligible_units:
        return []
    
    all_eligible_unit_ids = [u.unit_id for u in all_eligible_units]
    
    # Find the IDs of units that are booked during the conflicting period.
    booked_unit_ids = db.session.query(
        booking_unit_association.c.unit_id
    ).join(Booking).filter(
        booking_unit_association.c.unit_id.in_(all_eligible_unit_ids),
        Booking.end_date >= order.start_date,
        Booking.start_date <= order.end_date
    ).distinct().all()
    
    booked_unit_ids_set = {uid for (uid,) in booked_unit_ids}

    # Final list is all eligible units that are NOT in the booked set.
    available_units = [u for u in all_eligible_units if u.unit_id not in booked_unit_ids_set]
    
    # Sort the final list (optional, but good for consistent display)
    available_units.sort(key=lambda u: u.serial_number)
    
    return available_units


def get_rentable_quantity_for_dates(product_id: int, start_date, end_date) -> int:
    """
    Calculates the number of available rental units for a product and date range.
    Returns the total number of physical units for that product in an
    'available' condition.
    """
    # 1. Get total rental supply for this SKU.
    # The supply is the number of its physical units that are currently 'available'.
    total_supply = ProductUnit.query.filter_by(
        product_id=product_id,
        condition='available'
    ).count()

    # 2. Get total demand from unfulfilled rental OrderItems for this SKU.
    demand_from_orders = db.session.query(func.sum(OrderItem.quantity)).join(CustomerOrder).filter(
        OrderItem.product_id == product_id,
        OrderItem.booking_id.is_(None),
        CustomerOrder.order_type == 'rental',
        CustomerOrder.start_date <= end_date,
        CustomerOrder.end_date >= start_date
    ).scalar() or 0
    
    # 3. Get total demand from fulfilled Bookings for this SKU.
    demand_from_bookings = db.session.query(func.count(ProductUnit.unit_id.distinct()))\
        .join(booking_unit_association).join(Booking).filter(
            ProductUnit.product_id == product_id,
            Booking.start_date <= end_date,
            Booking.end_date >= start_date
        ).scalar() or 0
    
    total_demand = demand_from_orders + demand_from_bookings
    
    return max(0, total_supply - total_demand)


def process_polled_wc_order(order_data: dict) -> CustomerOrder | None:
    """
    Orchestrates the creation of a complete CustomerOrder record from a rich
    WooCommerce payload.

    This function handles:
    1. Finding or creating the Customer.
    2. Creating the Billing and Shipping Address records.
    3. Creating the parent CustomerOrder with all financial and method details.
    4. Creating the individual OrderItem records for each rental item.

    Args:
        order_data (dict): The complete order data dictionary from the polling endpoint.

    Returns:
        The newly created CustomerOrder object on success, or None on failure.
    """
    # debug log
    logging.info(f"--- Processing WC Order Payload: {order_data} ---")

    wc_order_id = order_data.get('wc_order_id')
    if not wc_order_id:
        logging.error("Polling Error: Payload missing 'wc_order_id'.")
        return None

    # --- Prevent Duplicates ---
    if CustomerOrder.query.filter_by(wc_order_id=wc_order_id).first():
        logging.warning(f"Skipping duplicate WC Order #{wc_order_id}.")
        return None

    try:
        # --- 1. Handle Customer ---
        customer_data = order_data['customer']
        customer = Customer.query.filter_by(email=customer_data['email']).first()
        if not customer:
            customer = Customer(
                email=customer_data['email'],
                first_name=customer_data['first_name'],
                last_name=customer_data['last_name'],
                phone=customer_data.get('phone')
            )
            db.session.add(customer)
            db.session.flush() # Flush to get the customer ID

        # --- 2. Handle Addresses ---
        billing_addr_data = order_data.get('billing_address', {})
        billing_address = Address(
            customer_id=customer.id,
            first_name=billing_addr_data.get('first_name'),
            last_name=billing_addr_data.get('last_name'),
            address_line_1=billing_addr_data.get('address_1'),
            address_line_2=billing_addr_data.get('address_2'),
            postcode=billing_addr_data.get('postcode'),
            city=billing_addr_data.get('city'),
            state=billing_addr_data.get('state'),
            country=billing_addr_data.get('country')
        )
        db.session.add(billing_address)

        shipping_addr_data = order_data.get('shipping_address', {})
        # If shipping is same as billing, WooCommerce may send empty data.
        if not shipping_addr_data or shipping_addr_data == billing_addr_data:
            shipping_address = billing_address
        else:
            shipping_address = Address(
                customer_id=customer.id,
                first_name=shipping_addr_data.get('first_name'),
                last_name=shipping_addr_data.get('last_name'),
                address_line_1=shipping_addr_data.get('address_1'),
                address_line_2=shipping_addr_data.get('address_2'),
                postcode=shipping_addr_data.get('postcode'),
                city=shipping_addr_data.get('city'),
                state=shipping_addr_data.get('state'),
                country=shipping_addr_data.get('country')
            )
            db.session.add(shipping_address)
        
        db.session.flush() # Flush to get address IDs

        # --- 3. Create the Parent CustomerOrder ---
        new_order = CustomerOrder(
            wc_order_id=wc_order_id,
            customer_id=customer.id,
            billing_address_id=billing_address.id,
            shipping_address_id=shipping_address.id,
            status=order_data.get('status', 'Pending Fulfillment'),
            order_type=order_data.get('order_type'),
            start_date=datetime.strptime(order_data['start_date'], '%Y-%m-%d').date(),
            end_date=datetime.strptime(order_data['end_date'], '%Y-%m-%d').date(),
            subtotal_net=order_data.get('subtotal_net'),
            shipping_cost=order_data.get('shipping_cost'),
            tax_amount=order_data.get('tax_amount'),
            discount_amount=order_data.get('discount_amount'),
            grand_total=order_data.get('grand_total'),
            shipping_method_title=order_data.get('shipping_method_title'),
            payment_method_title=order_data.get('payment_method_title'),
            customer_note=order_data.get('customer_note')
        )
        db.session.add(new_order)
        db.session.flush() # Flush to get the new_order ID

        # --- 4. Create OrderItems ---
        rental_items = order_data.get('rental_items', {})
        for isi_variation_id_str, quantity in rental_items.items():
            
            variation = PublicVariation.query.filter_by(
                isi_variation_id=int(isi_variation_id_str)
            ).first()

            if not variation:
                logging.error(f"CRITICAL: Could not find PublicVariation with ISI hash '{isi_variation_id_str}' for WC Order #{wc_order_id}. Skipping item.")
                continue

            # Call helper to get the correct prices before creating the item.
            price_data = calculate_item_price_and_total(
                variation.id,
                quantity,
                new_order.order_type,
                new_order.start_date,
                new_order.end_date
            )

            new_item = OrderItem(
                customer_order_id=new_order.id,
                public_variation_id=variation.id,
                quantity=quantity,
                price_per_item=price_data['price_per_item'],
                line_total=price_data['line_total']
            )
            db.session.add(new_item)
            logging.info(f"Successfully created OrderItem for variation ID {variation.id} with quantity {quantity}.")
            
        db.session.commit()
        logging.info(f"✅ Successfully created full CustomerOrder #{new_order.id} for WC Order #{wc_order_id}.")
        return new_order

    except Exception as e:
        logging.error(f"❌ CRITICAL ERROR processing WC Order #{wc_order_id}. Rolling back.", exc_info=True)
        db.session.rollback()
        return None


