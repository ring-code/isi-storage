# src/app/auth/models.py

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db, login_manager
from app.utility.secrets_helper import get_secret
import os


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class UserRights(db.Model):
    __tablename__ = 'user_rights'
    __table_args__ = {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    id = db.Column(db.Integer, primary_key=True)
    rights = db.Column(db.String(50), nullable=False, unique=True)

    @staticmethod
    def insert_default_roles():
        default_roles = ['admin', 'manager', 'user']
        for role in default_roles:
            if not UserRights.query.filter_by(rights=role).first():
                db.session.add(UserRights(rights=role)) 


class User(UserMixin, db.Model):
    __tablename__ = 'user'
    __table_args__ = {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    id = db.Column(db.Integer, primary_key=True)
    user_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=True) 
    user_rights_id = db.Column(db.Integer, db.ForeignKey('user_rights.id'))
    password_reset_token = db.Column(db.String(255), nullable=True, unique=True)
    password_reset_expiration = db.Column(db.DateTime, nullable=True)

    # Insert default admin user
    @staticmethod
    def insert_default_admin():
        """
        Inserts the default admin user on the first run, using credentials
        from environment variables. Skips if the admin email already exists.
        """
        # 1. Read the credentials from environment variables.
        admin_email = os.getenv('DEFAULT_ADMIN_EMAIL')
        admin_user_name = os.getenv('DEFAULT_ADMIN_USER')
        admin_password = get_secret('default_admin_password')

        # 2. Safety check: If the variables are not set, do nothing.
        if not all([admin_email, admin_user_name, admin_password]):
            print("WARNING: Default admin credentials not found in environment variables. Skipping admin creation.")
            return

        # 3. Check if an admin with this email already exists.
        if not User.query.filter_by(email=admin_email).first():
            
            # Find the 'admin' role. Assumes roles are already seeded.
            admin_role = UserRights.query.filter_by(rights='admin').first()
            if not admin_role:
                print("ERROR: 'admin' role not found in database. Cannot create admin user.")
                return

            # 4. Create the new admin user object.
            admin_user = User(
                user_name=admin_user_name,
                email=admin_email,
                user_rights_id=admin_role.id
            )
            admin_user.set_password(admin_password)
            
            db.session.add(admin_user)
            print(f"✅ Default admin user '{admin_user_name}' created with email '{admin_email}'.")
        else:
            print(f"Admin user with email '{admin_email}' already exists. Skipping creation.")

    user_rights = db.relationship("UserRights", backref='users')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')
        

    def check_password(self, password):
        # Safety check: if a user has no password set yet, checking should always fail.
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return str(self.id)

    def __repr__(self):
        return f'<User {self.user_name}>'
    
    def is_admin(self):
        return self.user_rights and self.user_rights.rights == 'admin'

    def is_manager(self):
        return self.user_rights and self.user_rights.rights == 'manager'
    
    def is_user(self):
        return self.user_rights and self.user_rights.rights == 'user'


    

