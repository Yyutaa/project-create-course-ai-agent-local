document.addEventListener("DOMContentLoaded", () => {
  // Reading progress tracker: marks visited lessons in localStorage,
  // highlights them in the chapter navigation sidebar.
  const STORAGE_PREFIX = "course-reading:";
  const slug = document.body.dataset.courseSlug || location.pathname.split("/").slice(-3, -2)[0] || "unknown";
  const key = STORAGE_PREFIX + slug;

  function loadProgress() {
    try { return JSON.parse(localStorage.getItem(key)) || {}; } catch { return {}; }
  }
  function saveProgress(data) {
    try { localStorage.setItem(key, JSON.stringify(data)); } catch {}
  }

  // Mark current lesson as read
  const currentLink = document.querySelector(".chapter-nav-list a.is-current, .chapter-nav-list a[aria-current='page']");
  if (currentLink) {
    const href = currentLink.getAttribute("href");
    const lessonPath = href ? href.replace(/^\.\.\//, "") : null;
    if (lessonPath) {
      const progress = loadProgress();
      progress[lessonPath] = { readAt: new Date().toISOString() };
      saveProgress(progress);
    }
  }

  // Highlight all read lessons in sidebar
  const progress = loadProgress();
  document.querySelectorAll(".chapter-nav-list a").forEach((link) => {
    const href = link.getAttribute("href");
    if (!href) return;
    const lessonPath = href.replace(/^\.\.\//, "");
    if (progress[lessonPath]) {
      link.classList.add("is-read");
      const code = link.querySelector(".chapter-nav-code");
      if (code && !code.querySelector(".read-badge")) {
        const badge = document.createElement("span");
        badge.className = "read-badge";
        badge.textContent = " ✓";
        badge.setAttribute("aria-label", "已阅读");
        code.appendChild(badge);
      }
    }
  });
});
