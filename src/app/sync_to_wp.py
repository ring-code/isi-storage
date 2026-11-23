# app/sync_to_wp.py

import os
import requests
from dotenv import load_dotenv

# Load environment variables from the .env file in the current directory
load_dotenv()

# --- CONFIGURATION ---

# The base URL of the local backend API.
BACKEND_API_URL = 'http://localhost:5050'

# The base URL of the WordPress API.
WP_API_BASE_URL = os.getenv('WP_API_BASE_URL')

# The shared secret key.
WORDPRESS_API_KEY = os.getenv('ISI_SYNC_API_KEY')

# Api endpoints to get the summary from and push to.
BACKEND_SUMMARY_ENDPOINT = "/internal/sales/availability-summary"
WORDPRESS_SYNC_ENDPOINT = "/sync/update-availability"

# --- END CONFIGURATION ---

def run_sync():
    """
    Fetches the full availability summary from the local backend
    and pushes it to the WordPress sync endpoint.
    """
    if not WORDPRESS_API_KEY:
        print("❌ ERROR: ISI_SYNC_API_KEY environment variable is not set.")
        return
    if not WP_API_BASE_URL:
        print("❌ ERROR: WP_API_BASE_URL environment variable is not set.")
        return

    # endpoints
    summary_url = f"{BACKEND_API_URL}{BACKEND_SUMMARY_ENDPOINT}"
    wordpress_sync_url = f"{WP_API_BASE_URL}{WORDPRESS_SYNC_ENDPOINT}"
    
    print("Step 1: Fetching availability summary from backend...")
    
    try:
        # Get the data from our own API
        response = requests.get(summary_url)
        response.raise_for_status() # Will raise an error for non-2xx status codes
        products_data = response.json()
        print(f"✅ Successfully fetched data for {len(products_data)} products.")
    except requests.exceptions.RequestException as e:
        print(f"❌ FAILED to fetch data from backend: {e}")
        return

    print("\nStep 2: Pushing data to WordPress...")
    
    headers = {
        'Content-Type': 'application/json',
        'X-ISI-API-KEY': WORDPRESS_API_KEY
    }

    try:
        # Push the data to the WordPress endpoint
        wp_response = requests.post(wordpress_sync_url, headers=headers, json=products_data, timeout=60)
        wp_response.raise_for_status()
        
        result = wp_response.json()
        print("✅ Sync successful!")
        print(f"   Message: {result.get('message')}")
        print("--- LOG ---")
        print(result.get('log'))
        
    except requests.exceptions.RequestException as e:
        print(f"❌ FAILED to push data to WordPress: {e}")
        if 'wp_response' in locals() and hasattr(wp_response, 'text') and wp_response.text:
            print(f"   Server Response: {wp_response.text}")

if __name__ == "__main__":
    run_sync()