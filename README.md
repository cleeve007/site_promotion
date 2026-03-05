# site_promotion

MVP: une page "questionnaire" pour déposer un bien immobilier, stocké en base PostgreSQL (Railway).

## Démarrage local

```bash
pip install -r requirements.txt
export SECRET_KEY="dev"
python app.py
```

## Déploiement Railway (PostgreSQL)

1) Crée un projet Railway + ajoute une base **PostgreSQL**.
2) Dans le service web, Railway fournit automatiquement `DATABASE_URL`.
3) Ajoute une variable d'env :
- `SECRET_KEY` = une valeur longue et aléatoire.

Le repo contient un `Procfile` pour démarrer avec gunicorn :

```
web: gunicorn app:app --bind 0.0.0.0:$PORT
```

## URLs

- `/questionnaire` (GET) : formulaire
- `/questionnaire` (POST) : enregistre en base
- `/merci` : page de confirmation
