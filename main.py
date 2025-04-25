# main.py
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
from services.instagram_analyzer import analyze_instagram_handle

app = FastAPI()

class HandleInput(BaseModel):
    handles: List[str]

@app.post("/analyze")
def analyze_handles(input: HandleInput):
    results = []
    for handle in input.handles:
        result = analyze_instagram_handle(handle)
        results.append(result)
    return {"results": results}
