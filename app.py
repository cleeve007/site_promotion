from __future__ import annotations

import os
import threading
import time
import json

import requests

from flask import Flask, render_template, redirect, url_for, request, session, abort, jsonify

from models import db, PropertySubmission


ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

# Async enrichment controls
ENRICH_ENABLED = (os.environ.get("ENRICH_ENABLED", "1") == "1")
ENRICH_BATCH_ON_ADMIN = int(os.environ.get("ENRICH_BATCH_ON_ADMIN", "2") or "2")
# In-process lock to avoid running too many enrichment jobs at once.
_enrich_lock = threading.Semaphore(value=int(os.environ.get("ENRICH_CONCURRENCY", "1") or "1"))


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


def _point_in_ring(lon: float, lat: float, ring: list) -> bool:
    """Ray casting point-in-polygon for a linear ring in lon/lat."""
    inside = False
    n = len(ring)
    if n < 4:
        return False
    x, y = lon, lat
    for i in range(n - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        # intersect with horizontal ray to +inf
        if ((y1 > y) != (y2 > y)):
            x_int = (x2 - x1) * (y - y1) / (y2 - y1 + 1e-18) + x1
            if x_int > x:
                inside = not inside
    return inside


def _point_in_geometry(lon: float, lat: float, geom: dict) -> bool:
    if not geom:
        return False
    t = geom.get("type")
    coords = geom.get("coordinates")
    if not t or coords is None:
        return False

    if t == "Polygon":
        # coords: [outer, hole1, ...]
        outer = coords[0] if coords else None
        if not outer or not _point_in_ring(lon, lat, outer):
            return False
        # holes
        for hole in coords[1:] or []:
            if hole and _point_in_ring(lon, lat, hole):
                return False
        return True

    if t == "MultiPolygon":
        for poly in coords or []:
            if not poly:
                continue
            outer = poly[0] if poly else None
            if not outer or not _point_in_ring(lon, lat, outer):
                continue
            in_hole = False
            for hole in poly[1:] or []:
                if hole and _point_in_ring(lon, lat, hole):
                    in_hole = True
                    break
            if not in_hole:
                return True
        return False

    return False


def _fetch_commune_for_point(lon: float, lat: float) -> dict:
    url = "https://apicarto.ign.fr/api/limites-administratives/commune"
    r = requests.get(url, params={"lon": lon, "lat": lat}, timeout=20)
    r.raise_for_status()
    fc = r.json() or {}
    feat = (fc.get("features") or [None])[0] or {}
    props = feat.get("properties") or {}
    return {
        "insee": props.get("insee_com") or props.get("insee_arr"),
        "nom": props.get("nom_com"),
    }


def _fetch_plu_zone_for_point(lon: float, lat: float) -> dict | None:
    """Fetch the PLU/GPU zone containing the point.

    APIcarto supports filtering by geometry directly:
    /api/gpu/zone-urba?geom={"type":"Point","coordinates":[lon,lat]}
    """
    url = "https://apicarto.ign.fr/api/gpu/zone-urba"
    geom = {"type": "Point", "coordinates": [lon, lat]}
    r = requests.get(url, params={"geom": json.dumps(geom, separators=(",", ":"))}, timeout=35)
    r.raise_for_status()
    fc = r.json() or {}
    feats = fc.get("features") or []
    return feats[0] if feats else None


def _fetch_cadastre_parcelle_for_point(lon: float, lat: float) -> dict:
    """Fetch cadastre parcel containing the point.

    Note: for parcelle, APIcarto is reliable with lon/lat params.
    (geom=Point seems to return empty for parcelle in some cases.)
    """
    url = "https://apicarto.ign.fr/api/cadastre/parcelle"
    r = requests.get(url, params={"lon": lon, "lat": lat}, timeout=25)
    r.raise_for_status()
    fc = r.json() or {}
    feat = (fc.get("features") or [None])[0] or {}
    props = feat.get("properties") or {}
    return {
        "section": props.get("section"),
        "numero": props.get("numero"),
        "contenance": props.get("contenance"),
        "code_insee": props.get("code_insee"),
        "idu": props.get("idu"),
    }


def _fetch_cadastre_feuille_for_point(lon: float, lat: float) -> dict:
    """Optional: fetch cadastre sheet (feuille) containing the point."""
    url = "https://apicarto.ign.fr/api/cadastre/feuille"
    geom = {"type": "Point", "coordinates": [lon, lat]}
    r = requests.get(url, params={"geom": json.dumps(geom, separators=(",", ":"))}, timeout=25)
    r.raise_for_status()
    fc = r.json() or {}
    feat = (fc.get("features") or [None])[0] or {}
    props = feat.get("properties") or {}
    return {
        "section": props.get("section"),
        "feuille": props.get("feuille"),
        "code_insee": props.get("code_insee"),
        "id": feat.get("id"),
    }


def enrich_submission_async(submission_id: int) -> None:
    if not ENRICH_ENABLED:
        return

    def job():
        if not _enrich_lock.acquire(blocking=False):
            return
        try:
            with app.app_context():
                ensure_tables()
                s = PropertySubmission.query.get(submission_id)
                if not s:
                    return

                # Skip if no coords
                if s.adresse_x is None or s.adresse_y is None:
                    s.enrich_status = "skipped"
                    db.session.commit()
                    return

                s.enrich_status = "running"
                s.enrich_error = None
                db.session.commit()

                lon, lat = float(s.adresse_x), float(s.adresse_y)

                # 1) Commune
                com = _fetch_commune_for_point(lon, lat)
                s.commune_insee = com.get("insee")
                s.commune_nom = com.get("nom")

                # 2) PLU (GPU zone-urba) via geom=Point
                zone = _fetch_plu_zone_for_point(lon, lat)
                if zone:
                    p = zone.get("properties") or {}
                    s.plu_typezone = p.get("typezone")
                    s.plu_libelle = p.get("libelle")
                    s.plu_idurba = p.get("idurba")

                # 3) Cadastre parcelle (section/numero/contenance)
                cadp = _fetch_cadastre_parcelle_for_point(lon, lat)
                s.cad_section = cadp.get("section")
                s.cad_numero = cadp.get("numero")
                try:
                    s.cad_contenance = int(cadp.get("contenance")) if cadp.get("contenance") is not None else None
                except Exception:
                    s.cad_contenance = None
                s.cad_code_insee = cadp.get("code_insee")

                # Optional: cadastre feuille (useful for display)
                try:
                    cadf = _fetch_cadastre_feuille_for_point(lon, lat)
                    s.cad_feuille = cadf.get("feuille")
                    # if section missing, fill it
                    if not s.cad_section:
                        s.cad_section = cadf.get("section")
                except Exception:
                    pass

                from datetime import datetime, timezone
                s.enriched_at = datetime.now(timezone.utc)
                s.enrich_status = "ok"
                db.session.commit()

        except Exception as e:
            try:
                with app.app_context():
                    s = PropertySubmission.query.get(submission_id)
                    if s:
                        s.enrich_status = "error"
                        s.enrich_error = str(e)
                        db.session.commit()
            except Exception:
                pass
        finally:
            _enrich_lock.release()

    threading.Thread(target=job, daemon=True).start()


def run_enrich_batch(limit: int = 1) -> int:
    if not ENRICH_ENABLED:
        return 0
    with app.app_context():
        ensure_tables()
        q = (
            PropertySubmission.query
            .filter((PropertySubmission.enrich_status.is_(None)) | (PropertySubmission.enrich_status == "queued") | (PropertySubmission.enrich_status == "error"))
            .filter(PropertySubmission.adresse_x.isnot(None))
            .filter(PropertySubmission.adresse_y.isnot(None))
            .order_by(PropertySubmission.id.asc())
            .limit(limit)
        )
        rows = q.all()
        for s in rows:
            if s.enrich_status != "running":
                s.enrich_status = "queued"
                db.session.commit()
                enrich_submission_async(s.id)
        return len(rows)


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
        enrich_status="queued" if ENRICH_ENABLED else "skipped",
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

    # Async enrichment (do not block the user)
    if ENRICH_ENABLED:
        enrich_submission_async(submission.id)

    return redirect(url_for("thanks"))


@app.get("/merci")
def thanks():
    return render_template("thanks.html")


@app.get("/admin")
@admin_required
def admin_list():
    ensure_tables()
    # kick a small enrichment batch in the background
    if ENRICH_ENABLED and ENRICH_BATCH_ON_ADMIN > 0:
        run_enrich_batch(ENRICH_BATCH_ON_ADMIN)

    submissions = PropertySubmission.query.order_by(PropertySubmission.id.desc()).all()
    return render_template("admin_list.html", submissions=submissions)


@app.get("/admin/map")
@admin_required
def admin_map():
    ensure_tables()
    if ENRICH_ENABLED and ENRICH_BATCH_ON_ADMIN > 0:
        run_enrich_batch(ENRICH_BATCH_ON_ADMIN)
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


@app.get("/admin/api/plu/zone-urba")
@admin_required
def admin_api_plu_zone_urba():
    """Fetch PLU/GPU urban zones via APIcarto.

    Query: ?commune=Grenoble

    Correct API usage:
    1) Resolve a coordinate for the commune name
    2) Call APIcarto limites-administratives/commune?lon={x}&lat={y} to get INSEE
    3) Call GPU zone-urba with partition=DU_{INSEE}
    """
    commune = (request.args.get("commune") or "").strip()
    if not commune:
        return jsonify({"error": "missing_commune"}), 400

    # 1) Resolve commune -> a coordinate (centre) using geo.api.gouv.fr
    gouv_url = "https://geo.api.gouv.fr/communes"
    params = {
        "nom": commune,
        "fields": "nom,code,centre",
        "format": "json",
    }
    r = requests.get(gouv_url, params=params, timeout=20)
    r.raise_for_status()
    communes = r.json() or []
    if not communes:
        return jsonify({"error": "commune_not_found"}), 404

    c = communes[0]
    centre = (c.get("centre") or {}).get("coordinates")
    if not centre or len(centre) != 2:
        return jsonify({"error": "no_centre"}), 502

    lon, lat = centre[0], centre[1]

    # 2) Get INSEE from APIcarto
    adm_url = "https://apicarto.ign.fr/api/limites-administratives/commune"
    a = requests.get(adm_url, params={"lon": lon, "lat": lat}, timeout=30)
    a.raise_for_status()
    fc_adm = a.json() or {}
    features = fc_adm.get("features") or []
    if not features:
        return jsonify({"error": "apicarto_commune_not_found"}), 404

    props = (features[0] or {}).get("properties") or {}
    insee = props.get("insee_com") or props.get("insee_arr")
    if not insee:
        return jsonify({"error": "no_insee"}), 502

    partition = f"DU_{insee}"

    # 3) Query GPU zone-urba by partition
    apicarto_url = "https://apicarto.ign.fr/api/gpu/zone-urba"
    z = requests.get(apicarto_url, params={"partition": partition}, timeout=60)
    z.raise_for_status()
    fc = z.json()

    # Optional: keep only potentially buildable zones (U and AU)
    only_buildable = (request.args.get("buildable") or "1") == "1"
    if only_buildable and isinstance(fc, dict) and isinstance(fc.get("features"), list):
        fc["features"] = [
            f for f in fc["features"]
            if (f.get("properties") or {}).get("typezone") in ("U", "AU")
        ]

    return jsonify({
        "commune": {
            "nom": c.get("nom"),
            "code": c.get("code"),
            "insee": insee,
            "partition": partition,
            "centre": {"lon": lon, "lat": lat},
        },
        "data": fc,
    })


@app.get("/admin/api/cadastre/parcelle")
@admin_required
def admin_api_cadastre_parcelle():
    """Fetch cadastre parcels.

    Notes:
    - APIcarto cadastre/parcelle is reliable for point queries (lon/lat).
    - Bulk queries by commune INSEE can be very large and may timeout.

    Modes:
      1) Point: ?lon=2.35&lat=48.85
      2) Commune (heavy): ?insee=59143 OR ?commune=Grenoble
      3) View sampling (approx): ?bbox=minLon,minLat,maxLon,maxLat[&samples=16]

    The view sampling mode approximates "bbox de la vue" by sampling a grid of points
    and requesting the parcel at each point, then deduplicating.
    """
    cad_url = "https://apicarto.ign.fr/api/cadastre/parcelle"

    lon = (request.args.get("lon") or "").strip()
    lat = (request.args.get("lat") or "").strip()
    bbox = (request.args.get("bbox") or "").strip()

    # Mode 1: point
    if lon and lat:
        z = requests.get(cad_url, params={"lon": lon, "lat": lat}, timeout=30)
        z.raise_for_status()
        return jsonify({"mode": "point", "data": z.json()})

    # Mode 3: view sampling
    if bbox:
        import time

        try:
            minlon_s, minlat_s, maxlon_s, maxlat_s = bbox.split(",")
            minlon, minlat, maxlon, maxlat = map(float, (minlon_s, minlat_s, maxlon_s, maxlat_s))
        except Exception:
            return jsonify({"error": "bad_bbox"}), 400

        # Default lower to avoid worker timeouts.
        samples = int((request.args.get("samples") or "9").strip() or "9")
        samples = max(4, min(samples, 25))

        # Hard time budget so we don't hit gunicorn worker timeout.
        budget_sec = float((request.args.get("budget") or "20").strip() or "20")
        budget_sec = max(5.0, min(budget_sec, 60.0))
        t0 = time.monotonic()

        # Build a square-ish grid
        n = int(samples ** 0.5)
        n = max(2, n)
        xs = [minlon + (maxlon - minlon) * (i + 0.5) / n for i in range(n)]
        ys = [minlat + (maxlat - minlat) * (j + 0.5) / n for j in range(n)]

        features = []
        seen = set()
        req_count = 0
        timed_out = 0
        failed = 0

        def add_features(fc: dict) -> None:
            nonlocal features, seen
            for f in fc.get("features") or []:
                props = f.get("properties") or {}
                key = props.get("idu") or (props.get("section"), props.get("numero"), props.get("code_insee"))
                if key in seen:
                    continue
                seen.add(key)
                features.append(f)

        # Always sample the view center first (most likely to hit a parcel)
        cx, cy = (minlon + maxlon) / 2.0, (minlat + maxlat) / 2.0
        try:
            req_count += 1
            zc = requests.get(cad_url, params={"lon": cx, "lat": cy}, timeout=8)
            zc.raise_for_status()
            add_features(zc.json() or {})
        except requests.exceptions.Timeout:
            timed_out += 1
        except Exception:
            failed += 1

        for y in ys:
            for x in xs:
                if time.monotonic() - t0 > budget_sec:
                    break
                req_count += 1
                try:
                    # Keep per-sample timeout small.
                    z = requests.get(cad_url, params={"lon": x, "lat": y}, timeout=5)
                    z.raise_for_status()
                    add_features(z.json() or {})
                except requests.exceptions.Timeout:
                    timed_out += 1
                    continue
                except Exception:
                    failed += 1
                    continue
            else:
                continue
            break

        return jsonify({
            "mode": "view-sampling",
            "bbox": [minlon, minlat, maxlon, maxlat],
            "sampleRequests": req_count,
            "featureCount": len(features),
            "timedOutSamples": timed_out,
            "failedSamples": failed,
            "budgetSec": budget_sec,
            "data": {"type": "FeatureCollection", "features": features},
        })

    # Mode 2: commune (heavy)
    insee = (request.args.get("insee") or "").strip()
    commune = (request.args.get("commune") or "").strip()

    if not insee and not commune:
        return jsonify({"error": "missing_params"}), 400

    if not insee and commune:
        # Resolve commune -> centre -> insee via APIcarto limites-admin
        gouv_url = "https://geo.api.gouv.fr/communes"
        params = {"nom": commune, "fields": "nom,code,centre", "format": "json"}
        r = requests.get(gouv_url, params=params, timeout=20)
        r.raise_for_status()
        communes = r.json() or []
        if not communes:
            return jsonify({"error": "commune_not_found"}), 404
        centre = (communes[0].get("centre") or {}).get("coordinates")
        if not centre or len(centre) != 2:
            return jsonify({"error": "no_centre"}), 502
        lon2, lat2 = centre[0], centre[1]

        adm_url = "https://apicarto.ign.fr/api/limites-administratives/commune"
        a = requests.get(adm_url, params={"lon": lon2, "lat": lat2}, timeout=30)
        a.raise_for_status()
        fc_adm = a.json() or {}
        feats = fc_adm.get("features") or []
        if not feats:
            return jsonify({"error": "apicarto_commune_not_found"}), 404
        props = (feats[0] or {}).get("properties") or {}
        insee = props.get("insee_com") or props.get("insee_arr")
        if not insee:
            return jsonify({"error": "no_insee"}), 502

    # Warning: can be large.
    try:
        z = requests.get(cad_url, params={"code_insee": insee}, timeout=180)
        z.raise_for_status()
        fc = z.json()
    except requests.exceptions.Timeout:
        return jsonify({
            "error": "timeout",
            "message": "Le cadastre est trop long à charger pour cette commune. Utilise le mode bbox de la vue.",
            "insee": insee,
        }), 504

    return jsonify({"mode": "commune", "insee": insee, "data": fc})


@app.post("/admin/enrich/<int:submission_id>")
@admin_required
def admin_enrich_one(submission_id: int):
    ensure_tables()
    s = PropertySubmission.query.get(submission_id)
    if not s:
        abort(404)
    s.enrich_status = "queued"
    s.enrich_error = None
    db.session.commit()
    enrich_submission_async(s.id)
    return redirect(url_for("admin_list"))


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
