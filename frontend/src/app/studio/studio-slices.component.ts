import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  ElementRef,
  HostListener,
  OnDestroy,
  OnInit,
  ViewChild,
} from '@angular/core';
import { BreakpointObserver } from '@angular/cdk/layout';
import { NzMessageService } from 'ng-zorro-antd/message';
import { forkJoin, Observable, of, Subject, timer } from 'rxjs';
import {
  catchError,
  filter,
  switchMap,
  take,
  takeUntil,
  timeout,
} from 'rxjs/operators';

import {
  StudioApiService,
  StudioRoom,
  StudioSegment,
  StudioSourceDetail,
  StudioSourceRecording,
} from './studio-api.service';
import { StudioPreferencesService } from './studio-preferences.service';

type InspectorTab = 'content' | 'subtitles' | 'technical';
type RangeBoundary = 'start' | 'end';
type QueueOrder = 'newest' | 'oldest' | 'grouped';

@Component({
  selector: 'app-studio-slices',
  templateUrl: './studio-slices.component.html',
  styleUrls: ['./studio-slices.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StudioSlicesComponent implements OnInit, OnDestroy {
  @ViewChild('densityChart') densityChart?: ElementRef<SVGElement>;

  loading = true;
  detailLoading = false;
  actionBusy = false;
  error = '';
  roomFilter = '';
  statusFilter = 'all';
  queueOrder: QueueOrder = 'newest';
  queueOpen = true;
  inspectorTab: InspectorTab = 'content';
  rooms: StudioRoom[] = [];
  recordings: StudioSourceRecording[] = [];
  selectedTaskId = '';
  detail: StudioSourceDetail | null = null;
  selectedSegmentId = '';
  titleDraft = '';
  descriptionDraft = '';
  tagsDraft = '';
  qualityReasonDraft = '';
  startDraft = 0;
  endDraft = 0;
  rangeDirty = false;
  missedStartDraft = 0;
  missedEndDraft = 10;
  missedReason = 'mimo_missed';
  missedNote = '';
  subtitleFontName = 'Noto Sans SC';
  subtitleFontSize = 20;
  subtitleMarginV = 60;
  subtitleAlignment = 2;
  subtitleOutline = 2;
  subtitleTextColor = '#ffffff';
  subtitleOutlineColor = '#000000';
  progress: Record<string, any> = {};
  diagnostics: Record<string, any> = {};
  worker: Record<string, any> = {};
  dropPending = false;
  private pendingDropSegmentId = '';
  private dropTimer?: ReturnType<typeof setTimeout>;
  private requestId = 0;
  private detailRequestId = 0;
  private dragBoundary: RangeBoundary | null = null;
  private dragMaxEnd = 1;
  private readonly destroyed = new Subject<void>();

  constructor(
    private api: StudioApiService,
    private message: NzMessageService,
    private changeDetector: ChangeDetectorRef,
    private preferences: StudioPreferencesService,
    private breakpointObserver: BreakpointObserver
  ) {}

  ngOnInit(): void {
    this.breakpointObserver
      .observe('(max-width: 1320px) and (min-width: 901px)')
      .pipe(take(1), takeUntil(this.destroyed))
      .subscribe(({ matches }) => {
        this.queueOpen = !matches;
        this.changeDetector.markForCheck();
      });
    this.refresh();
    this.preferences.preferences$
      .pipe(
        switchMap((preferences) =>
          timer(0, preferences.refreshInterval * 1000).pipe(
            switchMap(() =>
              forkJoin({
                progress: this.api.getSliceProgress().pipe(catchError(() => of({}))),
                diagnostics: this.api
                  .getSliceDiagnostics()
                  .pipe(catchError(() => of({}))),
                worker: this.api.getWorkerStatus().pipe(catchError(() => of({}))),
              })
            )
          )
        ),
        takeUntil(this.destroyed)
      )
      .subscribe((state) => {
        this.progress = state.progress;
        this.diagnostics = state.diagnostics;
        this.worker = state.worker;
        this.changeDetector.markForCheck();
      });
  }

  ngOnDestroy(): void {
    if (this.dropTimer) clearTimeout(this.dropTimer);
    this.destroyed.next();
    this.destroyed.complete();
  }

  get compactQueue(): boolean {
    return this.preferences.value.compactQueue;
  }

  get workerState(): 'running' | 'idle' | 'unavailable' {
    const status = String(this.worker.status || this.worker.process_status || '').toLowerCase();
    if (['running', 'processing', 'starting'].includes(status)) return 'running';
    if (!status || ['unavailable', 'error', 'failed', 'offline', 'unknown'].includes(status)) {
      return 'unavailable';
    }
    return 'idle';
  }

  get workerLabel(): string {
    if (this.workerState === 'running') return 'Windows 重任务节点：处理中';
    if (this.workerState === 'unavailable') return 'Windows 重任务节点：不可用';
    return `Windows 重任务节点：空闲，待处理 ${this.worker.pending_tasks || 0}`;
  }

  get filteredRecordings(): StudioSourceRecording[] {
    const items = this.recordings.filter((item) => this.recordingMatchesStatus(item));
    if (this.queueOrder === 'grouped') return items;
    const direction = this.queueOrder === 'oldest' ? 1 : -1;
    return [...items].sort(
      (left, right) => direction * (this.recordedAt(right) - this.recordedAt(left))
    );
  }

  get groupedRecordings(): Array<{ room: string; items: StudioSourceRecording[] }> {
    if (this.queueOrder !== 'grouped') {
      return [{ room: '', items: this.filteredRecordings }];
    }
    const groups = new Map<string, StudioSourceRecording[]>();
    for (const item of this.filteredRecordings) {
      const room = item.room_name || item.room_id || '未分组';
      groups.set(room, [...(groups.get(room) || []), item]);
    }
    return Array.from(groups.entries())
      .sort(([left], [right]) => left.localeCompare(right, 'zh-CN'))
      .map(([room, items]) => ({
        room,
        items: [...items].sort(
          (left, right) => this.recordedAt(right) - this.recordedAt(left)
        ),
      }));
  }

  trackByGroup(_index: number, group: { room: string }): string {
    return group.room || 'all';
  }

  trackByRecording(_index: number, item: StudioSourceRecording): string {
    return item.task_id;
  }

  get selectedSegment(): StudioSegment | null {
    return (
      this.detail?.segments?.find(
        (segment) => segment.segment_id === this.selectedSegmentId
      ) || null
    );
  }

  get selectedMediaUrl(): string {
    return this.detail?.source_media_id
      ? this.api.getMediaUrl(this.detail.source_media_id)
      : '';
  }

  get diagnosticItems(): Array<{ status?: string; title?: string; message?: string }> {
    return Array.isArray(this.diagnostics.items) ? this.diagnostics.items : [];
  }

  get failureItems(): StudioSourceRecording[] {
    return this.recordings.filter(
      (item) => item.status === 'failed' || Boolean(item.failure)
    );
  }

  get reviewCount(): number {
    return this.recordings.reduce((total, item) => {
      const counts = item.summary_counts || {};
      return total + Number(counts.review || 0) + Number(counts.judge_failed || 0);
    }, 0);
  }

  get keepCount(): number {
    return this.recordings.reduce((total, item) => {
      const counts = item.summary_counts || {};
      return total + Number(counts.keep || 0) + Number(counts.manual_keep || 0);
    }, 0);
  }

  get densityMaxEnd(): number {
    const points = this.detail?.density_points || [];
    const segments = this.detail?.segments || [];
    return Math.max(
      10,
      ...points.map((point) => Number(point.end_seconds || 0)),
      ...segments.map((segment) => Number(segment.end_seconds || 0))
    );
  }

  get densityPath(): string {
    const points = this.detail?.density_points || [];
    if (!points.length) return '';
    const top = points.map((point) => {
      const x = this.densityX(Number(point.start_seconds || 0));
      const y = 38 - Number(point.normalized || 0) * 34;
      return { x, y };
    });
    const lastX = this.densityX(Number(points[points.length - 1].end_seconds || this.densityMaxEnd));
    const first = top[0];
    if (top.length === 1) {
      return `M 0 38 L ${first.x.toFixed(2)} ${first.y.toFixed(2)} L ${lastX.toFixed(2)} 38 Z`;
    }

    let curve = `L ${first.x.toFixed(2)} ${first.y.toFixed(2)}`;
    for (let index = 1; index < top.length - 1; index += 1) {
      const point = top[index];
      const next = top[index + 1];
      const midpointX = (point.x + next.x) / 2;
      const midpointY = (point.y + next.y) / 2;
      curve += ` Q ${point.x.toFixed(2)} ${point.y.toFixed(2)} ${midpointX.toFixed(2)} ${midpointY.toFixed(2)}`;
    }
    const last = top[top.length - 1];
    curve += ` Q ${last.x.toFixed(2)} ${last.y.toFixed(2)} ${last.x.toFixed(2)} ${last.y.toFixed(2)}`;
    return `M 0 38 ${curve} L ${lastX.toFixed(2)} 38 Z`;
  }

  get selectedRangeLabel(): string {
    if (!this.selectedSegment) return '-';
    return `${this.startDraft.toFixed(1)}s - ${this.endDraft.toFixed(1)}s`;
  }

  get selectedActionStatus(): string {
    return this.selectedSegment?.action_state?.status || '';
  }

  get selectedActionBusy(): boolean {
    return this.actionBusy || ['pending', 'processing', 'running'].includes(this.selectedActionStatus);
  }

  get subtitlePreviewShadow(): string {
    const width = Math.max(0, Number(this.subtitleOutline || 0));
    return width ? `0 0 ${width}px ${this.subtitleOutlineColor}` : 'none';
  }

  refresh(): void {
    const requestId = ++this.requestId;
    this.loading = true;
    this.error = '';
    forkJoin({
      rooms: this.api.getRooms().pipe(catchError(() => of([]))),
      recordings: this.api.getSourceRecordings(this.roomFilter || undefined).pipe(
        catchError((error) => {
          this.error = this.describeError(error);
          return of([]);
        })
      ),
    })
      .pipe(takeUntil(this.destroyed))
      .subscribe(({ rooms, recordings }) => {
        if (requestId !== this.requestId) return;
        this.rooms = rooms;
        this.recordings = recordings;
        this.loading = false;
        if (!this.recordings.some((item) => item.task_id === this.selectedTaskId)) {
          this.selectedTaskId = this.filteredRecordings[0]?.task_id || '';
          this.selectedSegmentId = '';
        }
        if (this.selectedTaskId) this.loadDetail(this.selectedTaskId);
        this.changeDetector.markForCheck();
      });
  }

  onRoomChanged(): void {
    this.selectedTaskId = '';
    this.selectedSegmentId = '';
    this.detail = null;
    this.refresh();
  }

  onStatusChanged(): void {
    if (!this.filteredRecordings.some((item) => item.task_id === this.selectedTaskId)) {
      this.selectedTaskId = this.filteredRecordings[0]?.task_id || '';
      this.selectedSegmentId = '';
      if (this.selectedTaskId) this.loadDetail(this.selectedTaskId);
    }
    this.changeDetector.markForCheck();
  }

  selectRecording(taskId: string): void {
    if (taskId === this.selectedTaskId && this.detail) return;
    this.selectedTaskId = taskId;
    this.selectedSegmentId = '';
    this.loadDetail(taskId);
  }

  selectSegment(segment: StudioSegment): void {
    this.selectedSegmentId = segment.segment_id;
    this.titleDraft = segment.title || '';
    this.descriptionDraft = segment.description || '';
    this.tagsDraft = (segment.tags || []).join(', ');
    this.qualityReasonDraft = segment.quality_reason || '';
    this.startDraft = Number(segment.start_seconds || 0);
    this.endDraft = Number(segment.end_seconds || 0);
    this.rangeDirty = false;
    const style = segment.subtitle_style || {};
    this.subtitleFontName = String(style.font_name || 'Noto Sans SC');
    this.subtitleFontSize = Number(style.font_size || 20);
    this.subtitleMarginV = Number(style.margin_v || 60);
    this.subtitleAlignment = Number(style.alignment || 2);
    this.subtitleOutline = Number(style.outline || 2);
    this.subtitleTextColor = this.cssColour(style.primary_colour, '#ffffff');
    this.subtitleOutlineColor = this.cssColour(style.outline_colour, '#000000');
    this.changeDetector.markForCheck();
  }

  selectSegmentAt(seconds: number): void {
    const segment = this.detail?.segments?.find(
      (candidate) => seconds >= Number(candidate.start_seconds || 0) && seconds <= Number(candidate.end_seconds || 0)
    );
    if (segment) this.selectSegment(segment);
  }

  setInspectorTab(tab: InspectorTab): void {
    this.inspectorTab = tab;
  }

  toggleQueue(): void {
    this.queueOpen = !this.queueOpen;
  }

  densityX(seconds: number): number {
    return Math.min(100, Math.max(0, (seconds / this.densityMaxEnd) * 100));
  }

  densityWidth(start: number, end: number): number {
    return Math.max(0.5, this.densityX(end) - this.densityX(start));
  }

  densitySegmentClass(segment: StudioSegment): string {
    if (['keep', 'manual_keep'].includes(segment.judge_status || '')) return 'segment-overlay-keep';
    if (segment.judge_status === 'judge_failed') return 'segment-overlay-failed';
    return 'segment-overlay-review';
  }

  updateRange(boundary: RangeBoundary, value: number): void {
    const number = Math.max(0, Number(value || 0));
    if (boundary === 'start') {
      this.startDraft = Math.min(number, Math.max(0, this.endDraft - 0.1));
    } else {
      this.endDraft = Math.max(number, this.startDraft + 0.1);
    }
    this.rangeDirty = true;
    this.changeDetector.markForCheck();
  }

  beginRangeDrag(event: PointerEvent, boundary: RangeBoundary): void {
    event.preventDefault();
    this.dragBoundary = boundary;
    this.dragMaxEnd = this.densityMaxEnd;
  }

  @HostListener('document:pointermove', ['$event'])
  onRangeDrag(event: PointerEvent): void {
    if (!this.dragBoundary || !this.densityChart) return;
    const bounds = this.densityChart.nativeElement.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - bounds.left) / Math.max(bounds.width, 1)));
    this.updateRange(this.dragBoundary, ratio * this.dragMaxEnd);
  }

  @HostListener('document:pointerup')
  endRangeDrag(): void {
    this.dragBoundary = null;
  }

  seekTo(seconds: number, video?: HTMLVideoElement): void {
    video = video || document.querySelector<HTMLVideoElement>('.source-video') || undefined;
    if (video) {
      video.currentTime = Math.max(0, seconds);
      video.pause();
    }
  }

  startSlice(): void {
    this.runRequest(this.api.startSlice(), '已提交待处理录播', () => this.refresh());
  }

  startSelectedSlice(): void {
    if (!this.selectedTaskId) return;
    this.runRequest(this.api.startSlice(this.selectedTaskId), '已提交当前录播', () => this.refresh());
  }

  stopWorker(): void {
    this.runRequest(this.api.stopWorker(), '已请求停止切片 worker');
  }

  wakeWorker(): void {
    this.runRequest(this.api.wakeWorker(), '已请求唤醒切片 worker');
  }

  saveRange(): void {
    const segment = this.selectedSegment;
    if (!segment || this.endDraft <= this.startDraft) {
      this.message.warning('出点必须大于入点');
      return;
    }
    this.runSegmentAction('range', {
      start_seconds: this.startDraft,
      end_seconds: this.endDraft,
    });
  }

  finalizeSegment(): void {
    const segment = this.selectedSegment;
    if (!segment) return;
    this.runSegmentAction('finalize', this.finalizePayload());
  }

  approvePublish(): void {
    if (this.selectedSegment) this.runSegmentAction('approve-publish');
  }

  markMissedBoundary(boundary: RangeBoundary): void {
    const seconds = this.currentVideoTime();
    if (boundary === 'start') {
      this.missedStartDraft = seconds;
      if (this.missedEndDraft <= seconds) this.missedEndDraft = seconds + 0.1;
    } else {
      this.missedEndDraft = Math.max(seconds, this.missedStartDraft + 0.1);
    }
    this.changeDetector.markForCheck();
  }

  addMissedSegment(): void {
    if (!this.selectedTaskId || this.actionBusy) return;
    if (this.missedEndDraft <= this.missedStartDraft) {
      this.message.warning('漏切出点必须大于入点');
      return;
    }
    this.actionBusy = true;
    this.api.createMissedSegment(this.selectedTaskId, {
      start_seconds: this.missedStartDraft,
      end_seconds: this.missedEndDraft,
      reason: this.missedReason,
      note: this.missedNote,
    }).pipe(takeUntil(this.destroyed)).subscribe({
      next: (result) => {
        const segment = result.segment as Record<string, unknown> | undefined;
        const segmentId = String(segment?.segment_id || '');
        const jobId = this.jobIdFromResult(result);
        if (jobId && segmentId) {
          this.message.info('已提交 Windows worker 生成人工候选');
          this.waitForJob(jobId, segmentId);
          return;
        }
        this.actionBusy = false;
        this.message.success('已记录漏切候选');
        this.loadDetail(this.selectedTaskId);
        this.changeDetector.markForCheck();
      },
      error: (error) => {
        this.actionBusy = false;
        this.message.error(this.describeError(error));
        this.changeDetector.markForCheck();
      },
    });
  }

  completeReview(confirmedNoContent = false): void {
    if (!this.selectedTaskId || this.actionBusy) return;
    this.actionBusy = true;
    this.api.completeSourceReview(this.selectedTaskId, confirmedNoContent)
      .pipe(takeUntil(this.destroyed))
      .subscribe({
        next: (result) => {
          const jobId = this.jobIdFromResult(result);
          if (jobId) {
            this.message.info('整场复核已完成，已提交 Windows 回收任务');
            this.waitForRecordingJob(jobId);
            return;
          }
          this.finishRecordingAction('整场复核已完成');
        },
        error: (error) => {
          this.actionBusy = false;
          this.message.error(this.describeError(error));
          this.changeDetector.markForCheck();
        },
      });
  }

  private finalizePayload(): Record<string, unknown> {
    return {
      title: this.titleDraft,
      description: this.descriptionDraft,
      tags: this.tagsDraft.split(',').map((tag) => tag.trim()).filter(Boolean),
      quality_reason: this.qualityReasonDraft,
      start_seconds: this.startDraft,
      end_seconds: this.endDraft,
      subtitle_style: {
        font_name: this.subtitleFontName,
        font_size: this.subtitleFontSize,
        margin_v: this.subtitleMarginV,
        alignment: this.subtitleAlignment,
        outline: this.subtitleOutline,
        primary_colour: this.assColour(this.subtitleTextColor),
        outline_colour: this.assColour(this.subtitleOutlineColor),
      },
    };
  }

  scheduleDrop(): void {
    const segment = this.selectedSegment;
    if (!segment || this.selectedActionBusy) return;
    if (this.dropTimer) clearTimeout(this.dropTimer);
    this.pendingDropSegmentId = segment.segment_id;
    this.dropPending = true;
    this.dropTimer = setTimeout(() => {
      this.dropPending = false;
      this.runSegmentAction('drop', { reason: this.qualityReasonDraft }, this.pendingDropSegmentId);
      this.pendingDropSegmentId = '';
    }, 5000);
  }

  undoDrop(): void {
    if (!this.dropPending) return;
    if (this.dropTimer) clearTimeout(this.dropTimer);
    this.dropPending = false;
    this.pendingDropSegmentId = '';
    this.message.info('已撤销丢弃操作');
    this.changeDetector.markForCheck();
  }

  retrySegment(): void {
    if (this.selectedSegment) this.runSegmentAction('retry-judge');
  }

  renderSegment(): void {
    if (this.selectedSegment) this.runSegmentAction('render');
  }

  saveSubtitleStyle(): void {
    if (!this.selectedSegment) return;
    this.runSegmentAction('subtitle-style', {
      font_name: this.subtitleFontName,
      font_size: this.subtitleFontSize,
      margin_v: this.subtitleMarginV,
      alignment: this.subtitleAlignment,
      outline: this.subtitleOutline,
      primary_colour: this.assColour(this.subtitleTextColor),
      outline_colour: this.assColour(this.subtitleOutlineColor),
    });
  }

  reburnSubtitles(): void {
    if (this.selectedSegment) this.runSegmentAction('reburn');
  }

  statusLabel(status: string | undefined): string {
    const labels: Record<string, string> = {
      all: '全部',
      ready: '待处理',
      pending: '已排队',
      processing: '处理中',
      running: '处理中',
      done: '已完成',
      failed: '失败',
      skipped: '已跳过',
      review: '待复核',
      keep: '已保留',
      manual_keep: '已保留',
      judge_failed: '判断失败',
      queue_failed: '队列失败',
      awaiting_publish: '等待最终确认',
      staged: '等待最终确认',
      drop: '已丢弃',
      unprocessed: '待处理',
      candidate_review: '候选待复核',
      source_review: '整场待复核',
      review_complete: '复核完成',
      trash_pending: '等待回收源录播',
      trash: '回收源录播',
    };
    return labels[status || ''] || status || '未知';
  }

  statusColor(status: string | undefined): string {
    if (['failed', 'judge_failed', 'queue_failed'].includes(status || '')) return 'error';
    if (['done', 'keep', 'manual_keep', 'review_complete'].includes(status || '')) return 'success';
    if (['pending', 'processing', 'running'].includes(status || '')) return 'processing';
    if (status === 'review' || status === 'ready') return 'warning';
    return 'default';
  }

  reviewStateLabel(state: string | undefined): string {
    return this.statusLabel(state);
  }

  reviewStateColor(state: string | undefined): string {
    if (['candidate_review', 'source_review', 'unprocessed'].includes(state || '')) return 'warning';
    if (['processing', 'trash_pending'].includes(state || '')) return 'processing';
    if (state === 'review_complete') return 'success';
    return 'default';
  }

  canCompleteReview(): boolean {
    return Boolean(
      this.detail &&
      !this.actionBusy &&
      this.detail.trash_status !== 'done' &&
      this.detail.review_state !== 'trash_pending' &&
      this.detail.review_state !== 'review_complete'
    );
  }

  canConfirmNoContent(): boolean {
    return Boolean(
      this.detail &&
      !this.detail.segments?.length &&
      this.detail.review_state === 'source_review' &&
      this.canCompleteReview()
    );
  }

  private assColour(value: string): string {
    const match = String(value || '').trim().match(/^#([0-9a-f]{6})$/i);
    if (!match) return String(value || '').trim();
    const hex = match[1].toUpperCase();
    return `&H00${hex.slice(4, 6)}${hex.slice(2, 4)}${hex.slice(0, 2)}`;
  }

  private cssColour(value: unknown, fallback: string): string {
    const text = String(value || '').trim();
    const ass = text.match(/^&H(?:[0-9a-f]{2})?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
    if (ass) return `#${ass[3]}${ass[2]}${ass[1]}`.toLowerCase();
    return /^#[0-9a-f]{6}$/i.test(text) ? text : fallback;
  }

  recordingSummary(item: StudioSourceRecording): string {
    const counts = item.summary_counts || {};
    const review = Number(counts.review || 0);
    const keep = Number(counts.keep || 0) + Number(counts.manual_keep || 0);
    return `${item.segment_count || 0} 候选 · ${review} 待复核 · ${keep} 已保留`;
  }

  sourceDateLabel(item: StudioSourceRecording): string {
    return item.recorded_at || item.source_name || item.source_rel_path || '-';
  }

  isActionEnabled(action: string): boolean {
    if (!this.selectedSegment || this.selectedActionBusy) return false;
    if (action === 'drop') return true;
    return true;
  }

  nextSegment(offset: number): void {
    const segments = this.detail?.segments || [];
    if (!segments.length) return;
    const index = Math.max(0, segments.findIndex((segment) => segment.segment_id === this.selectedSegmentId));
    const next = segments[(index + offset + segments.length) % segments.length];
    if (next) this.selectSegment(next);
  }

  @HostListener('document:keydown', ['$event'])
  onShortcut(event: KeyboardEvent): void {
    const target = event.target as HTMLElement | null;
    if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
    if (event.key.toLowerCase() === 'j') {
      event.preventDefault();
      this.nextSegment(1);
    } else if (event.key.toLowerCase() === 'k') {
      event.preventDefault();
      this.nextSegment(-1);
    } else if (event.key.toLowerCase() === 'i') {
      event.preventDefault();
      this.updateRange('start', this.currentVideoTime());
    } else if (event.key.toLowerCase() === 'o') {
      event.preventDefault();
      this.updateRange('end', this.currentVideoTime());
    } else if (event.ctrlKey && event.key === 'Enter') {
      event.preventDefault();
      this.finalizeSegment();
    }
  }

  private currentVideoTime(): number {
    const video = document.querySelector<HTMLVideoElement>('.source-video');
    return Number(video?.currentTime || 0);
  }

  private recordingMatchesStatus(item: StudioSourceRecording): boolean {
    if (this.statusFilter === 'all') return true;
    const status = item.status || 'ready';
    if (this.statusFilter === 'has_keep') {
      const counts = item.summary_counts || {};
      return Number(counts.keep || 0) + Number(counts.manual_keep || 0) > 0;
    }
    if (this.statusFilter === 'todo') return ['ready', 'review'].includes(status);
    if (this.statusFilter === 'processing') return ['processing', 'running', 'pending'].includes(status);
    return status === this.statusFilter;
  }

  private recordedAt(item: StudioSourceRecording): number {
    const parsed = Date.parse(item.recorded_at || '');
    if (Number.isFinite(parsed)) return parsed;
    const filename = item.source_name || item.source_rel_path || '';
    const match = filename.match(/(\d{4})(\d{2})(\d{2})[-_](\d{2})[-_](\d{2})[-_](\d{2})/);
    if (!match) return 0;
    const [, year, month, day, hour, minute, second] = match;
    return new Date(
      Number(year),
      Number(month) - 1,
      Number(day),
      Number(hour),
      Number(minute),
      Number(second)
    ).getTime();
  }

  private loadDetail(taskId: string): void {
    const requestId = ++this.detailRequestId;
    this.detailLoading = true;
    this.api.getSourceRecording(taskId).pipe(takeUntil(this.destroyed)).subscribe({
      next: (detail) => {
        if (requestId !== this.detailRequestId || taskId !== this.selectedTaskId) return;
        this.detail = detail;
        this.detailLoading = false;
        const selected = detail.segments?.find((segment) => segment.segment_id === this.selectedSegmentId);
        const first = selected || detail.segments?.[0];
        if (first) this.selectSegment(first);
        else this.selectedSegmentId = '';
        this.changeDetector.markForCheck();
      },
      error: (error) => {
        if (requestId !== this.detailRequestId) return;
        this.detailLoading = false;
        this.error = this.describeError(error);
        this.changeDetector.markForCheck();
      },
    });
  }

  private runSegmentAction(
    action: string,
    payload?: Record<string, unknown>,
    segmentId = this.selectedSegment?.segment_id
  ): void {
    if (!segmentId || this.actionBusy) return;
    this.actionBusy = true;
    this.api.segmentAction(segmentId, action, payload).pipe(takeUntil(this.destroyed)).subscribe({
      next: (result) => {
        const jobId = this.jobIdFromResult(result);
        if (jobId) {
          this.message.info('已提交 Windows worker 处理');
          this.waitForJob(jobId, segmentId);
          return;
        }
        this.finishAction(segmentId, action, '操作已保存');
      },
      error: (error) => {
        this.actionBusy = false;
        this.message.error(this.describeError(error));
        this.changeDetector.markForCheck();
      },
    });
  }

  private waitForJob(jobId: string, segmentId: string): void {
    timer(0, 1500)
      .pipe(
        switchMap(() => this.api.getJob(jobId)),
        filter((job) => ['done', 'failed', 'error'].includes(String(job.status || job.state || ''))),
        take(1),
        timeout(90000),
        takeUntil(this.destroyed),
        catchError((error) => {
          this.actionBusy = false;
          this.message.error(this.describeError(error));
          this.changeDetector.markForCheck();
          return of(null);
        })
      )
      .subscribe((job) => {
        if (!job) return;
        const status = String(job.status || job.state || '');
        this.finishAction(segmentId, 'job', status === 'done' ? '处理完成' : '处理失败');
      });
  }

  private finishAction(segmentId: string, action: string, message: string): void {
    this.actionBusy = false;
    if (message === '处理失败') this.message.error(message);
    else this.message.success(message);
    if (segmentId === this.selectedSegmentId && this.selectedTaskId) this.loadDetail(this.selectedTaskId);
    this.rangeDirty = action === 'range' ? false : this.rangeDirty;
    this.changeDetector.markForCheck();
  }

  private waitForRecordingJob(jobId: string): void {
    timer(0, 1500)
      .pipe(
        switchMap(() => this.api.getJob(jobId)),
        filter((job) => ['done', 'failed', 'error'].includes(String(job.status || job.state || ''))),
        take(1),
        timeout(90000),
        takeUntil(this.destroyed),
        catchError((error) => {
          this.actionBusy = false;
          this.message.error(this.describeError(error));
          this.changeDetector.markForCheck();
          return of(null);
        })
      )
      .subscribe((job) => {
        if (!job) return;
        const status = String(job.status || job.state || '');
        this.finishRecordingAction(status === 'done' ? '整场复核完成，源录播已回收' : '源录播回收失败');
      });
  }

  private finishRecordingAction(message: string): void {
    this.actionBusy = false;
    if (message.includes('失败')) this.message.error(message);
    else this.message.success(message);
    if (this.selectedTaskId) {
      this.loadDetail(this.selectedTaskId);
      this.refresh();
    }
    this.changeDetector.markForCheck();
  }

  private jobIdFromResult(result: Record<string, unknown>): string {
    const direct = String(result.job_id || '');
    if (direct) return direct;
    const statusUrl = String(result.status_url || '');
    const match = statusUrl.match(/jobs\/([^/?#]+)/);
    return match?.[1] || '';
  }

  private runRequest<T>(request: Observable<T>, successMessage: string, after?: () => void): void {
    this.actionBusy = true;
    request.pipe(takeUntil(this.destroyed)).subscribe({
      next: () => {
        this.actionBusy = false;
        this.message.success(successMessage);
        after?.();
        this.changeDetector.markForCheck();
      },
      error: (error) => {
        this.actionBusy = false;
        this.message.error(this.describeError(error));
        this.changeDetector.markForCheck();
      },
    });
  }

  private describeError(error: any): string {
    return String(error?.error?.detail || error?.message || '工作台接口不可用');
  }
}
