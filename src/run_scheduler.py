import logging
import os
from apscheduler.schedulers.blocking import BlockingScheduler
from app import create_app
from app.utility.polling_logic import run_polling

# Set up basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logging.getLogger('apscheduler').setLevel(logging.INFO)

# Create the app instance
app = create_app()

# Initialize the scheduler
scheduler = BlockingScheduler()

# Check if the URL exists in the environment
wp_url = os.getenv('WP_API_BASE_URL')

if wp_url and wp_url.strip():
    # Only add the job if the URL is set
    logging.info(f"✅ WP_API_BASE_URL found ({wp_url}). Adding polling job.")
    scheduler.add_job(
        id='run_polling_job',
        func=run_polling, 
        trigger='interval', 
        minutes=1, 
        args=[app]
    )
else:
    # If not set, do NOT add the job.
    logging.warning("⚠️  WP_API_BASE_URL is missing. The polling job will NOT run.")

# Start the scheduler even if it's empty
print("Starting scheduler process...")
try:
    scheduler.start()
except (KeyboardInterrupt, SystemExit):
    print("Scheduler stopped.")
    pass