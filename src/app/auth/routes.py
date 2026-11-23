# src/app/auth/routes.py
import secrets

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db
from app.permissions import role_required
from .models import User, UserRights
from .forms import LoginForm, CreateUserForm, SetPasswordForm

auth_bp = Blueprint('auth', __name__)



@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # If a user is already logged in, redirect them to the homepage.
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
        
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        
        if user and user.check_password(form.password.data):
            login_user(user)
            # Redirect to the page the user was trying to access before being sent to login.
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('main.home'))
        else:
            flash('Login Unsuccessful. Please check email and password.', 'danger')
    
    return render_template('auth/login.html', form=form, title='Login')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/users/manage-roles', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def manage_roles():
    if request.method == 'GET':
        users = User.query.order_by(User.user_name).all()
        roles = UserRights.query.order_by(UserRights.id).all()
        return render_template('auth/manage_roles.html', users=users, roles=roles)

    if request.method == 'POST':
        user_id = request.form.get('user_id', type=int)
        
        new_role_id = request.form.get('new_role_id', type=int)

        print(f"--- Received POST for manage_roles ---")
        print(f"User ID from form: {user_id}")
        print(f"New Role ID from form: {new_role_id}")
        print(f"------------------------------------")

        user = db.session.get(User, user_id)
        if user and new_role_id:
            user.user_rights_id = new_role_id
            db.session.commit()
            flash(f"The role for user '{user.user_name}' has been updated.", 'success')
        else:
            flash('Error: User or role not found.', 'danger')
        
        return redirect(url_for('auth.manage_roles'))


@auth_bp.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for('auth.manage_roles'))

    # Prevent an admin from deleting themselves
    if user.id == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for('auth.manage_roles'))

    db.session.delete(user)
    db.session.commit()
    flash(f"User '{user.user_name}' has been deleted.", 'success')
    
    return redirect(url_for('auth.manage_roles'))


@auth_bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def create_user():
    """
    Handles the creation of a new user by an administrator.
    """
    form = CreateUserForm()
    form.role.choices = [
        (r.id, r.rights.capitalize()) for r in UserRights.query.order_by('rights')
    ]

    if form.validate_on_submit():
        try:
            # 1. Create the user object without a password
            new_user = User(
                user_name=form.user_name.data,
                email=form.email.data,
                user_rights_id=form.role.data
            )
            
            # 2. Generate a secure, URL-safe token for the setup link
            setup_token = secrets.token_urlsafe(32)
            
            # 3. Store the HASH of the token and its expiration in the database
            new_user.password_reset_token = generate_password_hash(setup_token)
            new_user.password_reset_expiration = datetime.utcnow() + timedelta(days=1) # Link is valid for 1 day
            
            db.session.add(new_user)
            db.session.commit()

            # 4. Generate the full setup link to display to the admin
            setup_link = url_for('auth.set_password', token=setup_token, _external=True)
            
            # 5. Flash a success message that includes the link
            flash(f"User '{new_user.user_name}' created successfully. Please send them this one-time setup link: {setup_link}", "success")
            
            return redirect(url_for('auth.manage_roles'))
            
        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred while creating the user: {e}", "danger")

    return render_template('auth/create_user.html', form=form, title="Create New User")


@auth_bp.route('/set-password/<token>', methods=['GET', 'POST'])
def set_password(token):
    """
    Allows a new user to set their password for the first time using a secure token.
    """
    # 1. Find the user by the HASH of the token.
    user = None
    all_users = User.query.filter(User.password_reset_token.isnot(None)).all()
    for u in all_users:
        if check_password_hash(u.password_reset_token, token):
            user = u
            break

    # 2. Validate the user and the token's expiration.
    if not user or user.password_reset_expiration < datetime.utcnow():
        flash("This password setup link is invalid or has expired.", "danger")
        return redirect(url_for('auth.login'))

    form = SetPasswordForm()
    if form.validate_on_submit():
        try:
            # 3. Set the new password.
            user.set_password(form.password.data)
            
            # 4. Invalidate the token to make the link single-use.
            user.password_reset_token = None
            user.password_reset_expiration = None
            
            db.session.commit()
            
            flash("Your password has been set successfully. You can now log in.", "success")
            return redirect(url_for('auth.login'))
            
        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred: {e}", "danger")

    return render_template('auth/set_password.html', form=form, title="Set Your Password")


@auth_bp.route('/users/reset-password-link/<int:user_id>', methods=['POST'])
@login_required
@role_required('admin')
def reset_password(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for('auth.manage_roles'))

    try:
        # 1. Generate a new token
        setup_token = secrets.token_urlsafe(32)
        
        # 2. Update the user record
        user.password_reset_token = generate_password_hash(setup_token)
        # Set shorter expiration for resets (e.g., 24 hours)
        user.password_reset_expiration = datetime.utcnow() + timedelta(hours=24) 
        
        db.session.commit()

        # 3. Generate the link (Reusing your existing set_password route)
        reset_link = url_for('auth.set_password', token=setup_token, _external=True)
        
        # 4. Show the link to the admin
        flash(f"Password reset link for '{user.user_name}': {reset_link}", "warning")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error generating link: {e}", "danger")

    return redirect(url_for('auth.manage_roles'))