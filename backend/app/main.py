from fastapi import FastAPI

app = FastAPI(title="TeslaLab API")

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "TeslaLab backend is healthy"}
