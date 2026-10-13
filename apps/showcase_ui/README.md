# ✨ Artemis Showcase & User Workspace UI

A presentation and interaction frontend built with **Angular 22** and **SCSS** for the Artemis mobile autonomous agent.

## 🎨 Visual Design Highlights

* **Aurora Glow Dynamics**: Ambient background lighting with smooth gradients.
* **Glassmorphism Aesthetic**: Translucent frosted-glass panels with subtle borders.
* **Real-time Dual-Pane Workspace**:
  - **Left Pane (`app-agent-stream`)**: Live streaming of Agent thought steps, plan breakdowns, tool actions, and status.
  - **Right Pane (`app-chat-interface`)**: Natural language chat input sidebar with interactive feedback and status pills.

## 🚀 How to Run

### Prerequisites
- Node.js 22.22.3+, 24.15.0+, or 26+ (Angular 22 supported release lines; use an LTS version).
- Backend API running on `http://localhost:8000` (via `apps/admin_console` or `artemis ui`)

### Development Server
```bash
cd apps/showcase_ui
npm install
npm start
```
This runs `ng serve --proxy-config proxy.conf.json` on **`http://localhost:4200/`**.

### Production Build
```bash
npm run build
```
Build artifacts will be emitted to `dist/`, which can be served statically by `apps.admin_console` or `artemis ui`.

## Model setup and task management

Setup recommends DeepSeek, with Zhipu, Gemini and custom provider options. Keys can be tested and saved without overwriting the existing JSONC model configuration. Optional OCR configuration remains separate.

Recommended Tasks uses the backend SQLite catalog. Expand **Manage recommended tasks** for the full catalog, details, create/edit forms and confirmed deletion. Each task can declare ordered, case-sensitive parameter names (one ASCII identifier per line). Keep `${NAME}` in the Goal template and use `$${NAME}` to show a literal `${NAME}`. **Use task** selects the template in the Home composer; enter each declared parameter (an explicitly entered empty value is allowed) and review the read-only, single-pass preview before running. Switching to a different template resets arguments; **Edit as custom task** or a quick prompt switches back to an ordinary goal. The recommendation cards retain category filtering, device-app matching and shuffle.

Each Recommended List card has **Copy** immediately to the left of **Use** in its bottom-right corner. Copy writes the template's `POST /api/run` JSON (`template_id` plus all declared arguments as empty strings) without selecting the card, changing the current task draft or submitting a task. Use still selects the template for parameter entry.

Selecting a template displays its **Expected Output** directly below the task preview in a multiline field, preserving JSON and line breaks. Pro allows per-run edits or **Clear expected output**; an untouched field inherits the saved template value. Flash keeps saved output visible as read-only, with structured output editing available after switching to Pro. Switching templates restores the newly selected template's saved output; editing the launch form does not update the persisted template.

Template details and the selected-template composer show the selectable `template_id` and a **Copy API JSON** button. Details copy a minimal `{ "template_id": "...", "args": { "NAME": "" } }` request for `POST /api/run`, with empty strings for every declared parameter. The composer copies entered arguments plus the current device, tuning and explicit profile/output overrides using the same serializer as task submission; unentered arguments remain empty strings in the copy. Copying never submits a task or saves changes to the template. Clipboard access requires localhost or HTTPS and browser permission.

The template manager follows the Home page's light palette: white controls, dark text, blue primary actions and selected tasks, and red deletion/error messages. Hover, keyboard focus and disabled states remain distinct; narrow screens stack the catalog above the form.

The shared Admin Debug Console at `/admin` and `/debug` also supports **Task template** mode. Select a saved template, fill its arguments, and review the rendered preview. **Use template architecture** inherits its profile; selecting Flash or Pro overrides it. Manual mode still submits a raw goal. Switching templates clears argument values, and switching back to manual mode clears the template reference.

All declared arguments are required, including names not used in the prompt; unknown arguments and non-string values are rejected before device probing or queue reservation. Explicit empty strings are valid values. Template execution uses a server-rendered goal snapshot, so editing or deleting a template cannot alter a task already admitted to the queue.

On startup, persisted presets created before `parameters` existed are upgraded atomically: active `${NAME}` placeholders become unique declarations in first-occurrence order; escaped `$${NAME}` placeholders are excluded. IDs, prompt text and other metadata are preserved, and existing explicit parameter lists are never overwritten. New and edited templates still require explicit declarations for their placeholders.

Setup displays detected devices without global active-device selection. The Home and Workspace composers share a browser-local target device; each `/api/run` submission sends `device_serial`. Connected authorized targets remain submittable when locked or when lock state is unknown. After acquiring the execution lease, the worker wakes the device and attempts to dismiss a nonsecure keyguard before UI initialization. A PIN/password/pattern requirement, failed unlock or unverifiable state produces a failed task without credential entry. Lock state remains visible as informational guidance, not a submission blocker. Recommendation app matching follows the selected target. Disconnection or ADB server changes require reselection rather than silently retargeting an existing choice.

### Task-template API

- `GET /api/tasks/catalog`: full `{ tasks, app_registry }` catalog.
- `GET /api/tasks/presets`: existing filtered/device-aware recommendations.
- `POST /api/tasks/presets`: create a template; returns 201 with a server-generated ID.
- `GET /api/tasks/presets/{id}` / `PUT /api/tasks/presets/{id}`: view/full update.
- `DELETE /api/tasks/presets/{id}`: confirmed UI deletion; API returns 204.

Payload fields are `title`, `description`, `goal` (the template prompt), `parameters` (ordered string identifiers, default `[]`), `profile`, `category`, `tag`, `apps`, `required_packages`, `match_mode`, `priority` and optional `expected_output`. Missing IDs return 404; invalid fields return 422. The Angular service maps snake_case wire fields to the existing camelCase view model. Templates are seeded transactionally once, not whenever the table is empty. Home submits `{ "template_id": "...", "args": { "NAME": "value" } }` to `POST /api/run` (along with selected device and optional run settings), never the preview as a goal. Raw goals still use the normal `{ "goal": "..." }` request; retries use the saved session's original goal even if a template changes or is deleted.
