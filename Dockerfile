# Use a slim version of Python as the base
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Install system-level dependencies for SQLite and psutil
RUN apt-get update && apt-get install -y \
    sqlite3 \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python libraries
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy all project files into the container
COPY . .

# Create the data directory for persistent storage (Very important for k8s)
# Replace the old RUN mkdir line with this:
RUN touch /app/metrics.db /app/backend_data.json && chmod 666 /app/metrics.db
# Tell Flask to listen on all network interfaces
ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0

# Expose the dashboard port
EXPOSE 5000

# Run the application using the Flask command
CMD ["flask", "run"]