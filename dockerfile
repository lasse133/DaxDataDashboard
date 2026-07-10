# 1. Start with a lightweight Python Linux environment
FROM python:3.12-slim

# 2. Prevent Python from buffering console output
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 3. Set the working directory inside the container
WORKDIR /app

# 4. Install system dependencies (needed for compiling PostgreSQL and rapidfuzz C-extensions)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 5. Copy the requirements file first to leverage Docker layer caching
COPY requirements.txt .

# 6. Install all Python packages (your text file automatically handles the CPU PyTorch logic!)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 7. Copy the rest of your project files
COPY . .

# 8. Tell Docker that Streamlit uses port 8501
EXPOSE 8501

# 9. Healthcheck so Caprover knows the app is alive
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# 10. Start Streamlit
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]