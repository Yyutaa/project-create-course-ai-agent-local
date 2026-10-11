from fastapi import APIRouter, HTTPException

from app.catalog import CourseList, list_courses


router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.get("", response_model=CourseList)
def read_courses() -> CourseList:
    try:
        return list_courses()
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
