import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  OnInit,
  OnDestroy,
} from '@angular/core';
import { Subject, timer } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { NzMessageService } from 'ng-zorro-antd/message';
import { StudioApiService, UploadDashboard } from './studio-api.service';

@Component({
  selector: 'app-studio-uploads',
  templateUrl: './studio-uploads.component.html',
  styleUrls: ['./studio-uploads.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StudioUploadsComponent implements OnInit, OnDestroy {
  page = 1;
  private requestId = 0;
  statusFilter = '';
  private destroyed = new Subject<void>();
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
    timer(5000, 5000).pipe(takeUntil(this.destroyed)).subscribe(() => {
      if (!document.hidden && !this.loading && ['queued','uploading','uploaded','publishing'].some(s => this.count(s))) this.refresh();
    });
  }

  ngOnDestroy(): void { this.destroyed.next(); this.destroyed.complete(); }

  changePage(page: number): void { this.page = page; this.refresh(); }

  retryUpload(id: number): void {
    this.actionBusy = true;
    this.api.retryUpload(id).pipe(takeUntil(this.destroyed)).subscribe({
      next: () => { this.actionBusy = false; this.message.info('已提交 Windows 重试任务'); this.refresh(); },
      error: error => { this.actionBusy = false; this.error = this.describeError(error); this.changeDetector.markForCheck(); }
    });
  }

  refresh(): void {
    const requestId = ++this.requestId;
    this.loading = true;
    this.api.getUploadDashboard(this.statusFilter, this.page).pipe(takeUntil(this.destroyed)).subscribe({
      next: (dashboard) => {
        if (requestId !== this.requestId) return;
        this.dashboard = dashboard || { queue_counts: {}, items: [] };
        this.loading = false;
        this.error = String(dashboard?.database || '').startsWith('unavailable') ? '上传数据库暂不可用，请恢复数据库连接后刷新；当前数量不是实际库存。' : '';
        this.changeDetector.markForCheck();
      },
      error: (error) => {
        if (requestId !== this.requestId) return;
        this.loading = false;
        this.error = this.describeError(error);
        this.changeDetector.markForCheck();
      },
    });
  }

  wakeWorker(): void {
    this.actionBusy = true;
    this.api.wakeWorker().pipe(takeUntil(this.destroyed)).subscribe({
      next: (result) => {
        this.actionBusy = false;
        if (['unavailable', 'failed', 'error'].includes(String(result.status || ''))) this.message.warning(String(result.message || '上传 worker 暂不可用'));
        else this.message.success('已请求唤醒上传 worker');
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
    if (status === 'staged') return 'warning';
    if (['uploading', 'publishing'].includes(status || '')) return 'processing';
    return 'default';
  }

  statusLabel(status: string | undefined): string {
    const labels: Record<string, string> = {
      staged: '等待最终确认',
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
