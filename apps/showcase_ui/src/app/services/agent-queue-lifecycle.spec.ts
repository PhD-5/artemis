import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { AgentService } from './agent.service';
import { AgentStatusResponse, TaskQueueItem } from '../core/models/session.model';

type Snapshot = AgentStatusResponse & {
  active_tasks: { session_id: string; device_id: string }[];
};

const queued: TaskQueueItem = {
  session_id: 'queued-task', goal: 'Queued task', status: 'pending', start_time: 100
};
const otherQueued: TaskQueueItem = {
  session_id: 'other-queued-task', goal: 'Other task', status: 'pending', start_time: 101
};
const idle: Snapshot = { status: 'idle', session_id: null, queue: [], active_tasks: [] };
const running: Snapshot = {
  status: 'running', session_id: 'active-task', goal: 'Active task', queue: [],
  active_tasks: [{ session_id: 'active-task', device_id: 'device-two' }]
};

describe('AgentService queue lifecycle', () => {
  let service: AgentService;
  let http: HttpTestingController;

  function replyToSnapshot(snapshot: Snapshot): void {
    http.expectOne('/api/status').flush(snapshot);
    for (const request of http.match('/api/sessions')) request.flush([]);
  }

  function poll(snapshot: Snapshot): void {
    service.fetchStatus();
    replyToSnapshot(snapshot);
  }

  beforeEach(() => {
    localStorage.removeItem('artemis.sessions.v1');
    spyOn(window, 'EventSource').and.returnValue(
      jasmine.createSpyObj<EventSource>('EventSource', ['addEventListener', 'close'])
    );
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()]
    });
    service = TestBed.inject(AgentService);
    http = TestBed.inject(HttpTestingController);
    service.destroy(); // Poll explicitly; no timers or live transport in this fixture.
    service.currentSessionId.set('viewed-history');
    service.userPinnedSessionId.set('viewed-history');
    http.expectOne('/api/sessions').flush([]);
    replyToSnapshot(idle);
  });

  afterEach(() => {
    service.destroy();
    http.verify();
    localStorage.removeItem('artemis.sessions.v1');
  });

  it('does not resurrect a cancelled queue-only task after subsequent polls', () => {
    poll({ ...idle, queue: [queued] });
    expect(service.sessions().map(s => s.status)).toEqual(['pending']);
    service.stopTask(queued.session_id);
    http.expectOne('/api/stop?all=false&session_id=queued-task').flush({ status: 'stopped' });
    replyToSnapshot(idle);
    expect(service.sessions()).toEqual([]);
    poll(idle);
    poll(idle);
    expect(service.sessions()).toEqual([]);
    expect(service.isRunningTask()).toBeFalse();
  });

  it('cancels only the selected task and keeps another task queued', () => {
    poll({ ...idle, queue: [queued, otherQueued] });
    expect(service.sessions().map(s => s.session_id)).toEqual([
      otherQueued.session_id, queued.session_id
    ]);
    service.stopTask(queued.session_id);
    http.expectOne('/api/stop?all=false&session_id=queued-task').flush({ status: 'stopped' });
    replyToSnapshot({ ...idle, queue: [otherQueued] });
    expect(service.sessions().map(s => [s.session_id, s.status])).toEqual([
      [otherQueued.session_id, 'pending']
    ]);
  });

  it('does not restore a deleted task while another device remains active', () => {
    poll({ ...running, queue: [queued] });
    expect(service.sessions().some(s => s.session_id === queued.session_id)).toBeTrue();
    service.deleteSession(queued.session_id).subscribe();
    http.expectOne('/api/sessions/queued-task/delete').flush({ status: 'success' });
    replyToSnapshot(running);
    expect(service.sessions().map(s => [s.session_id, s.status])).toEqual([
      ['active-task', 'running']
    ]);
  });

  it('drops an absent queue-only task when the backend is idle, even with a historical session ID', () => {
    poll({ ...idle, queue: [queued] });
    expect(service.sessions().some(s => s.session_id === queued.session_id)).toBeTrue();
    poll({ ...idle, session_id: 'historical-session' });
    expect(service.sessions()).toEqual([]);
    expect(service.isRunningTask()).toBeFalse();
  });

  it('keeps failed history and allows another retry after admission is rejected', () => {
    const failed = {
      session_id: 'failed-task', initial_goal: 'Read battery level', status: 'failed', start_time: 50
    };
    service.fetchSessions();
    http.expectOne('/api/sessions').flush([failed]);

    service.retrySession(failed, new Event('click'));
    service.retrySession(failed, new Event('click'));
    const request = http.expectOne('/api/run'); // Double-click must not enqueue twice.
    expect(request.request.body).toEqual({ goal: 'Read battery level', profile: 'flash' });
    expect(service.retryingSessionId()).toBe(failed.session_id);
    request.flush({ status: 'rejected', error: 'Target device is offline', tasks: [] });
    expect(service.retryingSessionId()).toBeNull();
    expect(service.retrySubmissionError()).toBe('Target device is offline');
    expect(service.sessions().find(s => s.session_id === failed.session_id)?.status).toBe('failed');

    service.retrySession(failed, new Event('click'));
    expect(service.retrySubmissionError()).toBeNull();
    http.expectOne('/api/run').flush('Unavailable', { status: 503, statusText: 'Unavailable' });
    expect(service.retryingSessionId()).toBeNull();
    expect(service.retrySubmissionError()).toContain('Failed to retry task');
  });

  it('keeps cancelled history when its retry is rejected', () => {
    const cancelled = {
      session_id: 'cancelled-task', initial_goal: 'Read battery level', status: 'cancelled', start_time: 50
    };
    service.fetchSessions();
    http.expectOne('/api/sessions').flush([cancelled]);
    service.retrySession(cancelled, new Event('click'));
    expect(service.retryingSessionId()).toBe(cancelled.session_id);
    http.expectOne('/api/run').flush({ status: 'rejected', error: 'Device offline', tasks: [] });
    expect(service.retryingSessionId()).toBeNull();
    expect(service.retrySubmissionError()).toBe('Device offline');
    expect(service.sessions().find(s => s.session_id === cancelled.session_id)?.status).toBe('cancelled');
  });

  it('submits templates with args instead of a goal and preserves explicit settings', () => {
    service.runTask({
      templateId: 'task-template', args: { ITEM: '', APP: 'Mail' },
      profile: 'pro', expectedOutput: '', deviceSerial: 'device-one'
    }).subscribe();
    const request = http.expectOne('/api/run');
    expect(request.request.body).toEqual({
      template_id: 'task-template', args: { ITEM: '', APP: 'Mail' },
      profile: 'pro', expected_output: '', device_serial: 'device-one'
    });
    request.flush({ status: 'queued', tasks: [] });
  });

  it('keeps template profile/output omitted when no override is requested', () => {
    service.runTask({ templateId: 'task-template', args: {} }).subscribe();
    const request = http.expectOne('/api/run');
    expect(request.request.body).toEqual({ template_id: 'task-template', args: {} });
    request.flush({ status: 'queued', tasks: [] });
  });

  it('never resubmits an active or successful run', () => {
    for (const status of ['running', 'paused', 'pending', 'completed', 'success']) {
      service.retrySession({
        session_id: 'not-failed', initial_goal: 'Read battery level', status, start_time: 50
      }, new Event('click'));
    }
    http.expectNone('/api/run');
    expect(service.retryingSessionId()).toBeNull();
  });
});
