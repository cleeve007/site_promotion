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

    # Property
    adresse = db.Column(db.String(300), nullable=True)
    ville = db.Column(db.String(120), nullable=True)
    code_postal = db.Column(db.String(20), nullable=True)

    prix = db.Column(db.Integer, nullable=True)
    surface_habitable = db.Column(db.Integer, nullable=True)
    nombre_pieces = db.Column(db.Integer, nullable=True)

    description = db.Column(db.Text, nullable=True)
