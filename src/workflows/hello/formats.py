from pydantic import BaseModel


class HelloInput(BaseModel):
    name: str = "World"
