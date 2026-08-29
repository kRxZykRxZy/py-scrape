FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data/exports
EXPOSE 81
CMD ["waitress-serve","--host=0.0.0.0","--port=81","--threads=1","app:app"]