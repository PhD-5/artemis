import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ProviderSetupComponent } from './provider-setup.component';
import { ProviderConfiguration, SystemService } from '../../services/system.service';

const config = {
  config_path: '/configured/artemis.jsonc', config_filename: 'artemis.jsonc',
  config_content: '{"default":{"provider":"google","model":"gemini-existing"}}',
  default_model: { provider: 'google', model: 'gemini-existing' }, presets: {},
  env_path: '/configured/.env', env_filename: '.env', env_vars: []
};
const providers: ProviderConfiguration[] = [
  { name: 'deepseek', configured: true, base_url: 'https://api.deepseek.com', api_key: '********' },
  { name: 'zhipu', configured: false, base_url: 'https://open.bigmodel.cn/api/paas/v4', api_key: null },
  { name: 'google', configured: true, base_url: 'https://generativelanguage.googleapis.com', api_key: '********' },
  { name: 'openai', configured: true, base_url: 'https://custom.example/v1', api_key: '********' }
];
const report = {
  overall_ready: true, blocker_count: 0, passed_blocker_count: 0,
  probes: [], active_device: null, os_type: 'darwin', timestamp: 1
};

describe('ProviderSetupComponent', () => {
  let http: HttpTestingController;

  async function setup(): Promise<ComponentFixture<ProviderSetupComponent>> {
    const fixture = TestBed.createComponent(ProviderSetupComponent);
    fixture.detectChanges();
    http.expectOne('/api/system/credentials').flush({ providers });
    http.expectOne('/api/system/model-config-env').flush(config);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    return fixture;
  }


  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [ProviderSetupComponent],
      providers: [provideHttpClient(withXhr()), provideHttpClientTesting()]
    });
    http = TestBed.inject(HttpTestingController);
    TestBed.inject(SystemService).stopAutoPolling();
  });

  afterEach(() => http.verify());

  it('loads the readable URL and changes it without reading or clearing the stored key', async () => {
    const fixture = await setup();
    const component = fixture.componentInstance;
    const input: HTMLInputElement = fixture.nativeElement.querySelector('#provider-base-url');
    const key: HTMLInputElement = fixture.nativeElement.querySelector('#provider-key');
    expect(component.selected()).toBe('deepseek');
    expect(input.value).toBe('https://api.deepseek.com');
    expect(key.type).toBe('password');
    expect(key.value).toBe('');
    expect(component.canSave()).toBeFalse();

    input.value = 'https://deepseek-proxy.example/v1';
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    const save: HTMLButtonElement = fixture.nativeElement.querySelector('.actions button:last-child');
    expect(save.disabled).toBeFalse();
    save.click();
    const request = http.expectOne('/api/system/credentials');
    expect(request.request.body.base_url).toBe('https://deepseek-proxy.example/v1');
    expect('api_key' in request.request.body).toBeFalse();
    request.flush({ status: 'success', provider: 'deepseek', configuration: {
      name: 'deepseek', configured: true, base_url: 'https://deepseek-proxy.example/v1', api_key: '********'
    }, report });
    http.expectOne('/api/system/model-config-env').flush(config);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(key.value).toBe('');
    expect(component.isConfigured()).toBeTrue();
    expect(component.canSave()).toBeFalse();
    expect(fixture.nativeElement.textContent).toContain('google / gemini-existing');
  });

  it('overwrites a key, erases the draft after saving, and retains the selected model', async () => {
    const fixture = await setup();
    const component = fixture.componentInstance;
    const key: HTMLInputElement = fixture.nativeElement.querySelector('#provider-key');
    key.value = 'replacement-private-key';
    key.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    fixture.nativeElement.querySelector('.actions button:last-child').click();
    const request = http.expectOne('/api/system/credentials');
    expect(request.request.body.api_key).toBe('replacement-private-key');
    expect('base_url' in request.request.body).toBeFalse();
    request.flush({ status: 'success', provider: 'deepseek', configuration: providers[0], report });
    http.expectOne('/api/system/model-config-env').flush(config);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(component.apiKey()).toBe('');
    expect(key.value).toBe('');
    expect(fixture.nativeElement.textContent).not.toContain('replacement-private-key');
    expect(fixture.nativeElement.textContent).toContain('google / gemini-existing');
  });

  it('tests a modified URL with the server-side key without sending its masked value', async () => {
    const fixture = await setup();
    const component = fixture.componentInstance;
    component.baseUrl.set('https://test-proxy.example/v1');
    fixture.detectChanges();
    fixture.nativeElement.querySelector('.actions button:first-child').click();
    const request = http.expectOne('/api/system/credentials/test');
    expect(request.request.body.base_url).toBe('https://test-proxy.example/v1');
    expect('api_key' in request.request.body).toBeFalse();
    request.flush({ valid: true, provider: 'deepseek', message: 'Verified' });
    fixture.detectChanges();
    expect(component.apiKey()).toBe('');
    expect(component.baseUrl()).toBe('https://test-proxy.example/v1');
    expect(component.canSave()).toBeTrue();
    http.expectNone('/api/system/credentials');
  });

  it('does not apply rejected credentials and clears drafts when switching providers', async () => {
    const fixture = await setup();
    const component = fixture.componentInstance;
    component.apiKey.set('draft-for-deepseek');
    component.choose('zhipu');
    expect(component.apiKey()).toBe('');
    expect(component.baseUrl()).toBe('https://open.bigmodel.cn/api/paas/v4');
    component.apiKey.set('bad-zhipu-key');
    component.saveConfiguration();
    http.expectOne('/api/system/credentials').flush(
      { detail: 'Invalid key' }, { status: 400, statusText: 'Bad Request' }
    );
    expect(component.isConfigured()).toBeFalse();
    expect(component.error()).toBe('Invalid key');
    component.choose('custom');
    expect(component.apiKey()).toBe('');
    expect(component.baseUrl()).toBe('https://custom.example/v1');
    expect(component.isConfigured()).toBeTrue();
    expect(component.error()).toBeNull();
  });
});
