/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { HttpClient } from '@angular/common/http';
import { computed, Injectable, inject, signal } from '@angular/core';
import { map, Observable, tap } from 'rxjs';
import { AppReference, SmartSuggestion, SuggestionCategory } from '../data/smart-tasks.data';

interface PresetResponse extends Omit<SmartSuggestion, 'parameters' | 'requiredPackages' | 'matchMode' | 'expectedOutput'> {
  parameters?: string[];
  required_packages: string[];
  match_mode: 'any' | 'all';
  expected_output?: string | null;
}

interface CatalogResponse {
  tasks: PresetResponse[];
  app_registry: Record<string, AppReference>;
}

export type TaskPresetInput = Omit<SmartSuggestion, 'id' | 'archived'>;

function toSuggestion(task: PresetResponse): SmartSuggestion {
  const { required_packages, match_mode, expected_output, ...fields } = task;
  return { ...fields, parameters: task.parameters ?? [], requiredPackages: required_packages, matchMode: match_mode, expectedOutput: expected_output };
}

function toPayload(task: TaskPresetInput): Omit<PresetResponse, 'id'> {
  const { requiredPackages, matchMode, expectedOutput, ...fields } = task;
  return {
    ...fields,
    parameters: task.parameters ?? [],
    required_packages: requiredPackages ?? [],
    match_mode: matchMode ?? 'any',
    expected_output: task.profile === 'pro' ? expectedOutput?.trim() || null : null
  };
}

@Injectable({ providedIn: 'root' })
export class TaskRecommendationService {
  private readonly http = inject(HttpClient);
  private readonly tasksState = signal<SmartSuggestion[]>([]);
  private readonly registryState = signal<Record<string, AppReference>>({});
  /** Complete, unfiltered live catalog; management and suggestions share this state. */
  public readonly allTasks = this.tasksState.asReadonly();
  public readonly activeTasks = computed(() => this.allTasks().filter(task => !task.archived));
  public readonly archivedTasks = computed(() => this.allTasks().filter(task => task.archived));
  public readonly appRegistry = this.registryState.asReadonly();

  public loadCatalog(): Observable<SmartSuggestion[]> {
    return this.http.get<CatalogResponse>('/api/tasks/catalog').pipe(
      tap(catalog => this.registryState.set(catalog.app_registry)),
      map(catalog => catalog.tasks.map(toSuggestion)),
      tap(tasks => this.tasksState.set(tasks))
    );
  }

  public getPreset(id: string): Observable<SmartSuggestion> {
    return this.http.get<PresetResponse>(`/api/tasks/presets/${encodeURIComponent(id)}`).pipe(map(toSuggestion));
  }

  public createPreset(input: TaskPresetInput): Observable<SmartSuggestion> {
    return this.http.post<PresetResponse>('/api/tasks/presets', toPayload(input)).pipe(
      map(toSuggestion),
      tap(task => this.tasksState.update(tasks => [...tasks, task]))
    );
  }

  public updatePreset(id: string, input: TaskPresetInput): Observable<SmartSuggestion> {
    return this.http.put<PresetResponse>(`/api/tasks/presets/${encodeURIComponent(id)}`, toPayload(input)).pipe(
      map(toSuggestion),
      tap(task => this.tasksState.update(tasks => tasks.map(existing => existing.id === id ? task : existing)))
    );
  }

  public setArchived(id: string, archived: boolean): Observable<SmartSuggestion> {
    return this.http.patch<PresetResponse>(`/api/tasks/presets/${encodeURIComponent(id)}/archive`, { archived }).pipe(
      map(toSuggestion),
      tap(task => this.tasksState.update(tasks => tasks.map(existing => existing.id === id ? task : existing)))
    );
  }

  public deletePreset(id: string): Observable<void> {
    return this.http.delete<void>(`/api/tasks/presets/${encodeURIComponent(id)}`).pipe(
      tap(() => this.tasksState.update(tasks => tasks.filter(task => task.id !== id)))
    );
  }

  public isSuggestionOnDevice(suggestion: SmartSuggestion, installedPackages: Set<string>): boolean {
    if (installedPackages.size === 0) return false;
    if (!suggestion.requiredPackages || suggestion.requiredPackages.length === 0) return true;
    if (suggestion.matchMode === 'all') {
      return suggestion.requiredPackages.every(pkg => installedPackages.has(pkg));
    }
    return suggestion.requiredPackages.some(pkg => installedPackages.has(pkg));
  }

  /** Pure rank/filter/rotation over the latest catalog; never discards unmatched tasks. */
  public filterAndRankTasks(
    installedPackages: Set<string>,
    category: SuggestionCategory,
    shuffleOffset: number = 0
  ): SmartSuggestion[] {
    const hasDevice = installedPackages.size > 0;
    const scored = this.activeTasks().map(task => {
      const isMatched = this.isSuggestionOnDevice(task, installedPackages);
      let score = task.priority ?? 50;
      if (hasDevice) {
        if (isMatched) {
          score += 100;
          if (task.requiredPackages && task.requiredPackages.length > 1 && task.matchMode === 'all') score += 30;
        } else {
          score -= 40;
        }
      }
      return { task, score };
    });
    const filtered = scored.filter(item => {
      if (category === 'flash' || category === 'pro') return item.task.profile === category;
      if (category === 'cross_app' || category === 'monitor') return item.task.category === category;
      return true;
    });
    filtered.sort((a, b) => b.score - a.score);
    const result = filtered.map(item => item.task);
    if (shuffleOffset > 0 && result.length > 0) {
      const shift = shuffleOffset % result.length;
      return [...result.slice(shift), ...result.slice(0, shift)];
    }
    return result;
  }
}
