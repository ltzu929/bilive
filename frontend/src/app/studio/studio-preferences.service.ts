import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

export interface StudioPreferences {
  refreshInterval: number;
  compactQueue: boolean;
  collapseSidebar: boolean;
}

const STORAGE_KEY = 'bilive-studio-preferences';
const DEFAULTS: StudioPreferences = {
  refreshInterval: 30,
  compactQueue: false,
  collapseSidebar: false,
};

@Injectable({ providedIn: 'root' })
export class StudioPreferencesService {
  readonly preferences$ = new BehaviorSubject<StudioPreferences>(this.read());

  get value(): StudioPreferences {
    return this.preferences$.value;
  }

  save(patch: Partial<StudioPreferences>): StudioPreferences {
    const next: StudioPreferences = {
      ...this.value,
      ...patch,
      refreshInterval: this.clampInterval(patch.refreshInterval ?? this.value.refreshInterval),
      compactQueue: Boolean(patch.compactQueue ?? this.value.compactQueue),
      collapseSidebar: Boolean(patch.collapseSidebar ?? this.value.collapseSidebar),
    };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Browser storage is optional; the in-memory preference still applies.
    }
    this.preferences$.next(next);
    return next;
  }

  private read(): StudioPreferences {
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
      return {
        refreshInterval: this.clampInterval(Number(stored.refreshInterval || DEFAULTS.refreshInterval)),
        compactQueue: Boolean(stored.compactQueue),
        collapseSidebar: Boolean(stored.collapseSidebar),
      };
    } catch {
      return { ...DEFAULTS };
    }
  }

  private clampInterval(value: number): number {
    return Math.min(300, Math.max(5, Number.isFinite(value) ? value : DEFAULTS.refreshInterval));
  }
}
