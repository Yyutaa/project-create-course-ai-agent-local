# 已发布课程详情页 · 样式设计规划

> 目标：让 `project-create-course-ai-agent-local` 发布功能产出的**已发布课程页面**，在视觉与结构上对齐引用项目 `project-create-course-ai-agent` 已实现的那套课程站点。
> 状态：**设计规划阶段**，尚未改动任何代码。工程侧发布能力（`publishing.py` 等）已可用，本文规划其产物形态的升级。

---

## 1. 意图与范围

当前「发布」只生成一个极简目录页 `courses/published/<slug>/index.html`（内联样式 + 链接到 `lessons/*.md`）。目标是把它升级为引用项目里那套**完整静态课程站点**：

- 课程详情页（目录/首页）
- 逐章阅读页（Markdown → 样式化 HTML）
- （可选）术语表页
- 自托管主题样式 + 顶部主题切换 + 章节侧栏 + 阅读进度

范围只覆盖**已发布课程的静态产物**，不改动生成流程、质量门禁与人工发布契约。示例课程 `courses/advanced-learning-of-obsidian/` 保持只读。

---

## 2. 参考实现解构（引用项目）

来源：`/Users/yuta/Documents/Project/project-create-course-ai-agent`

### 2.1 三类页面

| 页面 | 生成器 | 说明 |
| --- | --- | --- |
| 课程详情页 `index.html` | `build-static-course.mjs` `renderIndex()`（L296-343） | hero + 元信息胶囊 + 进度面板 + 按模块分组的章节卡片 |
| 章节页 `lessons/NN-*.html` | `renderLesson()`（L281-293） | 固定左侧章节导航 + 正文 + 粘性目录 + 上/下一章 |
| 术语表 `reference/glossary.html` | `renderGlossary()`（L345-352） | 由 `reference/glossary.md` 渲染 |

### 2.2 页面外壳与组件（`course-shell.css`）

- 外壳：`.site-shell` / `.course-shell`（`max-width:1680px`，`padding:20px 40px 84px`）。
- `.topbar`：左侧 `.brand`（课程标题）、右侧导航（课程目录 / 术语表），运行时注入 `.theme-toggle`。
- `.course-hero`（详情页）：`.eyebrow` 标签 → `h1` → `.lead` → `.meta-row > .pill`；右上角两处装饰——柔光球（`::before`，`filter:blur`）+ 巨型水印字（`::after`，`content:var(--course-mark)`）。
- `.progress-panel`：`190px + 1fr` 网格，大号进度数字 + `.progress-track`（`--progress` 变量）。
- `.module-section` → `.module-heading` + `.chapter-grid`（桌面 3 列 / ≤1080 2 列 / ≤680 1 列）→ `.chapter-card`（`min-height:360px`，圆角 `--radius-xl`，角落柔光球）。卡片态：`available`（可读，hover 加深边框）/ `planned`（`opacity:.58`，不可点）。
- 阅读页：`.lesson-page-grid`（`270px` 侧栏 + 内容）→ `.chapter-nav`（`position:fixed`，可折叠/展开，含模块分组与当前章高亮）→ `.lesson-page-main` → `.lesson-header`（水印光球 + `h1` + `.lesson-summary` + `.source-link`）→ `.lesson-layout`（`minmax(0,1fr) 286px`，正文 + `.toc` 粘性目录）→ `.lesson-content` → `.lesson-nav`（上/下一章）→ `.site-footer`。
- `.lesson-content` 内块级：`h2/h3/h4`、`p`、`ul/ol`、`blockquote`（左侧 3px `--signal` 竖条）、`.table-wrap > table`、`.code-card + .code-toolbar + .copy-code`、`.diagram-card`（mermaid + `figcaption`）、`.term`（术语 tooltip，`data-tip`）。

### 2.3 视觉系统：双主题（CSS 变量 + `data-theme`）

