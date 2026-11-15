import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from mealie.hearth.models import Food


def initialize(session: Session) -> None:
    if session.scalar(select(Food.id).limit(1)):
        return
    path = Path(__file__).parent / 'usda.json'
    if not path.is_file():
        return
    data = json.loads(path.read_text())
    session.add_all(Food(id=f['id'], owner='system', name=f['name'], nutrients=f['nutrients'], source=f['source']) for f in data)
    session.commit()
