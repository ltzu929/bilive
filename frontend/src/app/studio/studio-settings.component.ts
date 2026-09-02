import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  OnInit,
} from '@angular/core';
import { NzMessageService } from 'ng-zorro-antd/message';
import { StudioApiService } from './studio-api.service';
import { StudioPreferencesService } from './studio-preferences.service';

@Component({
  selector: 'app-studio-settings',
  templateUrl: './studio-settings.component.html',
  styleUrls: ['./studio-settings.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StudioSettingsComponent implements OnInit {
  loading = true;
  dashboardSettings: Record<string, any> = {};
  refreshInterval = 30;
  compactQueue = false;
  collapseSidebar = false;

  constructor(
    private api: StudioApiService,
    private message: NzMessageService,
    private changeDetector: ChangeDetectorRef,
    private preferences: StudioPreferencesService
  ) {}

  ngOnInit(): void {
    const stored = this.preferences.value;
    this.refreshInterval = stored.refreshInterval;
    this.compactQueue = stored.compactQueue;
    this.collapseSidebar = stored.collapseSidebar;
    this.api.getDashboardSettings().subscribe({
      next: (settings) => {
        this.dashboardSettings = settings || {};
        this.loading = false;
        this.changeDetector.markForCheck();
      },
      error: () => {
        this.loading = false;
        this.changeDetector.markForCheck();
      },
    });
  }

  save(): void {
    this.preferences.save({
      refreshInterval: this.refreshInterval,
      compactQueue: this.compactQueue,
      collapseSidebar: this.collapseSidebar,
    });
    this.message.success('工作台偏好已保存到当前浏览器');
  }
}