- `theme.css`（L1-7）先加载 `themes/guardnet.css`（深色，**默认**）与 `themes/evergreen.css`（浅色，`[data-theme="evergreen"]`）；`course-theme.css` 再 `@import theme.css + course-shell.css`。
- 令牌示例（完整见附件源）：
  - **guardnet（默认深色）**：`--page:#000` · `--surface:#0a0a0c` · `--ink:#f7f7f8` · `--accent:#8fb1ff` · `--accent-deep:#1e3a8a` · `--line:rgba(255,255,255,.11)` · 字体 `Futura` 系。
  - **evergreen（浅色）**：`--page:#FDF5EB` · `--surface:#fff` · `--ink:#08150C` · `--accent:#08150C` / `--accent-deep:#056949` · 字体 `Georgia/Cooper/Songti` 衬线。
- 切换：`theme-switcher.js` 在 `<head>` **无 defer** 读取 `localStorage["course-theme"]` 并立即设属性避免闪白；`DOMContentLoaded` 后向每个 `.topbar` 注入按钮；切换时按主题重配并重渲染 mermaid。阅读页额外加载 `course.js`（代码高亮、复制、mermaid 初始化、侧栏折叠）与 `reading-progress.js`（localStorage 记录已读章、侧栏打勾）。
- 打印样式：`@media print` 隐藏顶栏/目录/侧栏/复制按钮，正文转 `#17212b/#fff`、`11pt`。
- 无障碍/降级：`:focus-visible` 描边、`prefers-reduced-motion` 关闭平滑滚动。

### 2.4 资产清单（需随发布产物自托管）

| 文件 | 行数 | 作用 |
| --- | --- | --- |
| `assets/course.css` | 20 | 课程级入口：`@import` 主题 + `--course-mark` + 阅读进度样式 |
| `assets/course.js` | 77 | 代码高亮/复制、mermaid 初始化、章节侧栏折叠 |
| `assets/theme-switcher.js` | 141 | 双主题切换与持久化、mermaid 重渲染 |
| `assets/reading-progress.js` | 45 | 已读章节标记 |
| 主题：`theme.css` / `course-theme.css` / `themes/guardnet.css` / `themes/evergreen.css` | 7 / 3 / 57 / 81 | 令牌与主题 |
| 共享组件：`course-shell.css` | 602 | 全部组件样式 |
| 外部依赖 | — | `mermaid@10`（CDN，`defer`） |

---

## 3. 现状与差距

| 维度 | 当前 publish 产物 | 参考实现 |
| --- | --- | --- |
| 详情页 | 有，但为内联极简 CSS 的卡片列表 | hero + 进度面板 + 模块分组卡片 |
| 章节页 | **无**（只落 `lessons/*.md` 原文） | 样式化 HTML（目录/代码卡/图/术语） |
| 术语表 | 无 | 由 `reference/glossary.md` 生成 |
| 主题 | 无 | guardnet/evergreen 双主题 + 切换 |
| 交互 | 无 | 主题切换、复制、侧栏折叠、阅读进度、mermaid |
| 资产 | 无 | 自托管 4 个 js/css + 主题 |

**关键阻塞项**：参考项目**工作树里缺主题 CSS**——`courses/*/assets/course.css` 仍 `@import "../../../assets/course-theme.css"`，但仓库根 `assets/` 与 `apps/web/public/assets/` 中都没有该文件；版本历史里它存在于提交 `129b552`（`apps/web/public/assets/{course-shell,course-theme,theme}.css` + `themes/*.css`）。设计规划阶段已从该提交取回并确认内容。

---

## 4. 目标设计

### 4.1 页面信息架构

```
courses/published/<slug>/
├── index.html            # 详情页：hero → 进度 → 模块分组的章节卡片
├── lessons/NN-<slug>.html# 阅读页：侧栏 + 正文 + 粘性目录 + 上/下一章
├── reference/glossary.html
├── assets/               # 自托管：course.css + 主题 + 3 个 js
├── markdown/NN-*.md       # 原始 Markdown（“查看 Markdown 版本”链接）
└── course.json            # 课程元数据（详情页数据源）
```

