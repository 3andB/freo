from flask import Flask

app = Flask(__name__)

@app.get("/")
def home():
    return "FreoWorld is alive."

@app.get("/health")
def health():
    return {"status": "ok"}
