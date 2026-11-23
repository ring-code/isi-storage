# app/inventory/models.py
from datetime import datetime, timezone
from uuid import uuid4
from app.extensions import db
from sqlalchemy.dialects.postgresql import JSONB



class AssetTag(db.Model):
    __tablename__ = 'asset_tag'
    id = db.Column(db.Integer, primary_key=True) 
    # The unique value for the tag, generated as a UUID string.
    code_value = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid4()), index=True)   
    # The type of tag
    tag_type = db.Column(db.String(50), nullable=False, default='QR_CODE')  
    # The lifecycle status of the tag.
    status = db.Column(db.String(50), nullable=False, default='unassigned', index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    # The foreign key link to the ProductUnit. This is nullable because a tag can exist before it's assigned.
    unit_id = db.Column(db.Integer, db.ForeignKey('product_unit.unit_id'), nullable=True, unique=True)
    
    def __repr__(self):
        return f'<AssetTag {self.code_value}>'


class Space(db.Model):
    __tablename__ = 'space'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False) 
    description = db.Column(db.String(255), nullable=True) 


class DamageTemplate(db.Model):
    __tablename__ = 'damage_template'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    
    # This stores the filename of the template to be included
    visualization_component = db.Column(db.String(100), nullable=False, unique=True)
    
    # This creates the one-to-many relationship back to the Products that use this template
    products = db.relationship("Product", back_populates='damage_template')

    def __repr__(self):
        return f'<DamageTemplate {self.name}>'

    @staticmethod
    def insert_default_templates():
        """Inserts the baseline default damage templates if they do not exist."""
        # Check by visualization_component (rather than name) just in case
        # an admin renames it in the UI later.
        if not DamageTemplate.query.filter_by(visualization_component='text_list').first():
            default_template = DamageTemplate(
                name='Standard Text-Only',
                description='A simple list for recording damages with no visual aid.',
                visualization_component='text_list'
            )
            db.session.add(default_template)
            print("✅ Default DamageTemplate 'Standard Text-Only' queued for creation.")


class Damage(db.Model):
    __tablename__ = 'damage'
    __table_args__ = {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    damage_id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(db.Integer, db.ForeignKey('product_unit.unit_id'))
    description = db.Column(db.String(255))
    severity = db.Column(db.String(50))
    recorded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    x_coordinate = db.Column(db.Float, nullable=True)
    y_coordinate = db.Column(db.Float, nullable=True)
    product_unit = db.relationship("ProductUnit", backref='damages')
    dmg_metadata = db.Column(JSONB, nullable=True)