### 4.2 详情页布局（自上而下）

1. `topbar`：品牌标题 + 导航（课程目录 / 术语表）+ 主题切换按钮。
2. `course-hero`：`eyebrow`（课程定位标签）→ 标题 → 一句话描述 → `.meta-row`（章数、时长、受众、形态）。
3. `progress-panel`：`已发布章节 / 总章数` + 进度条 + 说明。
4. `module-section` ×N：模块标题 + `chapter-grid` 章节卡片（`available`/`planned`）。
5. `site-footer`：`<课程标题> · 已发布`。

### 4.3 阅读页布局

```
[固定左栏 chapter-nav（模块分组 / 当前章高亮 / 可折叠）] [ lesson-page-main ]
                                                   topbar
                                                   lesson-header（标题+摘要+Markdown 链接）
                                                   lesson-layout
                                                     ├─ lesson-content（正文块）
                                                     │   ├─ code-card / diagram-card
                                                     │   └─ lesson-nav（上/下一章）
                                                     └─ toc（本章目录，粘性）
```

### 4.4 视觉系统（沿用参考，不重新发明）

- 令牌、字体栈、圆角、阴影、动效**逐字沿用**参考主题（guardnet 默认 + evergreen 可选）。
- 一处决定性视觉母题：hero/卡片角落的**柔光球 + 巨型水印字**（`--course-mark`），详情页与阅读页统一。
- 强调色每屏 ≤2 次：链接/当前章/`eyebrow` 用 `--accent` / `--signal`，其余保持中性。

### 4.5 响应式断点（沿用参考）

| 断点 | 行为 |
| --- | --- |
| ≤1240px | 左侧章节栏收成窄条（可点开覆盖） |
| ≤1080px | 章节卡片 3 → 2 列 |
| ≤900px | 正文与目录改单列，目录移顶 |
| ≤680px | 单列、hero 与卡片缩排、上/下一章改纵向 |

### 4.6 状态与细节

- 卡片：`available`（hover 边框加强）/ `planned`（降透明不可点）。
- 代码块：`.code-toolbar` 语言标签 + 「复制」→「已复制」。
- 术语：`[[术语]]` → `.term` tooltip（缺术语表时给兜底文案）。
- 主题：默认深色，切换持久化；mermaid 随主题重渲染。
- 空/降级：无章节 → 空态提示；无术语表 → 不渲染术语表入口。

---

## 5. 内容模型映射（Run → 站点）

| 目标字段 | 来源 | 缺口/处理 |
| --- | --- | --- |
| `title` | `RunContent.title`（= course_input.topic） | 直接可用 |
| `description` | `run.mission.learning_goal`（回退 `goal`） | 直接可用 |
| `lessons[].number/title` | `RunContent.chapters[]` | 直接可用 |
| `lessons[].summary/time` | 章节 Markdown 首个引用块（`预计学习时间：` / `一句话总结：`，见 `course-structure-contract.mjs:42-54`） | **需解析**；缺失时以正文首段兜底 |
| `lessons[].module` | 无 | Run 未产出模块分组；阶段一可全部归入「课程章节」单模块，或按 `expected_chapters` 切分 |
| `lessons[].href/markdown` | 生成期决定 | 生成期写入 |
| `mark/audience/duration` | 无 | 用默认（`mark` 取项目缩写，`duration` 写「人工发布」） |
| 术语表 | 无 | 阶段一可省略入口，或仅用 `[[术语]]` 的兜底 tooltip |

---

## 6. 实现方案（接入 publish pipeline，供实现阶段执行）

> 设计层面建议：**把参考的 `build-static-course.mjs` 渲染逻辑移植为 `-local` 发布管线的一部分**，而不是让发布只输出 Markdown 链接。

