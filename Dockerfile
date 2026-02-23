FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md /app/
RUN pip install --no-cache-dir .

COPY . /app

CMD ["python", "-m", "src.app"]
