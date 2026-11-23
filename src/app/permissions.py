from flask_login import current_user
from functools import wraps
from flask import abort

# Decorator to check access for multiple roles
def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not any(getattr(current_user, f'is_{role}')() for role in roles):
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator