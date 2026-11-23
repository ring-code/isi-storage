#!/bin/sh

# this needs to be executable: chmod +x ./isi_storage/entrypoint.sh

# Exit immediately if any command fails
set -e

# how to make the container startup in maintenance mode, very useful for some SQLAlchemy errors:
# comment out everything but the set -e above and the line below
# tail -f /dev/null

# This is required by the `flask` command
export FLASK_APP=run:app

echo "--- Running initial database setup (migrations and seeding) ---"
flask seed init

# After the script finishes successfully, start the main application.
echo "--- Starting Gunicorn server and background scheduler ---"
python3 run_scheduler.py &
exec "$@"