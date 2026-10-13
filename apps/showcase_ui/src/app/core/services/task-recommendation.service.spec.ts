import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { TaskRecommendationService } from './task-recommendation.service';

const sample = {
  id: 'one', title: 'Task', description: 'Description', goal: 'Do it',
  profile: 'flash', category: 'flash', tag: 'Test', apps: [],
  required_packages: ['app.one', 'app.two'], match_mode: 'all', priority: 90
};

describe('TaskRecommendationService', () => {
  let service: TaskRecommendationService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    service = TestBed.inject(TaskRecommendationService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('loads the persisted catalog and maps snake_case fields, keeping all/any matches distinct', () => {
    service.loadCatalog().subscribe();
    http.expectOne('/api/tasks/catalog').flush({ tasks: [sample, { ...sample, id: 'two', match_mode: 'any' }], app_registry: {} });
    expect(service.allTasks().length).toBe(2);
    expect(service.allTasks()[0].parameters).toEqual([]);
    expect(service.allTasks()[0].requiredPackages).toEqual(['app.one', 'app.two']);
    expect(service.isSuggestionOnDevice(service.allTasks()[0], new Set(['app.one']))).toBeFalse();
    expect(service.isSuggestionOnDevice(service.allTasks()[1], new Set(['app.one']))).toBeTrue();
    expect(service.filterAndRankTasks(new Set(['app.one']), 'all').map(task => task.id)).toEqual(['two', 'one']);
  });

  it('updates one shared signal on CRUD and retains an empty catalog after deletion', () => {
    service.loadCatalog().subscribe();
    http.expectOne('/api/tasks/catalog').flush({ tasks: [], app_registry: {} });
    expect(service.allTasks()).toEqual([]);
    service.createPreset({ title: sample.title, description: sample.description, goal: sample.goal, parameters: ['APP'], profile: 'flash', category: 'flash', tag: sample.tag, apps: [], requiredPackages: sample.required_packages, matchMode: 'all' }).subscribe();
    const post = http.expectOne('/api/tasks/presets');
    expect(post.request.body.required_packages).toEqual(sample.required_packages);
    expect(post.request.body.match_mode).toBe('all');
    expect(post.request.body.parameters).toEqual(['APP']);
    post.flush({ ...sample, parameters: ['APP'] });
    expect(service.allTasks()[0].id).toBe('one');
    expect(service.allTasks()[0].parameters).toEqual(['APP']);
    service.updatePreset('one', { ...service.allTasks()[0], title: 'Edited' }).subscribe();
    http.expectOne('/api/tasks/presets/one').flush({ ...sample, title: 'Edited' });
    expect(service.allTasks()[0].title).toBe('Edited');
    service.deletePreset('one').subscribe();
    http.expectOne('/api/tasks/presets/one').flush(null, { status: 204, statusText: 'No Content' });
    expect(service.allTasks()).toEqual([]);
  });
});
