import { Component, computed, ElementRef, EventEmitter, inject, OnInit, Output, signal, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { SmartSuggestion } from '../../core/data/smart-tasks.data';
import { TaskPresetInput, TaskRecommendationService } from '../../core/services/task-recommendation.service';
import { taskErrorDetail, toRunTaskPayload } from '../../services/agent.service';

@Component({
  selector: 'app-recommended-task-manager',
  standalone: true,
  imports: [FormsModule],
  template: `
    <details #managerDisclosure class="manager-disclosure">
      <summary>Manage recommended tasks · New / Edit / Archive / Delete</summary>
    <section class="preset-manager" aria-label="Recommended task manager">
      <header>
        <h2>Recommended Tasks</h2>
        <button class="primary" type="button" [disabled]="saving()" (click)="newTask()">New task</button>
      </header>
      @if (loading()) { <p role="status">Loading tasks…</p> }
      @if (archivePendingId()) { <p role="status">Updating template archive status…</p> }
      @if (error()) { <p role="alert">{{ error() }}</p> }
      <div class="template-tabs" role="tablist" aria-label="Template status">
        <button id="active-templates-tab" type="button" role="tab" aria-controls="template-list"
          [attr.aria-selected]="templateView() === 'active'" [disabled]="saving()" (click)="switchView('active')">
          Active templates ({{ recommendations.activeTasks().length }})
        </button>
        <button id="archived-templates-tab" type="button" role="tab" aria-controls="template-list"
          [attr.aria-selected]="templateView() === 'archived'" [disabled]="saving()" (click)="switchView('archived')">
          Archived Templates ({{ recommendations.archivedTasks().length }})
        </button>
      </div>
      <div class="layout" id="template-list" role="tabpanel"
        [attr.aria-labelledby]="templateView() === 'active' ? 'active-templates-tab' : 'archived-templates-tab'">
        <ul [attr.aria-label]="templateView() === 'active' ? 'Active templates' : 'Archived Templates'">
          @for (task of visibleTasks(); track task.id) {
            <li><button type="button" (click)="select(task.id)" [attr.aria-current]="selectedId() === task.id ? 'true' : null">{{ task.title }}</button></li>
          } @empty {
            @if (!loading() && !error()) {
              <li>{{ templateView() === 'active' ? 'No active templates saved.' : 'No archived templates.' }}</li>
            }
          }
        </ul>
        <div class="detail">
          @if (mode() === 'view' && selectedTask(); as task) {
            <h3>{{ task.title }}</h3>
            <p>{{ task.description }}</p>
            <p class="template-id"><strong>template_id:</strong> <code>{{ task.id }}</code></p>
            <p><strong>Goal:</strong> {{ task.goal }}</p>
            <p><strong>Parameters:</strong> {{ task.parameters?.join(', ') || 'None' }}</p>
            <p><strong>Profile:</strong> {{ task.profile }} · {{ task.category }} · {{ task.tag }}</p>
            @if (task.profile === 'pro' && task.expectedOutput) {
              <p><strong>Expected Output:</strong> {{ task.expectedOutput }}</p>
            }
            <p><strong>Apps:</strong> @for (app of task.apps; track $index) { {{ app.name }} } @empty { None }</p>
            <p><strong>Required packages:</strong> {{ task.requiredPackages?.join(', ') || 'None' }} ({{ task.matchMode || 'any' }})</p>
            <p><strong>Priority:</strong> {{ task.priority ?? 50 }}</p>
            <button type="button" [disabled]="saving()" (click)="setArchived(task)">
              {{ archivePendingId() === task.id ? (task.archived ? 'Unarchiving…' : 'Archiving…') : (task.archived ? 'Unarchive' : 'Archive') }}
            </button>
            <button type="button" class="copy-api-json" (click)="copyApiJson(task)">
              {{ copiedId() === task.id ? 'Copied!' : 'Copy API JSON' }}
            </button>
            <p class="copy-json-hint">Copies a POST /api/run request with empty argument values. {{ task.archived ? 'Unarchive this template before using it.' : 'Use task to fill them.' }}</p>
            @if (task.archived) {
              <p role="status">This template is archived and cannot be used until it is unarchived.</p>
            } @else {
              <button class="primary" type="button" [disabled]="saving()" (click)="useTask.emit(task)">Use task</button>
            }
            <button type="button" [disabled]="saving()" (click)="edit(task)">Edit</button>
            @if (confirmDelete() === task.id) {
              <p class="delete-warning">Delete this task permanently?</p>
              <button class="danger" type="button" [disabled]="saving()" (click)="remove(task.id)">Confirm delete</button>
              <button type="button" (click)="confirmDelete.set(null)">Cancel</button>
            } @else {
              <button class="danger" type="button" [disabled]="saving()" (click)="confirmDelete.set(task.id)">Delete</button>
            }
          }
          @if (mode() === 'new' || mode() === 'edit') {
            <h3>{{ mode() === 'new' ? 'New task' : 'Edit task' }}</h3>
            <form #taskForm="ngForm" (ngSubmit)="save()">
              <label>Title <input name="title" [(ngModel)]="draft.title" required /></label>
              <label>Description <textarea name="description" [(ngModel)]="draft.description" required></textarea></label>
              <label>Goal template <textarea name="goal" [(ngModel)]="draft.goal" required placeholder="e.g. Find \${ITEM} in \${APP}; use $\${ITEM} for a literal placeholder"></textarea></label>
              <label>Parameters (one name per line, case-sensitive) <textarea name="parameters" [(ngModel)]="parametersText" placeholder="ITEM&#10;APP"></textarea></label>
              <label>Profile <select name="profile" [(ngModel)]="draft.profile"><option value="flash">Flash</option><option value="pro">Pro</option></select></label>
              @if (draft.profile === 'pro') {
                <label>Expected Output (optional)
                  <textarea name="expectedOutput" [(ngModel)]="draft.expectedOutput" placeholder="Specify an output format or JSON schema; leave blank for no preset."></textarea>
                </label>
              }
              <label>Category <select name="category" [(ngModel)]="draft.category"><option value="flash">Flash</option><option value="pro">Pro</option><option value="cross_app">Cross app</option><option value="monitor">Monitor</option></select></label>
              <label>Tag <input name="tag" [(ngModel)]="draft.tag" required /></label>
              <fieldset>
                <legend>Apps</legend>
                @for (app of draft.apps; track $index; let i = $index) {
                  <div class="app-row">
                    <label>Name <input [name]="'app-name-' + i" [(ngModel)]="app.name" required /></label>
                    <label>Icon
                      <span class="icon-picker">
                        <select [name]="'app-icon-' + i" [(ngModel)]="app.icon" required>
                          <option value="" disabled>Select an icon</option>
                          @for (option of iconOptions(); track option.value) {
                            <option [value]="option.value">{{ option.label }}</option>
                          }
                        </select>
                        @if (app.icon) {
                          <span class="icon-preview" role="img" [attr.aria-label]="'Icon preview: ' + app.icon" [title]="app.icon">
                            <span class="material-symbols-outlined" aria-hidden="true">{{ app.icon }}</span>
                          </span>
                        }
                      </span>
                    </label>
                    <label>Package <input [name]="'app-pkg-' + i" [(ngModel)]="app.pkg" required /></label>
                    <label>Category <input [name]="'app-category-' + i" [(ngModel)]="app.category" /></label>
                    <button class="danger" type="button" (click)="draft.apps.splice(i, 1)">Remove app</button>
                  </div>
                }
                <button type="button" (click)="addApp()">Add app</button>
              </fieldset>
              <label>Required packages (one per line) <textarea name="requiredPackages" [(ngModel)]="packagesText"></textarea></label>
              <label>Match mode <select name="matchMode" [(ngModel)]="draft.matchMode"><option value="any">Any</option><option value="all">All</option></select></label>
              <label>Priority <input name="priority" type="number" [(ngModel)]="draft.priority" required /></label>
              <button class="primary" type="submit" [disabled]="saving() || taskForm.invalid">{{ saving() ? 'Saving…' : 'Save task' }}</button>
              <button type="button" [disabled]="saving()" (click)="cancel()">Cancel</button>
            </form>
          }
        </div>
      </div>
    </section>
    </details>
  `,
  styles: [`
    :host { display: block; color: #1e293b; color-scheme: light; }
    .manager-disclosure { margin-bottom: 20px; padding: 14px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; }
    summary { cursor: pointer; font-size: 13px; font-weight: 600; color: #475569; border-radius: 4px; }
    summary:hover { color: #1d4ed8; }
    .preset-manager { padding: 1rem 0 0; }
    .preset-manager header, .layout { display: flex; gap: 1rem; }
    .preset-manager header { justify-content: space-between; align-items: center; }
    .template-tabs { display: flex; flex-wrap: wrap; gap: .4rem; margin: .6rem 0; }
    .template-tabs button[aria-selected="true"] { color: #1d4ed8; background: #eff6ff; border-color: #2563eb; font-weight: 600; }
    h2 { font-size: 16px; }
    h2, h3, strong { color: #0f172a; }
    .layout > ul { flex: 1; max-height: 28rem; overflow: auto; list-style: none; padding: 0; min-width: 160px; }
    .layout > .detail { flex: 2; min-width: 0; padding: 14px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; }
    li { margin-bottom: 6px; }
    li button { width: 100%; margin: 0; text-align: left; overflow-wrap: anywhere; }
    form, .app-row { display: grid; gap: .6rem; }
    form label { display: grid; gap: .3rem; font-size: 13px; color: #475569; }
    .icon-picker { display: flex; align-items: center; gap: 10px; }
    .icon-picker select { flex: 1; }
    .icon-preview { display: inline-flex; align-items: center; justify-content: center; flex: 0 0 40px; height: 40px; border: 1px solid #cbd5e1; border-radius: 8px; background: #eff6ff; color: #1d4ed8; }
    .icon-preview .material-symbols-outlined { font-size: 24px; }
    fieldset { min-width: 0; margin: 0; padding: 12px; border: 1px solid #cbd5e1; border-radius: 8px; }
    legend { padding: 0 4px; color: #475569; font-size: 13px; }
    button, input, textarea, select { color: #1e293b; background: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px 10px; font: inherit; min-width: 0; max-width: 100%; box-sizing: border-box; }
    input, textarea, select { width: 100%; }
    input:hover, textarea:hover, select:hover { border-color: #94a3b8; }
    input:focus, textarea:focus, select:focus { border-color: #2563eb; outline: 2px solid #2563eb; outline-offset: 2px; }
    textarea { min-height: 70px; resize: vertical; }
    button { cursor: pointer; margin: 3px; font-size: 12px; font-weight: 500; }
    button:hover:not(:disabled) { background: #f1f5f9; border-color: #94a3b8; }
    button[aria-current="true"] { color: #1d4ed8; background: #eff6ff; border-color: #2563eb; font-weight: 600; }
    button[aria-current="true"]:hover:not(:disabled) { background: #dbeafe; border-color: #2563eb; }
    button.primary { color: #ffffff; background: #1d4ed8; border-color: #1d4ed8; }
    button.primary:hover:not(:disabled) { background: #1e40af; border-color: #1e40af; }
    button.danger { color: #b91c1c; background: #fff1f2; border-color: #fda4af; }
    button.danger:hover:not(:disabled) { background: #ffe4e6; border-color: #e11d48; }
    button:focus-visible, summary:focus-visible { outline: 2px solid #2563eb; outline-offset: 2px; }
    button:disabled { color: #64748b; background: #f1f5f9; border-color: #cbd5e1; cursor: not-allowed; }
    p { overflow-wrap: anywhere; font-size: 13px; line-height: 1.6; }
    .template-id code { user-select: text; overflow-wrap: anywhere; }
    .copy-json-hint { color: #64748b; font-size: 12px; }
    [role="status"] { color: #475569; }
    [role="alert"], .delete-warning { color: #b91c1c; background: #fff1f2; border: 1px solid #fda4af; border-radius: 8px; padding: 10px 12px; }
    @media (max-width: 640px) { .layout { flex-direction: column; } .layout > ul { max-height: 12rem; } }
  `]
})
export class RecommendedTaskManagerComponent implements OnInit {
  public readonly recommendations = inject(TaskRecommendationService);
  @ViewChild('managerDisclosure') private managerDisclosure?: ElementRef<HTMLDetailsElement>;
  @Output() readonly useTask = new EventEmitter<SmartSuggestion>();
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly archivePendingId = signal<string | null>(null);
  readonly error = signal<string | null>(null);
  readonly mode = signal<'list' | 'view' | 'edit' | 'new'>('list');
  readonly templateView = signal<'active' | 'archived'>('active');
  readonly visibleTasks = computed(() => this.templateView() === 'active'
    ? this.recommendations.activeTasks() : this.recommendations.archivedTasks());
  readonly selectedId = signal<string | null>(null);
  readonly confirmDelete = signal<string | null>(null);
  readonly selectedTask = computed(() => this.visibleTasks().find(task => task.id === this.selectedId()));
  readonly copiedId = signal<string | null>(null);

  async copyApiJson(task: SmartSuggestion): Promise<void> {
    const json = JSON.stringify(toRunTaskPayload({
      templateId: task.id,
      args: Object.fromEntries(task.parameters.map(name => [name, '']))
    }), null, 2);
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(json);
      this.copiedId.set(task.id);
      setTimeout(() => {
        if (this.copiedId() === task.id) this.copiedId.set(null);
      }, 2000);
    } catch {
      this.error.set('Could not copy. Allow clipboard access and use localhost or HTTPS.');
    }
  }
  readonly iconOptions = computed(() => {
    const options = new Map<string, string>();
    const apps = [
      ...Object.values(this.recommendations.appRegistry()),
      ...this.recommendations.allTasks().flatMap(task => task.apps)
    ];
    for (const app of apps) {
      if (app.icon && !options.has(app.icon)) {
        options.set(app.icon, `${app.name} (${app.icon})`);
      }
    }
    return Array.from(options, ([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label));
  });
  draft: TaskPresetInput = this.emptyDraft();
  packagesText = '';
  parametersText = '';

  ngOnInit(): void {
    this.loading.set(true);
    this.recommendations.loadCatalog().subscribe({
      next: () => this.loading.set(false),
      error: () => { this.error.set('Could not load tasks.'); this.loading.set(false); }
    });
  }


  private emptyDraft(): TaskPresetInput {
    return { title: '', description: '', goal: '', parameters: [], profile: 'flash', category: 'flash', tag: '', apps: [], requiredPackages: [], matchMode: 'any', priority: 50 };
  }

  openArchived(): void {
    if (this.managerDisclosure) this.managerDisclosure.nativeElement.open = true;
    this.switchView('archived');
  }

  switchView(view: 'active' | 'archived'): void {
    this.templateView.set(view);
    this.selectedId.set(null);
    this.mode.set('list');
    this.confirmDelete.set(null);
    this.error.set(null);
  }

  select(id: string): void {
    if (this.saving()) return;
    this.selectedId.set(id);
    this.mode.set('view');
    this.confirmDelete.set(null);
    this.error.set(null);
  }

  newTask(): void {
    if (this.saving()) return;
    this.templateView.set('active');
    this.selectedId.set(null);
    this.draft = this.emptyDraft();
    this.packagesText = '';
    this.parametersText = '';
    this.mode.set('new');
    this.error.set(null);
    this.confirmDelete.set(null);
  }

  edit(task: SmartSuggestion): void {
    if (this.saving()) return;
    this.draft = { title: task.title, description: task.description, goal: task.goal, parameters: [...(task.parameters ?? [])], profile: task.profile, category: task.category, tag: task.tag, apps: task.apps.map(app => ({ ...app })), requiredPackages: [...(task.requiredPackages ?? [])], matchMode: task.matchMode ?? 'any', priority: task.priority ?? 50 };
    this.draft.expectedOutput = task.expectedOutput ?? '';
    this.packagesText = this.draft.requiredPackages?.join('\n') ?? '';
    this.parametersText = this.draft.parameters?.join('\n') ?? '';
    this.mode.set('edit');
    this.error.set(null);
  }

  addApp(): void {
    this.draft.apps.push({ name: '', icon: '', pkg: '', category: 'general' });
  }

  cancel(): void {
    this.mode.set(this.selectedId() ? 'view' : 'list');
    this.error.set(null);
  }

  save(): void {
    if (this.saving()) return;
    const parameters = this.parametersText.split(/\r?\n/).map(name => name.trim()).filter(Boolean);
    if (parameters.some(name => !/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) || new Set(parameters).size !== parameters.length) {
      this.error.set('Parameter names must be unique ASCII identifiers (letters, digits and underscores; no leading digit).');
      return;
    }
    this.saving.set(true);
    this.error.set(null);
    const payload = { ...this.draft, parameters, requiredPackages: this.packagesText.split(/\r?\n/).map(pkg => pkg.trim()).filter(Boolean) };
    const request = this.mode() === 'edit' && this.selectedId()
      ? this.recommendations.updatePreset(this.selectedId()!, payload)
      : this.recommendations.createPreset(payload);
    request.subscribe({
      next: task => {
        this.saving.set(false);
        if ((task.archived ? 'archived' : 'active') === this.templateView()) {
          this.select(task.id);
        } else {
          this.selectedId.set(null);
          this.mode.set('list');
        }
      },
      error: err => { this.saving.set(false); this.error.set(taskErrorDetail(err.error?.detail) || 'Could not save task.'); }
    });
  }

  setArchived(task: SmartSuggestion): void {
    if (this.saving()) return;
    this.saving.set(true);
    this.archivePendingId.set(task.id);
    this.error.set(null);
    this.recommendations.setArchived(task.id, !task.archived).subscribe({
      next: () => {
        this.saving.set(false);
        this.archivePendingId.set(null);
        this.selectedId.set(null);
        this.mode.set('list');
        this.confirmDelete.set(null);
      },
      error: err => {
        this.saving.set(false);
        this.archivePendingId.set(null);
        this.error.set(taskErrorDetail(err.error?.detail) || `Could not ${task.archived ? 'unarchive' : 'archive'} task.`);
      }
    });
  }

  remove(id: string): void {
    if (this.saving()) return;
    this.saving.set(true);
    this.error.set(null);
    this.recommendations.deletePreset(id).subscribe({
      next: () => { this.saving.set(false); this.selectedId.set(null); this.mode.set('list'); this.confirmDelete.set(null); },
      error: () => { this.saving.set(false); this.error.set('Could not delete task.'); }
    });
  }
}
