# isi_storage/app/utility/booking_logic.py

import logging
from datetime import datetime
from app.extensions import db
from app.sales.models import Booking

def create_unfulfilled_booking_from_order(order_data: dict) -> bool:
    """
    Creates a new, UNFULFILLED booking record from a WooCommerce order.
    This does NOT assign specific units. It only records the demand.

    Args:
        order_data (dict): A dictionary containing order details.

    Returns:
        bool: True if the booking was created successfully, False otherwise.
    """
    try:
        start_date = datetime.strptime(order_data['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(order_data['end_date'], '%Y-%m-%d').date()
        rental_items = order_data['rental_items'] # This is {isi_id: qty}

        # We assume an order only contains one type of rental product for now.
        # This can be expanded later if needed.
        if len(rental_items) != 1:
            logging.warning(f"Order #{order_data['order_id']} contains multiple rental types, which is not yet supported. Skipping.")
            return False

        # Get the single product ID and quantity from the items.
        isi_product_id = int(list(rental_items.keys())[0])
        quantity = int(list(rental_items.values())[0])

        new_booking = Booking(
            product_id=isi_product_id,
            quantity=quantity, 
            start_date=start_date,
            end_date=end_date,
            is_confirmed=True
        )

        db.session.add(new_booking)
        db.session.commit()
        logging.info(f"✅ Successfully created UNFULFILLED Booking #{new_booking.booking_id} for WC Order #{order_data['order_id']}.")
        return True

    except Exception as e:
        logging.error(f"❌ CRITICAL ERROR creating unfulfilled booking for Order #{order_data.get('order_id')}: {e}")
        db.session.rollback()
        return False