1. **主题资产**：从参考仓库提交 `129b552` 取回 `course-shell.css` / `theme.css` / `course-theme.css` / `themes/{guardnet,evergreen}.css`，与 `course.js` / `theme-switcher.js` / `reading-progress.js` 一起，落到发布产物 `published/<slug>/assets/`（去掉 `@import ../../../assets/`，改为同目录 `theme.css`+`course-shell.css`，成为自包含）。同时把这份资产固化为 `-local` 项目内的模板源，避免再次丢失。
2. **渲染器**：在 `-local` 新增 `apps/api/app/v0/static_course.py`（Python 版渲染器），对齐参考 `renderIndex/renderLesson/renderGlossary` 的类名与结构，产出详情页 + 阅读页 + 术语表。
3. **publish 接入**：`publishing.py` 的 `materialize()` 由「写 md + 极简 index」升级为「写真 Markdown 导出 + 渲染 HTML + 复制 assets」；`course.json` 补 `lessons/modules/mark` 等字段。
4. **自包含与预览**：全部用相对路径；沿用 `od-preview-rewrite.mjs` 处理嵌套路由；`/published` 静态挂载已具备。
5. **主题切换默认值**：无 `data-theme` = guardnet；如需发布即浅色，可在 `index.html` 的 `<html data-theme="evergreen">` 写死。

---

## 7. 验收清单（实现阶段逐项核对）

- [ ] 详情页与参考一致：hero、元信息胶囊、进度面板、模块分组卡片齐全。
- [ ] 每章生成样式化 HTML：标题、引用块、列表、表格、代码卡（可复制）、mermaid 图、术语 tooltip。
- [ ] 主题切换可用且持久化；mermaid 随主题重渲染；刷新不闪白。
- [ ] 左侧章节栏可折叠、当前章高亮、已读章节打勾。
- [ ] 上/下一章导航在首章/末章边界正确。
- [ ] 资产全部自托管、相对路径、无外链 CSS/JS（仅 mermaid CDN，可离线降级）。
- [ ] 响应式 1440/1080/768/390 无横向滚动、无溢出遮挡。
- [ ] `@media print` 与 `prefers-reduced-motion` 生效。
- [ ] 已发布课程从「我的课程」移除、进入「已发布」列表、链接可打开。（发布契约不变）
- [ ] 后端 `pytest`/`ruff`、前端 `typecheck`/`build` 通过；新增渲染器有测试。

---

## 8. 风险与开放问题

- **主题资产来源**：参考工作树缺失，需从 git 提交 `129b552` 取回；是否接受把这份资产固化进 `-local`？（建议：接受，并作为模板源。）
- **双主题 vs 单主题**：是否保留 guardnet/evergreen 切换？还是发布时固定一套？（建议：保留，默认深色。）
- **模块分组**：Run 无 `module` 信息。是否按 `expected_chapters` 自动切模块，还是全部归入单模块？（建议：阶段一单模块，后续再补蓝图产出模块。）
- **术语表**：是否纳入？（建议：阶段一省略入口，仅保留 `[[术语]]` 兜底 tooltip。）
- **渲染器语言**：Python 重写 vs 复用参考的 Node 脚本？（建议：Python 重写以随 API 发布，避免引入 Node 运行时依赖。）
- **Markdown 覆盖度**：参考渲染器为自研子集，不支持嵌套列表/引用内多段/任务列表等；需明确“支持范围 + 降级”。

---

## 9. 下一步（Next step）

1. 请审阅本文，确认第 8 节的开放问题（尤其是**双主题取舍**与**资产固化方式**）。
2. 确认后我将按第 6 节产出可执行改造清单（文件级修改点 + 测试），并进入实现。
3. 实现完成后同步更新 `course-publish-plan.md` 与 `agent-delivery-standard.md`。

> 本文仅为设计规划，未改动任何工程代码。可直接在本 Markdown 上批注。
