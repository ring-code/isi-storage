# app/inventory/forms.py

from flask_wtf import FlaskForm
from wtforms import SubmitField, TextAreaField, SelectField,  HiddenField, StringField
from wtforms.validators import DataRequired, Optional, ValidationError
from .models import Space


class AssetTagActionForm(FlaskForm):
    """A simple form with only a CSRF token for secure POST actions."""
    submit = SubmitField() # The button's text will be set in the template


class DamageForm(FlaskForm):
    description = TextAreaField('Description', validators=[DataRequired()])
    severity = SelectField('Severity', choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')], validators=[DataRequired()])
    x_coordinate = HiddenField('X Coordinate')
    y_coordinate = HiddenField('Y Coordinate')
    submit = SubmitField('Add Damage')


class SpaceForm(FlaskForm):
    """Form for creating and editing physical storage spaces."""
    name = StringField('Space Name / Location Code', validators=[DataRequired()])
    description = TextAreaField('Description', validators=[Optional()])
    
    submit = SubmitField('Save Space')
    id = HiddenField() # Used for tracking which space is being edited

    def validate_name(self, name):
        """Ensures the space name is unique."""
        query = Space.query.filter(Space.name == name.data)
        if self.id.data:
            # Exclude the current space from the check if editing
            query = query.filter(Space.id != self.id.data)
        if query.first():
            raise ValidationError('A storage space with this name already exists.')