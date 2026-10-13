import { ChangeDetectionStrategy, Component, inject, input, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { SystemService } from '../../services/system.service';

@Component({
  selector: 'app-task-device-selector',
  standalone: true,
  imports: [FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="target-picker">
      <label>
        <span>Target Android device</span>
        <select aria-label="Target Android device" [disabled]="disabled()"
          [ngModel]="system.selectedTaskDevice()?.serial || ''"
          (ngModelChange)="system.selectTaskDevice($event)">
          <option value="" disabled>Select a device</option>
          @for (device of system.connectedDevices(); track device.serial) {
            <option [value]="device.serial" [disabled]="device.state !== 'device'">
              {{ device.model || device.serial }} · {{ device.serial }} ·
              {{ device.state !== 'device' ? device.state : device.is_locked === true ? 'Locked' : device.is_locked === false ? 'Ready' : 'Lock state unknown' }}
            </option>
          }
        </select>
      </label>
      <button type="button" [disabled]="disabled() || system.isLoading()"
        (click)="system.fetchReadiness(false, true).subscribe()">Refresh devices</button>
    </div>
    @if (system.selectedTaskDevice(); as selected) {
      @if (selected.state === 'device' && selected.is_locked !== false) {
        <p class="target-info" role="status">
          {{ selected.is_locked === true ? 'Selected device is locked.' : 'Selected device lock state is unknown.' }}
          The task will try to wake and unlock it. If a PIN, password, or pattern is required, the task will fail; credentials will not be guessed.
        </p>
      }
    }
    @if (system.taskDeviceIssue()) {
      <p class="target-warning" role="status">{{ system.taskDeviceIssue() }}</p>
    }
  `,
  styles: `
    :host { display: block; min-width: 0; }
    .target-picker { display: flex; align-items: end; gap: 12px; flex-wrap: wrap; padding: 12px 0; }
    label { display: grid; gap: 6px; flex: 1; min-width: 180px; font-size: 12px; color: var(--text-secondary, #94a3b8); }
    select, button { border: 1px solid rgba(148,163,184,.3); border-radius: 10px; padding: 9px 12px; background: var(--bg-secondary, #18202e); color: var(--text-primary, #e2e8f0); font: inherit; }
    select { width: 100%; }
    button { cursor: pointer; font-size: 12px; }
    :disabled { opacity: .55; cursor: not-allowed; }
    .target-warning { margin: 0 0 12px; color: #fbbf24; font-size: 12px; }
    .target-info { margin: 0 0 12px; color: var(--text-secondary, #94a3b8); font-size: 12px; line-height: 1.5; }
  `
})
export class TaskDeviceSelectorComponent implements OnInit {
  public system = inject(SystemService);
  public disabled = input(false);

  ngOnInit(): void {
    if (!this.system.hasReadinessReport()) this.system.fetchReadiness(true).subscribe({ error: () => {} });
    if (!this.system.adbServerStatus()) this.system.fetchAdbServerStatus().subscribe({ error: () => {} });
  }
}
