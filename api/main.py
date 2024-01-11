from typing import Union
from fastapi import FastAPI


app = FastAPI(
    title="Thumbnail Generation API",
    debug=True,
    version="0.1.0",
)


@app.get("/")
def read_root():
    return {"Hello": "World"}
