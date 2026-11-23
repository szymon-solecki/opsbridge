FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY __init__.py backend/
COPY app backend/app
USER 9001:1999
ENTRYPOINT ["python", "-m", "backend.app.intake.worker"]
