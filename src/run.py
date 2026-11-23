# /app/run.py

from app import create_app

app = create_app('config.Config')

# just for local testing
if __name__ == '__main__':
    app.run()





