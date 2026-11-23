# src/app/auth/forms.py

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField
from wtforms.validators import DataRequired, Email, EqualTo, ValidationError, Length
from .models import User


class CreateUserForm(FlaskForm):
    """
    Form for an administrator to create a new user account.
    Password is not set here; it's handled via a secure setup link.
    """
    user_name = StringField(
        'Username',
        validators=[DataRequired(), Length(min=3, max=100)]
    )
    email = StringField(
        'Email Address',
        validators=[DataRequired(), Email()]
    )
    # The choices for this field will be populated dynamically in the route.
    role = SelectField(
        'User Role',
        coerce=int, # The value of each choice will be the role's ID
        validators=[DataRequired(message="You must assign a role.")]
    )
    submit = SubmitField('Create User and Generate Setup Link')

    def validate_email(self, email):
        """Checks if the email is already in use."""
        if User.query.filter_by(email=email.data).first():
            raise ValidationError('This email address is already registered.')

    def validate_user_name(self, user_name):
        """Checks if the username is already taken."""
        if User.query.filter_by(user_name=user_name.data).first():
            raise ValidationError('This username is already taken.')



class SetPasswordForm(FlaskForm):
    """
    Form for a new user to set their password for the first time via a secure link.
    """
    password = PasswordField(
        'New Password',
        validators=[DataRequired(), Length(min=8, message="Password must be at least 8 characters long.")]
    )
    confirm_password = PasswordField(
        'Confirm New Password',
        validators=[
            DataRequired(),
            EqualTo('password', message='Passwords must match.')
        ]
    )
    submit = SubmitField('Set Password and Login')



class LoginForm(FlaskForm):
    """
    Standard login form.
    """
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Log In')