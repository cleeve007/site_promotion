from __future__ import annotations

import os

from flask import Flask, render_template, redirect, url_for, request, session, abort

from models import db, PropertySubmission


ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


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

def ensure_tables() -> None:
    """Best-effort table creation.

    Railway sometimes races service startup vs DB readiness; also if the DB was reset,
    the tables may not exist yet. For MVP we create them lazily.
    """
    with app.app_context():
        db.create_all()


# Create tables on startup (MVP). Later we can add migrations.
ensure_tables()


from functools import wraps


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not ADMIN_PASSWORD:
            abort(500, description="ADMIN_PASSWORD is not set")
        if session.get("is_admin") is True:
            return fn(*args, **kwargs)
        return redirect(url_for("admin_login"))

    return wrapper


@app.get("/")
def home():
    return redirect(url_for("questionnaire"))


@app.get("/questionnaire")
def questionnaire():
    ensure_tables()
    return render_template("questionnaire.html")


@app.post("/questionnaire")
def submit_questionnaire():
    form = {
        "nom": request.form.get("nom", "").strip(),
        "email": request.form.get("email", "").strip(),
        "telephone": request.form.get("telephone", "").strip(),
        "adresse": request.form.get("adresse", "").strip(),
        "adresse_fulltext": request.form.get("adresse_fulltext", "").strip(),
        "adresse_x": request.form.get("adresse_x", "").strip(),
        "adresse_y": request.form.get("adresse_y", "").strip(),
        "adresse_city": request.form.get("adresse_city", "").strip(),
        "adresse_zipcode": request.form.get("adresse_zipcode", "").strip(),
        "adresse_kind": request.form.get("adresse_kind", "").strip(),
        "adresse_source": request.form.get("adresse_source", "").strip(),
        "prix": request.form.get("prix", "").strip(),
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

    def _to_float(value: str):
        value = value.strip()
        if value == "":
            return None
        return float(value)

    submission = PropertySubmission(
        nom=form["nom"],
        email=form["email"],
        telephone=form["telephone"],
        adresse=form["adresse"] or None,
        adresse_fulltext=form["adresse_fulltext"] or None,
        adresse_x=_to_float(form["adresse_x"]),
        adresse_y=_to_float(form["adresse_y"]),
        adresse_city=form["adresse_city"] or None,
        adresse_zipcode=form["adresse_zipcode"] or None,
        adresse_kind=form["adresse_kind"] or None,
        adresse_source=form["adresse_source"] or None,
        prix=_to_int(form["prix"]),
        description=form["description"] or None,
    )

    # If DB was reset and tables are missing, create and retry once.
    try:
        db.session.add(submission)
        db.session.commit()
    except Exception as e:
        msg = str(e)
        if "UndefinedTable" in msg or "does not exist" in msg or "relation \"property_submissions\" does not exist" in msg:
            db.session.rollback()
            ensure_tables()
            db.session.add(submission)
            db.session.commit()
        else:
            raise

    return redirect(url_for("thanks"))


@app.get("/merci")
def thanks():
    return render_template("thanks.html")


@app.get("/admin")
@admin_required
def admin_list():
    ensure_tables()
    submissions = PropertySubmission.query.order_by(PropertySubmission.id.desc()).all()
    return render_template("admin_list.html", submissions=submissions)


@app.get("/admin/map")
@admin_required
def admin_map():
    ensure_tables()
    rows = (
        PropertySubmission.query
        .filter(PropertySubmission.adresse_x.isnot(None))
        .filter(PropertySubmission.adresse_y.isnot(None))
        .order_by(PropertySubmission.id.desc())
        .all()
    )

    points = [
        {
            "id": r.id,
            "nom": r.nom,
            "email": r.email,
            "telephone": r.telephone,
            "adresse": r.adresse_fulltext or r.adresse,
            "city": r.adresse_city,
            "zipcode": r.adresse_zipcode,
            "prix": r.prix,
            "description": r.description,
            "x": r.adresse_x,
            "y": r.adresse_y,
        }
        for r in rows
    ]

    return render_template("admin_map.html", points=points)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        pw = request.form.get("password", "")
        if ADMIN_PASSWORD and pw == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin_list"))
        return render_template("admin_login.html", error="Mot de passe incorrect")

    return render_template("admin_login.html")


@app.get("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


if __name__ == "__main__":
    # Local dev only (Railway uses gunicorn via Procfile)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
