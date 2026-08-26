from pydantic import BaseModel
from pathlib import Path


def save_model(model: BaseModel, path: Path) -> None:
    path.write_text(model.model_dump_json(indent=2))


def load_model(model_cls: type[BaseModel], path: Path) -> BaseModel:
    return model_cls.model_validate_json(path.read_text())
