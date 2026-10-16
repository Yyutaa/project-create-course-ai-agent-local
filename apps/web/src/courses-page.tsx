import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Course, CourseProgress, Health } from "./api";
import { courseProgressLabel, runPath } from "./run-view";

export function CoursesPage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [drafts, setDrafts] = useState<CourseProgress[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draftsError, setDraftsError] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([api.health(), api.courses()])
      .then(([healthResponse, coursesResponse]) => {
        setHealth(healthResponse);
        setCourses(coursesResponse.items);
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "无法读取课程信息");
      });
    void api.courseFacts()
      .then((response) => setDrafts(response.items))
      .catch((reason: unknown) => {
        setDraftsError(reason instanceof Error ? reason.message : "无法读取我的课程");
      });
  }, []);

  return (
    <>
      <section className="dashboard-heading">
        <div>
          <h1>课程不是一次生成，而是一条可以恢复的生产线</h1>
          <p>每门课程都会进入独立工作台，可审阅章节、查看质量证据，或启动新的课程 Agent Run。</p>
        </div>
        <Link className="primary-button" to="/new"><span aria-hidden="true">✦</span>创建课程</Link>
      </section>

      {error && <p className="notice error">{error}</p>}
      {!error && !health && <p className="notice">正在连接本地课程服务。</p>}
      {health && <p className="connection-note"><span />本地服务已连接</p>}

      <section aria-label="我的课程" className="course-section">
        <div className="section-heading">
          <div><p className="eyebrow">Workspace</p><h2>我的课程</h2></div>
          <span>{drafts.length} 门草稿</span>
        </div>
        {draftsError && <p className="notice error">无法读取我的课程：{draftsError}</p>}
        <div className="course-grid">
          {drafts.map((course) => (
            <Link className="course-card" key={course.id} to={runPath(course.run_id)}>
              <div className="card-meta"><span className="status-pill">工作区</span><span>7 阶段</span></div>
              <h2>{course.title}</h2>
              <p>课程正在本地生成，可随时回到工作台继续处理。</p>
              <div className="course-metrics">
                <span>▱ {courseProgressLabel(course)}</span>
                <span>♢ 持久化运行记录</span>
              </div>
              <span className="course-link">打开课程工作台 <b aria-hidden="true">›</b></span>
            </Link>
          ))}
          {!draftsError && drafts.length === 0 && <div className="empty-card">
            <p className="eyebrow">No courses yet</p>
            <h2>从第一门课程开始</h2>
            <p>定义主题、受众和生成约束，创建后会自动进入 Run 工作台。</p>
            <Link className="text-link" to="/new">创建课程 →</Link>
          </div>}
        </div>
      </section>

      {courses.length > 0 && <section className="course-section" aria-label="示例课程">
        <div className="section-heading">
          <div><p className="eyebrow">Library</p><h2>已发布示例</h2></div>
          <span>{courses.length} 门课程</span>
        </div>
        <div className="course-grid">
          {courses.map((course) => <CourseCard key={course.slug} course={course} />)}
        </div>
      </section>}
    </>
  );
}


function CourseCard({ course }: { course: Course }) {
  return (
    <article className="course-card">
      <div className="card-meta">
        <span className="status-pill published">{course.status}</span>
        <span>{course.chapters} 章</span>
      </div>
      <h2>{course.title}</h2>
      <p>{course.description}</p>
      <div className="course-metrics">
        <span>▱ {course.chapters} 个 Markdown 章节</span>
        <span>♢ {course.duration}</span>
      </div>
      <a className="course-link" href={course.href}>
        打开课程工作台 <b aria-hidden="true">›</b>
      </a>
    </article>
  );
}
