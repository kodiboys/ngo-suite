# src/adapters/api_runner.py
from src.adapters.api import app

# FastAPI startet NUR hier
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
