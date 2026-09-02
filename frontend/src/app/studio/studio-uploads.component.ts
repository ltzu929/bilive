import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  OnInit,
} from '@angular/core';
import { NzMessageService } from 'ng-zorro-antd/message';
import { StudioApiService, UploadDashboard } from './studio-api.service';

@Component({
  selector: 'app-studio-uploads',
  templateUrl: './studio-uploads.component.html',
  styleUrls: ['./studio-uploads.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StudioUploadsComponent implements OnInit {
  loading = true;
  error = '';
  dashboard: UploadDashboard = { queue_counts: {}, items: [] };
  actionBusy = false;

  constructor(
    private api: StudioApiService,
    private message: NzMessageService,
    private changeDetector: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.loading = true;
    this.api.getUploadDashboard().subscribe({
      next: (dashboard) => {
        this.dashboard = dashboard || { queue_counts: {}, items: [] };
        this.loading = false;
        this.error = '';
        this.changeDetector.markForCheck();
      },
      error: (error) => {
        this.loading = false;
        this.error = this.describeError(error);
        this.changeDetector.markForCheck();
      },
    });
  }

  wakeWorker(): void {
    this.actionBusy = true;
    this.api.wakeWorker().subscribe({
      next: () => {
        this.actionBusy = false;
        this.message.success('已请求唤醒上传 worker');
        this.refresh();
      },
      error: (error) => {
        this.actionBusy = false;
        this.message.error(this.describeError(error));
        this.changeDetector.markForCheck();
      },
    });
  }

  stopWorker(): void {
    this.actionBusy = true;
    this.api.stopWorker().subscribe({
      next: () => {
        this.actionBusy = false;
        this.message.success('已请求停止 worker');
        this.refresh();
      },
      error: (error) => {
        this.actionBusy = false;
        this.message.error(this.describeError(error));
        this.changeDetector.markForCheck();
      },
    });
  }

  count(name: string): number {
    return Number(this.dashboard.queue_counts?.[name] || 0);
  }

  statusColor(status: string | undefined): string {
    if (status === 'failed') return 'error';
    if (status === 'published') return 'success';
    if (['uploading', 'publishing'].includes(status || '')) return 'processing';
    return 'default';
  }

  statusLabel(status: string | undefined): string {
    const labels: Record<string, string> = {
      queued: '等待上传',
      uploading: '上传中',
      uploaded: '等待投稿',
      publishing: '投稿中',
      published: '已发布',
      failed: '失败',
    };
    return labels[status || ''] || status || '未知';
  }

  private describeError(error: any): string {
    return String(error?.error?.detail || error?.message || '上传接口不可用');
  }
}
