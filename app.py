from __future__ import annotations

import os

from flask import Flask, render_template, redirect, url_for, request

from models import db, PropertySubmission


def _normalize_database_url(url: str) -> str:
    """Railway provides DATABASE_URL.

    We use psycopg v3 (psycopg[binary]) to avoid system libpq deps.
    SQLAlchemy URL should be: postgresql+psycopg://
    """
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


app = Flask(__name__)

# Secrets (Railway)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# Database
raw_db_url = os.environ.get("DATABASE_URL")
if raw_db_url:
    app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_database_url(raw_db_url)
else:
    # Local dev fallback
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///site.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

# Create tables on startup (MVP). Later we can add migrations.
with app.app_context():
    db.create_all()


@app.get("/")
def home():
    return redirect(url_for("questionnaire"))


@app.get("/questionnaire")
def questionnaire():
    return render_template("questionnaire.html")


@app.post("/questionnaire")
def submit_questionnaire():
    form = {
        "nom": request.form.get("nom", "").strip(),
        "email": request.form.get("email", "").strip(),
        "telephone": request.form.get("telephone", "").strip(),
        "adresse": request.form.get("adresse", "").strip(),
        "ville": request.form.get("ville", "").strip(),
        "code_postal": request.form.get("code_postal", "").strip(),
        "prix": request.form.get("prix", "").strip(),
        "surface_habitable": request.form.get("surface_habitable", "").strip(),
        "nombre_pieces": request.form.get("nombre_pieces", "").strip(),
        "description": request.form.get("description", "").strip(),
    }

    # Minimal validation
    if not form["nom"] or not form["email"] or not form["telephone"]:
        return render_template(
            "questionnaire.html",
            error="Nom, email et téléphone sont obligatoires.",
            form=form,
        )

    def _to_int(value: str):
        value = value.strip()
        if value == "":
            return None
        return int(value)

    submission = PropertySubmission(
        nom=form["nom"],
        email=form["email"],
        telephone=form["telephone"],
        adresse=form["adresse"] or None,
        ville=form["ville"] or None,
        code_postal=form["code_postal"] or None,
        prix=_to_int(form["prix"]),
        surface_habitable=_to_int(form["surface_habitable"]),
        nombre_pieces=_to_int(form["nombre_pieces"]),
        description=form["description"] or None,
    )

    db.session.add(submission)
    db.session.commit()

    return redirect(url_for("thanks"))


@app.get("/merci")
def thanks():
    return render_template("thanks.html")


if __name__ == "__main__":
    # Local dev only (Railway uses gunicorn via Procfile)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
