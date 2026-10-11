"""Course-owned files; SQLite remains the source of lesson content."""

from pathlib import Path


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def course_dir(self, course_id: str) -> Path:
        if not course_id.isalnum():
            raise ValueError("无效 Course ID")
        path = (self.root / course_id).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Workspace 路径越界")
        return path

    def write_lesson(self, course_id: str, run_id: str, version: int, markdown: str) -> str:
        if not run_id.isalnum() or version < 1:
            raise ValueError("无效 Run ID 或版本")
        course_dir = self.course_dir(course_id)
        run_dir = course_dir / "runs" / run_id
        if not run_dir.resolve().is_relative_to(course_dir):
            raise ValueError("Workspace 路径越界")
        path = run_dir / f"lesson-v{version}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.resolve().is_relative_to(course_dir):
            raise ValueError("Workspace 路径越界")
        created = False
        try:
            with path.open("x", encoding="utf-8") as output:
                created = True
                output.write(markdown)
        except Exception:
            if created:
                path.unlink(missing_ok=True)
            raise
        return str(path.relative_to(self.root))

    def remove_new_file(self, relative_path: str) -> None:
        path = (self.root / relative_path).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Workspace 路径越界")
        path.unlink(missing_ok=True)
