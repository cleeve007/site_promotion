from flask import Flask, render_template, request, redirect, url_for, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, VendeurUser, BienImmobilier
from openpyxl import Workbook
import datetime
import os
import requests
import time

app = Flask(__name__)
app.secret_key = "UNE_CHAINE_SECRETE_TRES_LONGUE_A_CHANGER"


app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///site.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

@app.before_request
def create_tables():
    db.create_all()

# 🔹 PAGE D’ACCUEIL
@app.route("/")
def home():
    return redirect(url_for("vendeur_dashboard"))

# 🔹 Vendeur 
# force la connexion
def login_required(f):
    print("login required")
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "vendeur_id" not in session:
            print("vendeur_id nor in")
            return redirect(url_for("vendeur_login"))
        return f(*args, **kwargs)
    return wrapper

# page login register logout
@app.route("/register", methods=["GET", "POST"])
def vendeur_register():
    if request.method == "POST":
        nom = request.form["nom"]
        email = request.form["email"]
        telephone = request.form["telephone"]
        password = generate_password_hash(request.form["password"])

        # Vérifier si email existe déjà
        if VendeurUser.query.filter_by(email=email).first():
            return render_template("vendeur_register.html", error="Email déjà utilisé")

        user = VendeurUser(
            nom=nom,
            email=email,
            telephone=telephone,
            password=password
        )

        db.session.add(user)
        db.session.commit()

        return redirect(url_for("vendeur_login"))

    return render_template("vendeur_register.html")

@app.route("/login", methods=["GET", "POST"])
def vendeur_login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = VendeurUser.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            session["vendeur_id"] = user.id
            return redirect(url_for("vendeur_dashboard"))

        return render_template("vendeur_login.html", error="Email ou mot de passe incorrect")

    return render_template("vendeur_login.html")

@app.route("/logout")
def vendeur_logout():
    session.pop("vendeur_id", None)
    return redirect(url_for("home"))

# dashboard vendeur (force le login)
@app.route("/dashboard")
@login_required
def vendeur_dashboard():
    user = VendeurUser.query.get(session["vendeur_id"])
    bien = BienImmobilier.query.filter_by(vendeur_id=user.id).first()

    return render_template("vendeur_dashboard.html", user=user, bien=bien)

@app.route("/bien", methods=["GET", "POST"])
@login_required
def update_bien():
    user = VendeurUser.query.get(session["vendeur_id"])
    bien = BienImmobilier.query.filter_by(vendeur_id=user.id).first()

    if request.method == "POST":
        if not bien:
            bien = BienImmobilier(vendeur_id=user.id)

        bien.adresse = request.form["adresse"]
        bien.ville = request.form["ville"]
        bien.code_postal = request.form["code_postal"]
        bien.quartier = request.form["quartier"]
        bien.prix = request.form["prix"]
        bien.surface_habitable = request.form["surface_habitable"]
        bien.surface_terrain = request.form["surface_terrain"]
        bien.nombre_pieces = request.form["nombre_pieces"]
        bien.description = request.form["description"]

        adresse_complete = f"{bien.adresse}, {bien.code_postal} {bien.ville}"

        lat, lon = geocode_adresse(adresse_complete)
        print(lat,lon)
        bien.latitude = lat
        bien.longitude = lon


        db.session.add(bien)
        db.session.commit()

        return redirect(url_for("vendeur_dashboard"))

    return render_template("vendeur_edit.html", bien=bien)

@app.route("/stop")
@login_required
def stop_vendre():
    user = VendeurUser.query.get(session["vendeur_id"])
    bien = BienImmobilier.query.filter_by(vendeur_id=user.id).first()
    if bien:
        bien.actif = False
        db.session.commit()
    return redirect(url_for("vendeur_dashboard"))

@app.route("/start")
@login_required
def start_vendre():
    user = VendeurUser.query.get(session["vendeur_id"])
    bien = BienImmobilier.query.filter_by(vendeur_id=user.id).first()
    if bien:
        bien.actif = True
        db.session.commit()
    return redirect(url_for("vendeur_dashboard"))


@app.route("/delete")
@login_required
def delete_bien():
    user = VendeurUser.query.get(session["vendeur_id"])
    bien = BienImmobilier.query.filter_by(vendeur_id=user.id).first()
    if bien:
        db.session.delete(bien)
        db.session.commit()
    return redirect(url_for("vendeur_dashboard"))


# 🔹 Promoteur
@app.route("/promoteur")
def promoteur_home():
    query = BienImmobilier.query.filter_by(actif=True)

    ville = request.args.get("ville")
    quartier = request.args.get("quartier")
    prix_min = request.args.get("prix_min")
    prix_max = request.args.get("prix_max")

    if ville:
        query = query.filter(BienImmobilier.ville.ilike(f"%{ville}%"))
    if quartier:
        query = query.filter(BienImmobilier.quartier.ilike(f"%{quartier}%"))
    if prix_min:
        query = query.filter(BienImmobilier.prix >= int(prix_min))
    if prix_max:
        query = query.filter(BienImmobilier.prix <= int(prix_max))

    biens = query.all()

    # ➜ conversion vers JSON-friendly
    biens_json = [
        {
            "id": b.id,
            "adresse": b.adresse,
            "ville": b.ville,
            "code_postal": b.code_postal,
            "quartier": b.quartier,
            "prix": b.prix,
            "surface_habitable": b.surface_habitable,
            "surface_terrain": b.surface_terrain,
            "nombre_pieces": b.nombre_pieces,
            "description": b.description,
            "latitude": b.latitude,
            "longitude": b.longitude,

        }
        for b in biens
    ]

    return render_template("promoteur_map.html", biens=biens_json)



@app.route("/promoteur/export")
def export_biens():

    query = BienImmobilier.query.filter_by(actif=True)

    # mêmes filtres que dans /promoteur
    if request.args.get("ville"):
        query = query.filter(BienImmobilier.ville.ilike(f"%{request.args['ville']}%"))

    if request.args.get("quartier"):
        query = query.filter(BienImmobilier.quartier.ilike(f"%{request.args['quartier']}%"))

    if request.args.get("prix_min"):
        query = query.filter(BienImmobilier.prix >= int(request.args["prix_min"]))

    if request.args.get("prix_max"):
        query = query.filter(BienImmobilier.prix <= int(request.args["prix_max"]))

    biens = query.all()

    wb = Workbook()
    ws = wb.active
    ws.append(["ID", "Adresse", "Ville", "Quartier", "Prix", "Surface", "Pièces"])

    for b in biens:
        ws.append([
            b.id, b.adresse, b.ville, b.quartier,
            b.prix, b.surface_habitable, b.nombre_pieces
        ])

    filename = f"export_biens_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx"
    wb.save(filename)

    return send_file(filename, as_attachment=True)


def geocode_adresse(adresse_complete):
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": adresse_complete,
        "format": "json",
        "addressdetails": 1,
        "limit": 1
    }

    time.sleep(1)  # ⚠️ Nominatim impose une pause 1s entre appels

    response = requests.get(url, params=params, headers={"User-Agent": "my-app"})
    
    data = response.json()
    print(data)
    if data:
        return float(data[0]["lat"]), float(data[0]["lon"])
    else:
        return None, None



if __name__ == "__main__":
    app.run(debug=True)
