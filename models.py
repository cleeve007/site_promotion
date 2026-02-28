from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class VendeurUser(db.Model):
    __tablename__ = "vendeur_users"

    id = db.Column(db.Integer, primary_key=True)

    # Role
    role = db.Column(db.String(20), default="vendeur")

    # Infos nécessaires
    nom = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    telephone = db.Column(db.String(20), nullable=False)

    # Auth
    password = db.Column(db.String(200), nullable=False)


class BienImmobilier(db.Model):
     __tablename__ = "vendeur_bien"

     id = db.Column(db.Integer, primary_key=True)
     
     # Vendeur ID
     vendeur_id = db.Column(db.Integer, db.ForeignKey("vendeur_users.id"), nullable=False)
     
     # Info du bien
     adresse = db.Column(db.String(250), nullable=True)
     prix = db.Column(db.Integer, nullable=True)
     
     description = db.Column(db.Text)
     
     # Info a partir de l'adresse
     latitude = db.Column(db.Float)
     longitude = db.Column(db.Float)
 
     # Vente
     actif = db.Column(db.Boolean, default=True)  # "ne plus vendre" / "remettre en vente"
 
     vendeur = db.relationship("VendeurUser", backref="bien")
