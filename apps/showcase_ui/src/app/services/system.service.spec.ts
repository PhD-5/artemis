import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { DeviceInfo, SystemReadinessReport } from '../core/models/system.model';
import { SystemService } from './system.service';

describe('SystemService readiness polling', () => {
  let service: SystemService;
  let http: HttpTestingController;

  const report = (timestamp: number): SystemReadinessReport => ({
    overall_ready: true,
    blocker_count: 3,
    passed_blocker_count: 3,
    probes: [],
    active_device: null,
    os_type: 'windows',
    timestamp
  });

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        SystemService,
        provideHttpClient(withXhr()),
        provideHttpClientTesting()
      ]
    });
    service = TestBed.inject(SystemService);
    http = TestBed.inject(HttpTestingController);
    service.stopAutoPolling();
  });

  afterEach(() => http.verify());

  it('shares one HTTP request across overlapping readiness callers', () => {
    let firstTimestamp = 0;
    let secondTimestamp = 0;

    service.fetchReadiness().subscribe(value => firstTimestamp = value.timestamp);
    service.fetchReadiness(true).subscribe(value => secondTimestamp = value.timestamp);

    const request = http.expectOne('/api/system/readiness');
    request.flush(report(10));

    expect(firstTimestamp).toBe(10);
    expect(secondTimestamp).toBe(10);
    expect(service.readinessReport()?.timestamp).toBe(10);
    expect(service.isLoading()).toBeFalse();
  });

  it('does not let an older snapshot replace a newer report', () => {
    service.fetchReadiness().subscribe();
    http.expectOne('/api/system/readiness').flush(report(20));

    service.fetchReadiness().subscribe();
    http.expectOne('/api/system/readiness').flush(report(10));

    expect(service.readinessReport()?.timestamp).toBe(20);
  });

  it('requests a forced backend refresh for a manual re-check', () => {
    service.fetchReadiness(false, true).subscribe();

    const request = http.expectOne(req =>
      req.url === '/api/system/readiness' && req.params.get('force') === 'true'
    );
    expect(request.request.params.get('force')).toBe('true');
    request.flush(report(30));
  });

  it('loads the active ADB server endpoint', () => {
    service.fetchAdbServerStatus().subscribe();

    const request = http.expectOne('/api/system/adb/server');
    request.flush({
      endpoint: {
        host: '127.0.0.1',
        port: 5038,
        socket: 'tcp:127.0.0.1:5038',
        mode: 'remote',
        is_local_default: false
      }
    });

    expect(service.isRemoteAdbServer()).toBeTrue();
    expect(service.adbServerStatus()?.endpoint.port).toBe(5038);
  });

  it('activates an ADB server endpoint and applies its readiness report', () => {
    service.connectAdbServer('127.0.0.1', 5038, true).subscribe();

    const request = http.expectOne('/api/system/adb/server/connect');
    expect(request.request.body).toEqual({
      host: '127.0.0.1',
      port: 5038,
      persist: true
    });
    request.flush({
      connection_result: {
        success: true,
        message: 'Connected.',
        endpoint: {
          host: '127.0.0.1',
          port: 5038,
          socket: 'tcp:127.0.0.1:5038',
          mode: 'remote',
          is_local_default: false
        },
        devices: []
      },
      report: report(40)
    });

    expect(service.isRemoteAdbServer()).toBeTrue();
    expect(service.readinessReport()?.timestamp).toBe(40);
  });

  it('probes an ADB server without changing the active endpoint', () => {
    service.probeAdbServer('127.0.0.1', 5038).subscribe();

    const request = http.expectOne('/api/system/adb/server/probe');
    expect(request.request.body).toEqual({
      host: '127.0.0.1',
      port: 5038,
      persist: false
    });
    request.flush({
      connection_result: {
        success: true,
        message: 'Endpoint is reachable.',
        endpoint: {
          host: '127.0.0.1',
          port: 5038,
          socket: 'tcp:127.0.0.1:5038',
          identity: 'tcp:127.0.0.1:5038',
          mode: 'remote',
          is_local_default: false
        },
        devices: []
      }
    });

    expect(service.adbServerStatus()).toBeNull();
  });

  it('restores the standard local ADB server explicitly', () => {
    service.useLocalAdbServer(true).subscribe();

    const request = http.expectOne(req =>
      req.url === '/api/system/adb/server/local' && req.params.get('persist') === 'true'
    );
    request.flush({
      connection_result: {
        success: true,
        message: 'Using local ADB.',
        endpoint: {
          host: '127.0.0.1',
          port: 5037,
          socket: 'tcp:127.0.0.1:5037',
          mode: 'local',
          is_local_default: true
        },
        devices: []
      },
      report: report(50)
    });

    expect(service.isRemoteAdbServer()).toBeFalse();
    expect(service.adbServerStatus()?.endpoint.port).toBe(5037);
  });

  describe('task-scoped device selection', () => {
    const device = (serial: string, locked: boolean | null = false): DeviceInfo => ({
      serial, state: 'device', model: serial, product: null,
      android_version: null, screen_resolution: null, is_locked: locked, is_emulator: false
    });
    function setDevices(devices: DeviceInfo[], adbStatus: 'pass' | 'warn' = 'pass'): void {
      service.readinessReport.set({
        ...report(100),
        overall_ready: adbStatus === 'pass',
        active_device: null,
        probes: ['python_runtime', 'system_config', 'toolchain', 'gemini_api_key', 'android_adb'].map(id => ({
          id, category: 'runtime', status: id === 'android_adb' ? adbStatus : 'pass', title: id,
          summary: id === 'android_adb' && adbStatus === 'warn'
            ? devices.some(device => device.is_locked === true) ? 'Device Locked' : 'Lock State Unknown'
            : 'Ready',
          description: '', is_blocker: true, actions: [], metadata: id === 'android_adb' ? { installed: true, devices } : {}
        }))
      });
      TestBed.tick();
    }
    beforeEach(() => {
      service.adbServerStatus.set({
        endpoint: {
          host: '127.0.0.1', port: 5037, socket: 'tcp:127.0.0.1:5037',
          identity: 'tcp:127.0.0.1:5037', mode: 'local', is_local_default: true
        }
      });
    });

    it('does not silently replace a disconnected target with another device', () => {
      setDevices([device('first')]);
      expect(service.selectedTaskDevice()?.serial).toBe('first');
      expect(service.canSubmitTask()).toBeTrue();
      setDevices([device('second')]);
      expect(service.selectedTaskDevice()).toBeNull();
      expect(service.taskTarget()?.serial).toBe('first');
      expect(service.canSubmitTask()).toBeFalse();
      service.selectTaskDevice('second');
      expect(service.selectedTaskDevice()?.serial).toBe('second');
      expect(service.canSubmitTask()).toBeTrue();
    });

    it('accepts an explicitly selected locked or unknown-lock device despite a warning diagnostic', () => {
      setDevices([device('locked', true), device('unknown', null)], 'warn');
      service.selectTaskDevice('locked');
      expect(service.adbProbe()?.status).toBe('warn');
      expect(service.taskDeviceIssue()).toBeNull();
      expect(service.isDeviceReady()).toBeTrue();
      expect(service.isReady()).toBeTrue();
      expect(service.canSubmitTask()).toBeTrue();

      setDevices([device('unknown', null)], 'warn');
      service.selectTaskDevice('unknown');
      expect(service.adbProbe()?.summary).toBe('Lock State Unknown');
      expect(service.selectedTaskDevice()?.serial).toBe('unknown');
      expect(service.taskDeviceIssue()).toBeNull();
      expect(service.isReady()).toBeTrue();
      expect(service.canSubmitTask()).toBeTrue();
    });

    it('blocks offline and unauthorized selected devices even when another device is usable', () => {
      setDevices([device('target'), device('other')]);
      service.selectTaskDevice('target');
      setDevices([{ ...device('target', true), state: 'offline' }, device('other')], 'warn');
      expect(service.selectedTaskDevice()?.serial).toBe('target');
      expect(service.taskDeviceIssue()).toContain('offline');
      expect(service.canSubmitTask()).toBeFalse();

      setDevices([{ ...device('target', null), state: 'unauthorized' }, device('other')], 'warn');
      expect(service.taskDeviceIssue()).toContain('unauthorized');
      expect(service.canSubmitTask()).toBeFalse();
    });

    it('does not mark an offline or unauthorized device as setup-ready', () => {
      setDevices([{ ...device('offline', null), state: 'offline' }]);
      expect(service.isDeviceReady()).toBeFalse();
      expect(service.isReady()).toBeFalse();
      setDevices([{ ...device('unauthorized'), state: 'unauthorized' }], 'warn');
      expect(service.isDeviceReady()).toBeFalse();
      expect(service.isReady()).toBeFalse();
    });

    it('still requires valid credentials and environment prerequisites with a locked device', () => {
      setDevices([device('locked', true)], 'warn');
      expect(service.canSubmitTask()).toBeTrue();
      const readyReport = service.readinessReport()!;
      service.readinessReport.set({
        ...readyReport,
        probes: readyReport.probes.map(probe =>
          probe.id === 'gemini_api_key' ? { ...probe, status: 'warn' } : probe
        )
      });
      expect(service.canSubmitTask()).toBeFalse();

      service.readinessReport.set({
        ...readyReport,
        probes: readyReport.probes.map(probe =>
          probe.id === 'python_runtime' ? { ...probe, status: 'fail' } : probe
        )
      });
      expect(service.canSubmitTask()).toBeFalse();
    });

    it('requires selection again after changing the ADB server', () => {
      setDevices([device('same-serial')]);
      const endpoint = service.adbServerStatus()!.endpoint;
      service.adbServerStatus.set({ endpoint: { ...endpoint, port: 5038, identity: 'tcp:127.0.0.1:5038' } });
      TestBed.tick();
      expect(service.selectedTaskDevice()).toBeNull();
      expect(service.canSubmitTask()).toBeFalse();
      service.selectTaskDevice('same-serial');
      expect(service.canSubmitTask()).toBeTrue();
    });
  });
});
