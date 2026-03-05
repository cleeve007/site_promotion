from __future__ import annotations

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class PropertySubmission(db.Model):
    __tablename__ = "property_submissions"

    id = db.Column(db.Integer, primary_key=True)

    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), nullable=False)

    # Contact
    nom = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    telephone = db.Column(db.String(40), nullable=False)

    # Address (user input + GeoPF selection)
    adresse = db.Column(db.String(300), nullable=True)  # raw input
    adresse_fulltext = db.Column(db.String(400), nullable=True)  # selected suggestion
    adresse_city = db.Column(db.String(120), nullable=True)
    adresse_zipcode = db.Column(db.String(20), nullable=True)
    adresse_kind = db.Column(db.String(80), nullable=True)
    adresse_source = db.Column(db.String(80), nullable=True)
    adresse_x = db.Column(db.Float, nullable=True)
    adresse_y = db.Column(db.Float, nullable=True)

    # Property
    prix = db.Column(db.Integer, nullable=True)

    description = db.Column(db.Text, nullable=True)
