import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { RecommendedTaskManagerComponent } from './recommended-task-manager.component';

const sample = {
  id: 'first', title: 'First task', description: 'Description', goal: 'Do it',
  profile: 'flash', category: 'flash', tag: 'Test', apps: [],
  required_packages: ['pkg'], match_mode: 'any', priority: 50
};

describe('RecommendedTaskManagerComponent', () => {
  let fixture: ComponentFixture<RecommendedTaskManagerComponent>;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [RecommendedTaskManagerComponent], providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(RecommendedTaskManagerComponent);
    fixture.detectChanges();
    http.expectOne('/api/tasks/catalog').flush({ tasks: [sample], app_registry: {} });
    fixture.detectChanges();
  });

  afterEach(() => http.verify());


  it('creates and deletes using the shared catalog only after confirmation', () => {
    const component = fixture.componentInstance;
    component.newTask();
    component.draft.title = 'Custom task';
    component.draft.description = 'Description';
    component.draft.goal = 'Goal';
    component.draft.tag = 'Custom';
    component.save();
    const post = http.expectOne('/api/tasks/presets');
    expect(post.request.body.title).toBe('Custom task');
    expect(post.request.body.parameters).toEqual([]);
    post.flush({ ...sample, id: 'custom', title: 'Custom task', tag: 'Custom' });
    fixture.detectChanges();
    expect(component.recommendations.allTasks().length).toBe(2);
    component.confirmDelete.set('custom');
    expect(component.recommendations.allTasks().length).toBe(2);
    component.remove('custom');
    http.expectOne('/api/tasks/presets/custom').flush(null, { status: 204, statusText: 'No Content' });
    expect(component.recommendations.allTasks().length).toBe(1);
  });

  it('edits and saves parameter names while preserving the raw template goal', () => {
    const component = fixture.componentInstance;
    component.select('first');
    component.edit(component.selectedTask()!);
    component.draft.goal = 'Find ${ITEM} and $${ITEM}';
    component.parametersText = 'ITEM\nitem';
    component.save();
    const put = http.expectOne('/api/tasks/presets/first');
    expect(put.request.body.parameters).toEqual(['ITEM', 'item']);
    expect(put.request.body.goal).toBe('Find ${ITEM} and $${ITEM}');
    put.flush({ ...sample, goal: component.draft.goal, parameters: ['ITEM', 'item'] });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Parameters: ITEM, item');
    component.edit(component.selectedTask()!);
    expect(component.parametersText).toBe('ITEM\nitem');
  });

  it('rejects duplicate or invalid parameter names before saving', () => {
    const component = fixture.componentInstance;
    component.newTask();
    component.parametersText = 'ITEM\nITEM';
    component.save();
    http.expectNone('/api/tasks/presets');
    expect(component.error()).toContain('unique');
    component.parametersText = '9bad';
    component.save();
    http.expectNone('/api/tasks/presets');
    expect(component.error()).toContain('ASCII');
  });
  it('shows field-specific 422 validation errors from the server', () => {
    const component = fixture.componentInstance;
    component.newTask();
    component.save();
    http.expectOne('/api/tasks/presets').flush({
      detail: [{ loc: ['body', 'parameters', 0], msg: 'Invalid parameter name', type: 'value_error' }]
    }, { status: 422, statusText: 'Unprocessable Entity' });
    expect(component.error()).toBe('parameters.0: Invalid parameter name');
  });

});
