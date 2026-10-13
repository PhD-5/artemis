import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, EventEmitter, OnInit, Output, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ProviderConfigurationUpdates, SystemService } from '../../services/system.service';

type ProviderChoice = 'deepseek' | 'zhipu' | 'google' | 'anthropic' | 'openrouter' | 'xai' | 'custom';

@Component({
  selector: 'app-provider-setup',
  standalone: true,
  imports: [FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="provider-setup" aria-label="AI model provider setup">
      <div class="provider-choices" role="group" aria-label="Choose a provider">
        @for (choice of choices; track choice.id) {
          <button type="button" [class.selected]="selected() === choice.id"
            [attr.aria-pressed]="selected() === choice.id" [disabled]="busy()" (click)="choose(choice.id)">
            {{ choice.label }} @if (choice.id === 'deepseek') { <span class="recommended">Recommended</span> }
          </button>
        }
      </div>

      <div class="credential-entry">
        <label for="provider-base-url">{{ selectedLabel() }} Base URL</label>
        <input id="provider-base-url" type="url" autocomplete="off" spellcheck="false"
          [ngModel]="baseUrl()" (ngModelChange)="baseUrl.set($event)"
          [disabled]="busy() || !loaded()" placeholder="Provider API endpoint" />
        <p class="key-status">API key:
          <code>{{ isConfigured() ? '********' : 'Not configured' }}</code>
        </p>
        <label for="provider-key">New API key (overwrite only)</label>
        <input id="provider-key" type="password" autocomplete="new-password" spellcheck="false"
          [ngModel]="apiKey()" (ngModelChange)="apiKey.set($event)"
          [disabled]="busy() || !loaded()" placeholder="Leave blank to keep the existing key" />
        <p>Stored keys cannot be read back. Enter a new key to replace the current one.</p>
        <div class="actions">
          <button type="button" (click)="testConfiguration()" [disabled]="busy() || !canTest()">
            {{ busy() === 'test' ? 'Testing…' : 'Test configuration' }}
          </button>
          <button type="button" (click)="saveConfiguration()" [disabled]="busy() || !canSave()">
            {{ busy() === 'save' ? 'Verifying & saving…' : 'Save configuration' }}
          </button>
        </div>
        @if (!loaded() && !error()) { <p>Loading provider configuration…</p> }
        @if (error()) { <p role="alert" class="error">{{ error() }}</p> }
        @if (message()) { <p role="status" class="success">{{ message() }}</p> }
      </div>

      <div class="actual-config">
        <p><strong>Currently configured default model:</strong>
          @if (system.modelConfigEnv(); as config) {
            {{ config.default_model.provider || 'not specified' }} / {{ config.default_model.model || 'not specified' }}
          } @else { Not available }
        </p>
        <p>Saving provider configuration does not change the selected model. To switch providers, edit
          <code>{{ system.modelConfigEnv()?.config_path || 'config/artemis.jsonc' }}</code>
          and set the model's <code>provider</code> and <code>model</code>.
          An explicit per-model Base URL in JSONC takes precedence over this provider default.</p>
        @if (selected() === 'deepseek') { <p>Example provider: <code>deepseek</code>; use a DeepSeek model name supported by your account.</p> }
        @if (selected() === 'zhipu') { <p>Example provider: <code>zhipu</code>; use a GLM model name supported by your account.</p> }
        @if (selected() === 'google') { <p>Gemini provider name in JSONC: <code>google</code>.</p> }
        @if (selected() === 'custom') { <p>Custom / OpenAI-compatible credentials use provider <code>openai</code>.</p> }
      </div>
    </section>
  `,
  styles: [`
    .provider-setup { display: grid; gap: 1rem; }
    .provider-choices { display: flex; flex-wrap: wrap; gap: .5rem; }
    .provider-choices button, .actions button { padding: .65rem .9rem; cursor: pointer; border: 1px solid #777; border-radius: .5rem; background: transparent; color: inherit; }
    .provider-choices button.selected { border-color: #4085df; box-shadow: inset 0 0 0 1px #4085df; }
    .recommended { margin-left: .25rem; font-size: .8em; color: #338f68; }
    .credential-entry { display: grid; gap: .6rem; }
    .credential-entry input { min-width: 0; max-width: 32rem; padding: .7rem; border-radius: .5rem; border: 1px solid #777; }
    .actions { display: flex; gap: .5rem; }
    button:disabled { opacity: .5; cursor: not-allowed; }
    .error { color: #d64646; } .success { color: #338f68; }
    .actual-config { overflow-wrap: anywhere; }
  `]
})
export class ProviderSetupComponent implements OnInit {
  readonly system = inject(SystemService);
  @Output() readonly credentialsSaved = new EventEmitter<void>();

  readonly choices: ReadonlyArray<{ id: ProviderChoice; label: string }> = [
    { id: 'deepseek', label: 'DeepSeek' },
    { id: 'zhipu', label: 'Zhipu' },
    { id: 'google', label: 'Gemini' },
    { id: 'anthropic', label: 'Anthropic' },
    { id: 'openrouter', label: 'OpenRouter' },
    { id: 'xai', label: 'xAI' },
    { id: 'custom', label: 'Custom / OpenAI-compatible' }
  ];
  readonly selected = signal<ProviderChoice>('deepseek');
  readonly apiKey = signal('');
  readonly baseUrl = signal('');
  readonly loaded = signal(false);
  readonly provider = computed(() => this.selected() === 'custom' ? 'openai' : this.selected());
  private readonly configuration = computed(() =>
    this.system.providerConfigurations().find(item => item.name === this.provider())
  );
  readonly canSave = computed(() =>
    this.loaded() && !!this.baseUrl().trim()
    && (this.baseUrl().trim() !== this.configuration()?.base_url || !!this.apiKey().trim())
  );
  readonly canTest = computed(() =>
    this.loaded() && !!this.baseUrl().trim() && (this.isConfigured() || !!this.apiKey().trim())
  );
  readonly busy = signal<false | 'test' | 'save'>(false);
  readonly error = signal<string | null>(null);
  readonly message = signal<string | null>(null);

  ngOnInit(): void {
    this.system.fetchProviderConfigurations().subscribe({
      next: () => {
        this.restoreBaseUrl();
        this.loaded.set(true);
      },
      error: () => this.error.set('Unable to load provider configuration.')
    });
    this.system.fetchModelConfigEnv().subscribe({ error: () => {
      this.error.set('Unable to load the current model configuration.');
    } });
  }

  selectedLabel(): string {
    return this.choices.find(choice => choice.id === this.selected())?.label || '';
  }

  isConfigured(): boolean {
    return this.configuration()?.configured ?? false;
  }

  choose(provider: ProviderChoice): void {
    if (this.busy()) return;
    this.selected.set(provider);
    this.apiKey.set('');
    this.restoreBaseUrl();
    this.error.set(null);
    this.message.set(null);
  }

  testConfiguration(): void {
    if (this.busy() || !this.canTest()) return;
    const updates: ProviderConfigurationUpdates = { base_url: this.baseUrl().trim() };
    const key = this.apiKey().trim();
    if (key) updates.api_key = key;
    this.busy.set('test');
    this.error.set(null);
    this.message.set(null);
    this.system.testProviderConfiguration(this.provider(), updates).subscribe({
      next: () => this.message.set(`${this.selectedLabel()} configuration verified.`),
      error: (err: unknown) => this.error.set(this.failureMessage(err, 'Could not verify provider configuration.'))
    }).add(() => this.busy.set(false));
  }

  saveConfiguration(): void {
    if (this.busy() || !this.canSave()) return;
    const updates: ProviderConfigurationUpdates = {};
    const url = this.baseUrl().trim();
    if (url !== this.configuration()?.base_url) updates.base_url = url;
    const key = this.apiKey().trim();
    if (key) updates.api_key = key;
    this.busy.set('save');
    this.error.set(null);
    this.message.set(null);
    this.system.updateProviderConfiguration(this.provider(), updates).subscribe({
      next: () => {
        this.apiKey.set('');
        this.restoreBaseUrl();
        this.message.set(`${this.selectedLabel()} configuration saved. Model selection unchanged.`);
        this.credentialsSaved.emit();
      },
      error: (err: unknown) => this.error.set(this.failureMessage(err, 'Could not save provider configuration.'))
    }).add(() => this.busy.set(false));
  }

  private restoreBaseUrl(): void {
    this.baseUrl.set(this.configuration()?.base_url ?? '');
  }

  private failureMessage(error: unknown, fallback: string): string {
    if (error instanceof HttpErrorResponse &&
        error.error && typeof error.error === 'object' &&
        'detail' in error.error && typeof error.error.detail === 'string') {
      return error.error.detail;
    }
    return fallback;
  }

}
