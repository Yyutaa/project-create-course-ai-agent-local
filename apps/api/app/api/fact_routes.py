"""Read-only endpoints for persisted Course facts."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.run_routes import RunnerDep
from app.v0.schemas import CourseProgress, CourseRecord


router = APIRouter(prefix="/api/v0/courses", tags=["v0-courses"])


class CourseList(BaseModel):
    items: list[CourseProgress]


@router.get("", response_model=CourseList)
def list_courses(runner: RunnerDep) -> CourseList:
    return CourseList(items=runner.store.list_courses())


@router.get("/{course_id}", response_model=CourseRecord)
def read_course(course_id: str, runner: RunnerDep) -> CourseRecord:
    try:
        return runner.store.get_course(course_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Course 不存在") from error
