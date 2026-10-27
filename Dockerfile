FROM python:3.12-slim-bookworm

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
	libgl1-mesa-glx \
	libglib2.0-0 \
	libzbar0 \
	tesseract-ocr \
	&& rm -rf /var/lib/apt/lists/*
COPY app app
COPY main.py main.py
COPY resources resources
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 3000
CMD ["gunicorn", "-w", "5", "-t", "5", "-b", "0.0.0.0:3000", "main:app", "--timeout", "120"]