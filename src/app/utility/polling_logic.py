import requests
import os
import logging
from app.utility.order_logic import process_polled_wc_order

def run_polling(app):
    """
    The main polling function that will be run by the scheduler.
    """
    with app.app_context():
        # Get config from the app context
        api_base_url = os.getenv('WP_API_BASE_URL')
        api_key = os.getenv('ISI_SYNC_API_KEY')
        
        # If URL is missing, just return silently or with a mild warning.
        if not api_base_url:
            logging.warning("Skipping polling: WP_API_BASE_URL is not configured.")
            return

        if not api_key:
            logging.error("❌ Polling failed: WP_API_BASE_URL is set, but ISI_SYNC_API_KEY is missing.")
            return

        logging.info("--- Polling for new WooCommerce orders... ---")
        
        # endpoints to poll from
        get_orders_url = f"{api_base_url}/sync/get-new-orders"
        confirm_url = f"{api_base_url}/sync/confirm-orders"

        headers = {'X-ISI-API-KEY': api_key}
        
        try:
            # Get new orders from WordPress
            response = requests.get(get_orders_url, headers=headers)
            response.raise_for_status()
            
            # Only log payload if debugging, otherwise it clogs logs
            # logging.debug(f"Raw payload: {response.text}") 
            
            new_orders = response.json().get('orders', [])

            if not new_orders:
                logging.info("--- No new orders found. ---")
                return

            logging.info(f"--- Found {len(new_orders)} new orders to process. ---")
            
            # Process the orders
            processed_ids = []
            for order_data in new_orders:
                success = process_polled_wc_order(order_data)
                if success:
                    processed_ids.append(order_data['wc_order_id'])

            # Confirm the processed orders back to WordPress
            if processed_ids:
                confirm_response = requests.post(confirm_url, headers=headers, json={'order_ids': processed_ids})
                confirm_response.raise_for_status() 
                logging.info(f"--- Successfully confirmed {len(processed_ids)} orders back to WordPress. ---")

        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Polling failed with a network error: {e}")