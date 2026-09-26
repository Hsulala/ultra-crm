FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["sh", "-c", "alembic upgrade head && python -m scripts.bootstrap_admin && python -m scripts.seed_item_catalog && python -m scripts.seed_venue_coaches && python -m scripts.seed_demo_data && uvicorn app.main:app --host 0.0.0.0 --port 8080"]
