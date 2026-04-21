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

    # Enrichment (async)
    enrich_status = db.Column(db.String(40), nullable=True)  # queued|running|ok|error|skipped
    enrich_error = db.Column(db.Text, nullable=True)
    enriched_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Commune (APIcarto limites-admin)
    commune_insee = db.Column(db.String(10), nullable=True)
    commune_nom = db.Column(db.String(200), nullable=True)

    # PLU (GPU zone-urba)
    plu_typezone = db.Column(db.String(20), nullable=True)  # U / AU / ...
    plu_libelle = db.Column(db.String(80), nullable=True)
    plu_idurba = db.Column(db.String(80), nullable=True)

    # Cadastre (feuille/parcelle)
    cad_section = db.Column(db.String(10), nullable=True)
    cad_feuille = db.Column(db.String(20), nullable=True)
    cad_numero = db.Column(db.String(20), nullable=True)
    cad_contenance = db.Column(db.Integer, nullable=True)  # m² (only if parcelle)
    cad_code_insee = db.Column(db.String(10), nullable=True)
