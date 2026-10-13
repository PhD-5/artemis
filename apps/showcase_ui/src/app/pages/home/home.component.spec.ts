import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { provideRouter } from '@angular/router';
import { AgentService } from '../../services/agent.service';
import { SystemService } from '../../services/system.service';
import { TaskRecommendationService } from '../../core/services/task-recommendation.service';
import { HomeComponent } from './home.component';
import { of } from 'rxjs';
import { SmartSuggestion, renderTaskTemplate } from '../../core/data/smart-tasks.data';

const report = {
  overall_ready: true, blocker_count: 0, passed_blocker_count: 0,
  probes: [], active_device: null, os_type: 'darwin', timestamp: 1
};
const modelConfig = {
  config_path: '/configured/artemis.jsonc', config_filename: 'artemis.jsonc',
  config_content: '{}', default_model: {}, presets: {},
  env_path: '/configured/.env', env_filename: '.env', env_vars: []
};

describe('HomeComponent OCR credential editor', () => {
  let http: HttpTestingController;
  let component: HomeComponent;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HomeComponent],
      providers: [
        provideRouter([]), provideHttpClient(withXhr()), provideHttpClientTesting(),
        { provide: AgentService, useValue: {} },
        { provide: TaskRecommendationService, useValue: {} }
      ]
    });
    TestBed.overrideComponent(HomeComponent, { set: { template: '' } });
    http = TestBed.inject(HttpTestingController);
    const system = TestBed.inject(SystemService);
    system.stopAutoPolling();
    system.fetchProviderConfigurations().subscribe();
    http.expectOne('/api/system/credentials').flush({ providers: [
      { name: 'ocr', configured: true, base_url: null, api_key: '********' }
    ] });
    component = TestBed.createComponent(HomeComponent).componentInstance;
  });

  afterEach(() => http.verify());

  it('keeps stored credentials out of the draft and erases newly saved credentials', () => {
    expect(component.isOcrConfigured()).toBeTrue();
    expect(component.ocrKeyInput()).toBe('');
    component.onOcrKeyChange('********');
    component.saveOcrKey();
    http.expectNone('/api/system/credentials');
    expect(component.isSavingOcrKey()).toBeFalse();

    component.onOcrKeyChange('new-private-credential');
    component.saveOcrKey();
    expect(component.isSavingOcrKey()).toBeTrue();
    http.expectOne('/api/system/credentials').flush({
      status: 'success', provider: 'ocr', message: 'saved', report,
      configuration: { name: 'ocr', configured: true, base_url: null, api_key: '********' }
    });
    http.expectOne('/api/system/model-config-env').flush(modelConfig);
    expect(component.isSavingOcrKey()).toBeFalse();
    expect(component.ocrKeyInput()).toBe('');
    expect(component.showOcrKey()).toBeFalse();
  });

  it('discards drafts on navigation and only clears a configured key after confirmation', () => {
    component.onOcrKeyChange('private-draft');
    component.toggleOcrConfig();
    expect(component.ocrKeyInput()).toBe('');
    component.onOcrKeyChange('second-draft');
    component.setTab('diagnostics');
    http.expectOne('/api/system/readiness').flush(report);
    http.expectOne('/api/system/model-config-env').flush(modelConfig);
    expect(component.ocrKeyInput()).toBe('');

    spyOn(window, 'confirm').and.returnValues(false, true);
    component.clearOcrKey();
    http.expectNone('/api/system/credentials');
    expect(component.isOcrConfigured()).toBeTrue();
    component.clearOcrKey();
    http.expectOne('/api/system/credentials').flush({
      status: 'success', provider: 'ocr', message: 'cleared', report,
      configuration: { name: 'ocr', configured: false, base_url: null, api_key: null }
    });
    http.expectOne('/api/system/model-config-env').flush(modelConfig);
    expect(component.isOcrConfigured()).toBeFalse();
    expect(component.ocrKeyInput()).toBe('');
    expect(component.isSavingOcrKey()).toBeFalse();
  });
});

describe('HomeComponent template composer', () => {
  const template: SmartSuggestion = {
    id: 'preset-1', title: 'Search', description: 'Search an app',
    goal: 'Find ${ITEM} again ${ITEM} in ${APP}; literal $${ITEM}; nested $${anything!}',
    parameters: ['ITEM', 'APP'], profile: 'flash', category: 'flash', tag: 'Search', apps: []
  };

  it('renders repeated arguments once without expanding argument placeholders and respects escapes', () => {
    expect(renderTaskTemplate(template.goal, { ITEM: '${APP}', APP: 'Mail' }))
      .toBe('Find ${APP} again ${APP} in Mail; literal ${ITEM}; nested ${anything!}');
    expect(renderTaskTemplate('Keep $ and ${MISSING} and $${ITEM}', { ITEM: 'hi' }))
      .toBe('Keep $ and ${MISSING} and ${ITEM}');
  });

  it('requires explicit arguments and clears them when switching template or input mode', () => {
    // Do not start diagnostics polling: the composer state is independent of it.
    const fixture = TestBed.configureTestingModule({
      imports: [HomeComponent],
      providers: [
        provideRouter([]), provideHttpClient(withXhr()), provideHttpClientTesting(),
        { provide: AgentService, useValue: { runTask: jasmine.createSpy('runTask').and.returnValue(of({ tasks: [] })) } }
      ]
    }).createComponent(HomeComponent);
    const home = fixture.componentInstance;
    const runTask = TestBed.inject(AgentService).runTask as jasmine.Spy;
    const system = TestBed.inject(SystemService);
    spyOn(system, 'canSubmitTask').and.returnValue(true);
    spyOn(system, 'taskDeviceIssue').and.returnValue(null);
    spyOn(TestBed.inject(Router), 'navigate').and.returnValue(Promise.resolve(true));
    home.applySuggestion(template);
    expect(home.missingParameters()).toEqual(['ITEM', 'APP']);
    home.runTask();
    expect(runTask).not.toHaveBeenCalled();
    home.setTemplateArg('ITEM', '');
    home.setTemplateArg('APP', 'Mail');
    expect(home.missingParameters()).toEqual([]);
    expect(home.templatePreview()).toBe('Find  again  in Mail; literal ${ITEM}; nested ${anything!}');
    home.applySuggestion({ ...template, id: 'preset-2', parameters: ['OTHER'] });
    expect(home.templateArgs()).toEqual({});
    expect(home.missingParameters()).toEqual(['OTHER']);
    home.applyQuickPrompt('Manual');
    expect(home.selectedTemplate()).toBeNull();
    expect(home.templateArgs()).toEqual({});
    expect(home.taskGoal()).toBe('Manual');
    fixture.destroy();
  });
});
