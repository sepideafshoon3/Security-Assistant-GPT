from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.schemas.schemas import ProjectCreateRequest, ProjectUpdateRequest
from src.db.models import Project, User
from src.db.session import get_db
from src.security.auth import get_current_user

router = APIRouter(tags=["projects"])


def _serialize(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def _get_owned_project_or_404(
    project_id: str, current_user: User, db: Session
) -> Project:
    """Fetch a project, scoped to the caller. Mirrors the conversations
    router: a plain 404 either way so this can't be used to enumerate
    other users' project ids."""
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/projects")
async def list_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    projects = (
        db.query(Project)
        .filter(Project.user_id == current_user.id)
        .order_by(Project.name.asc())
        .all()
    )
    return {"projects": [_serialize(p) for p in projects]}


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name must not be empty")

    project = Project(user_id=current_user.id, name=name[:255])
    db.add(project)
    db.commit()
    db.refresh(project)
    return _serialize(project)


@router.patch("/projects/{project_id}")
async def rename_project(
    project_id: str,
    body: ProjectUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _get_owned_project_or_404(project_id, current_user, db)

    new_name = body.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="name must not be empty")
    project.name = new_name[:255]

    db.commit()
    db.refresh(project)
    return _serialize(project)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    project = _get_owned_project_or_404(project_id, current_user, db)
    # Conversations in this project are un-filed (project_id -> NULL via
    # the FK's ondelete="SET NULL"), not deleted.
    db.delete(project)
    db.commit()
