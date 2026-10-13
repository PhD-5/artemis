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

export interface AppReference {
  name: string;
  icon: string;
  pkg?: string;
  category?: string;
}

export type SuggestionCategory =
  | 'all'
  | 'flash'
  | 'pro'
  | 'cross_app'
  | 'monitor';

export interface SmartSuggestion {
  id: string;
  archived?: boolean;
  title: string;
  description: string;
  goal: string;
  parameters: string[];
  profile: 'flash' | 'pro';
  expectedOutput?: string | null;
  category: 'flash' | 'pro' | 'cross_app' | 'monitor';
  tag: string;
  apps: AppReference[];
  requiredPackages?: string[];
  matchMode?: 'any' | 'all';
  priority?: number;
}

/** Preview a template without interpreting placeholders introduced by argument values. */
export function renderTaskTemplate(goal: string, args: Record<string, string>): string {
  return goal.replace(/\$\$\{[^}]*\}|\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g,
    (token, name: string | undefined) =>
      token.startsWith('$$') ? token.slice(1) : name && Object.prototype.hasOwnProperty.call(args, name) ? args[name] : token
  );
}

