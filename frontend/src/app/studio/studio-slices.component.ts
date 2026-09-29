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
  tap,
  timeout,
} from 'rxjs/operators';

import {
  StudioApiService,
  StudioActionJob,
  StudioJobProgress,
  StudioRoom,
  StudioSegment,
  StudioSubtitleSegment,
  StudioSourceDetail,
  StudioSourceRecording,
} from './studio-api.service';
import { StudioPreferencesService } from './studio-preferences.service';

import { subtitlePosition } from './subtitle-position';
import {
  SLICE_STAGES,
  SliceStageId,
  StageCounts,
  SamplePrimaryAction,
  computeStageCounts,
  filterSegmentsByStage,
  isSliceStageId,
  recordingInBurst,
  sampleOutstandingCount,
  samplePrimaryAction,
  segmentActionBusy,
} from './slice-stage';

type InspectorTab = 'content' | 'subtitles' | 'technical';
type RangeBoundary = 'start' | 'end';
const draftFields = ['titleDraft', 'descriptionDraft', 'tagsDraft', 'qualityReasonDraft', 'startDraft', 'endDraft', 'subtitleFontName', 'subtitleFontSize', 'subtitleMarginV', 'subtitleAlignment', 'subtitleOutline', 'subtitleTextColor', 'subtitleOutlineColor', 'subtitleDrafts'] as const;

type QueueOrder = 'newest' | 'oldest' | 'grouped';

const SEGMENT_ACTION_TIMEOUT_MS = 45_000;

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
  activeStage: SliceStageId = 'recordings';
  readonly stages = SLICE_STAGES;
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
  startDraftText = '0:00:00';
  endDraftText = '0:00:00';
  rangeDirty = false;
  missedStartDraft = 0;
  missedEndDraft = 10;
  missedStartDraftText = '0:00:00';
  missedEndDraftText = '0:00:10';
  missedReason = 'mimo_missed';
  missedNote = '';
  chartSelecting = false;
  missedSelectionActive = false;
  subtitleFontName = 'Noto Sans SC';
  subtitleFontSize = 20;
  subtitleMarginV = 60;
  subtitleAlignment = 2;
  subtitleOutline = 2;
  subtitleTextColor = '#ffffff';
  subtitleOutlineColor = '#000000';
  subtitleDrafts: StudioSubtitleSegment[] = [];
  activeSubtitleIndex = -1;
  subtitleTimeEditOpen = false;
  subtitleActionsIndex = -1;
  progress: Record<string, any> = {};
  diagnostics: Record<string, any> = {};
  worker: Record<string, any> = {};
  dropPending = false;
  mediaMode: 'source' | 'final' = 'source';
  draftConflict = false;
  observationError = '';
  subtitleSaveState: 'idle' | 'saving' | 'saved' | 'failed' = 'idle';
  subtitleSaveMessage = '';
  subtitleRefreshPending = false;
  jobProgressById: Record<string, StudioJobProgress> = {};
  private draftKey = '';
  private draftRevision = 0;
  private baseline = '';
  private readonly storageKey = 'bilive.review.session';
  private drafts: Record<string, {revision: number; values: Record<string, any>}> = {};
  pendingDrops: Record<string, {taskId: string; reason: string; revision: number; due: number; uncertain?: boolean}> = {};
  private dropTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private observedJobs = new Set<string>();
  private activeJobId = '';
  private workerTriggerUnavailable = false;
  busySegments = new Set<string>();
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
    this.restoreSession();
    const query = new URL(window.location.href).searchParams;
    const stageParam = query.get('stage');
    if (isSliceStageId(stageParam)) this.activeStage = stageParam;
    this.selectedTaskId = query.get('source_task_id') || '';
    this.selectedSegmentId = query.get('segment_id') || '';
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
            filter(() => !document.hidden),
            switchMap(() =>
              this.api.getReviewStatus().pipe(catchError(() => {
                this.observationError = '状态读取失败，显示上次结果';
                return of({progress: this.progress, diagnostics: this.diagnostics, worker: this.worker});
              }))
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
    this.saveDraft();
    for (const timer of this.dropTimers.values()) clearTimeout(timer);
    this.destroyed.next();
    this.destroyed.complete();
  }

  get compactQueue(): boolean {
    return this.preferences.value.compactQueue;
  }

  get stageMeta() {
    return this.stages.find((stage) => stage.id === this.activeStage) || this.stages[0];
  }

  get stageCounts(): StageCounts {
    return computeStageCounts(this.recordings);
  }

  get stageRecordings(): StudioSourceRecording[] {
    if (this.activeStage === 'recordings') return this.filteredRecordings;
    if (this.activeStage === 'burst') {
      return this.filteredRecordings.filter((item) => recordingInBurst(item));
    }
    return this.filteredRecordings.filter((item) => {
      const counts = item.summary_counts || {};
      const num = (key: string) => Number(counts[key] || 0);
      if (this.activeStage === 'judge') return num('review') + num('judge_failed') > 0;
      if (this.activeStage === 'sample') {
        return sampleOutstandingCount(counts) > 0 || num('needs_repair') > 0;
      }
      if (this.activeStage === 'subtitle') return num('awaiting_publish') + num('subtitle_needs_burn') > 0;
      return true;
    });
  }

  get stageSegments(): StudioSegment[] {
    return filterSegmentsByStage(this.detail?.segments || [], this.activeStage);
  }

  get canApprovePublish(): boolean {
    return Boolean(
      this.selectedSegment?.final_media_id &&
      !this.hasDraft &&
      this.selectedSegment.upload_status === 'awaiting_publish'
    );
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
    const direction = this.queueOrder === 'oldest' ? 1 : -1;
    return [...items].sort(
      (left, right) => {
        const a = this.recordedAt(left), b = this.recordedAt(right);
        return (!a && b ? 1 : a && !b ? -1 : direction * (a - b)) || left.task_id.localeCompare(right.task_id);
      }
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
        items,
      }));
  }

  trackByGroup(_index: number, group: { room: string }): string {
    return group.room || 'all';
  }

  trackByRecording(_index: number, item: StudioSourceRecording): string {
    return item.task_id;
  }

  trackBySubtitle(index: number, _item: StudioSubtitleSegment): number {
    return index;
  }

  get selectedSegment(): StudioSegment | null {
    return (
      this.detail?.segments?.find(
        (segment) => segment.segment_id === this.selectedSegmentId
      ) || null
    );
  }

  get selectedMediaUrl(): string {
    const id = this.mediaMode === 'final' ? this.selectedSegment?.final_media_id : this.detail?.source_media_id;
    return id ? this.api.getMediaUrl(id) : '';
  }

  setMediaMode(mode: 'source' | 'final'): void {
    this.mediaMode = mode;
    this.positionVideo();
  }

  positionVideo(): void {
    this.seekTo(this.mediaMode === 'final' ? 0 : Number(this.selectedSegment?.start_seconds || 0));
  }

  get hasDraft(): boolean {
    return !!this.draftKey && JSON.stringify(this.draftValues()) !== this.baseline;
  }

  get activeSubtitle(): StudioSubtitleSegment | null {
    return this.subtitleDrafts[this.activeSubtitleIndex] || null;
  }

  get subtitleDraftDirty(): boolean {
    if (!this.draftKey) return false;
    const baseline = JSON.parse(this.baseline || '{}');
    return JSON.stringify(this.cloneSubtitleSegments(this.subtitleDrafts))
      !== JSON.stringify(this.cloneSubtitleSegments(baseline.subtitleDrafts));
  }

  get subtitleStatusLabel(): string {
    if (!this.subtitleDrafts.length) return '暂无字幕';
    if (this.subtitleDraftDirty) return '未保存修改';
    if (this.subtitleSaveState === 'saving') return '正在保存';
    if (this.subtitleSaveState === 'failed') return '保存失败';
    return '已保存，可重新烧录';
  }

  get subtitleProgressLabel(): string {
    if (!this.subtitleDrafts.length) return '暂无字幕行';
    const index = this.activeSubtitleIndex >= 0 ? this.activeSubtitleIndex + 1 : 1;
    return `当前第 ${index} / ${this.subtitleDrafts.length} 行`;
  }

  private draftValues(): Record<string, any> {
    const values: Record<string, any> = {};
    for (const field of draftFields) values[field] = this[field];
    return values;
  }

  private cloneSubtitleSegments(value?: StudioSubtitleSegment[]): StudioSubtitleSegment[] {
    if (!Array.isArray(value)) return [];
    return value.map((subtitle) => ({
      start: Number(subtitle.start || 0),
      end: Number(subtitle.end || 0),
      text: String(subtitle.text || ''),
    }));
  }

  saveDraft(): void {
    if (!this.draftKey) return;
    if (this.hasDraft) this.drafts[this.draftKey] = {revision: this.draftRevision, values: this.draftValues()};
    else delete this.drafts[this.draftKey];
    this.persistSession();
  }

  private persistSession(): void {
    try { sessionStorage.setItem(this.storageKey, JSON.stringify({drafts: this.drafts, drops: this.pendingDrops})); }
    catch { this.error = '浏览器无法保存会话草稿，请勿刷新或关闭页面'; }
  }

  private restoreSession(): void {
    try {
      const saved = JSON.parse(sessionStorage.getItem(this.storageKey) || '{}');
      this.drafts = saved.drafts || {};
      this.pendingDrops = saved.drops || {};
      for (const [id, drop] of Object.entries(this.pendingDrops)) {
        if (!drop.uncertain && drop.due > Date.now()) this.armDrop(id);
      }
      this.dropPending = Object.keys(this.pendingDrops).length > 0;
    } catch { this.error = '会话草稿无法读取，请核对后重新编辑'; }
  }

  discardDraft(): void {
    delete this.drafts[this.draftKey];
    this.draftKey = '';
    if (this.selectedSegment) this.selectSegment(this.selectedSegment);
    this.persistSession();
  }

  @HostListener('window:beforeunload', ['$event'])
  beforeUnload(event: BeforeUnloadEvent): void {
    this.saveDraft();
    if (Object.keys(this.drafts).length || Object.keys(this.pendingDrops).length) {
      event.preventDefault(); event.returnValue = '';
    }
  }

  canLeave(): boolean {
    this.saveDraft();
    return !(Object.keys(this.drafts).length || Object.keys(this.pendingDrops).length)
      || window.confirm('仍有未提交草稿或丢弃操作，确定离开？同一标签页返回可继续审核。');
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

  get awaitingPublishCount(): number {
    return this.recordings.reduce((total, item) => total + Number(item.summary_counts?.['awaiting_publish'] || 0), 0);
  }

  get repairCount(): number {
    return this.recordings.reduce((total, item) => total + Number(item.summary_counts?.['needs_repair'] || 0), 0);
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
    return `${this.formatTimecode(this.startDraft)} - ${this.formatTimecode(this.endDraft)}`;
  }

  get progressHint(): string {
    const phase = String(this.progress?.phase || '');
    const message = String(this.progress?.message || '');
    const status = String(this.progress?.status || '');
    if (status === 'running' && (phase === 'mimo_wait' || phase === 'mimo_result' || message.includes('MiMo'))) {
      return '候选在本场处理结束后写入工作台；期间本板可能仍显示 0 候选。';
    }
    if (status === 'queued' || phase === 'queued') {
      return '任务已写入队列，等待 Windows Worker 领取；Worker 不可用时会一直保留。';
    }
    return '';
  }

  get selectedSegmentDuration(): number {
    return Math.max(0, this.endDraft - this.startDraft);
  }

  get subtitleValidationMessage(): string {
    if (!this.subtitleDrafts.length) return '当前没有字幕行';
    const duration = this.selectedSegmentDuration;
    for (let index = 0; index < this.subtitleDrafts.length; index += 1) {
      const subtitle = this.subtitleDrafts[index];
      const start = Number(subtitle.start);
      const end = Number(subtitle.end);
      if (!Number.isFinite(start) || !Number.isFinite(end)) {
        return `第 ${index + 1} 行时间必须是有效数字`;
      }
      if (start < 0) return `第 ${index + 1} 行开始时间不能小于 0`;
      if (end <= start) return `第 ${index + 1} 行结束时间必须晚于开始时间`;
      if (start > duration + 0.01) {
        return `第 ${index + 1} 行开始时间超出片段长度 ${(
          start - duration
        ).toFixed(2)} 秒`;
      }
      if (end > duration + 0.01) {
        return `第 ${index + 1} 行结束时间超出片段长度 ${(
          end - duration
        ).toFixed(2)} 秒`;
      }
      if (!String(subtitle.text || '').trim()) {
        return `第 ${index + 1} 行字幕文本不能为空`;
      }
    }
    return '';
  }

  get subtitleDraftsValid(): boolean {
    return this.subtitleDrafts.length > 0 && !this.subtitleValidationMessage;
  }

  get subtitleJobProgress(): StudioJobProgress | null {
    return this.activeJobId ? this.jobProgressById[this.activeJobId] || null : null;
  }

  get subtitleJobProgressPercent(): number {
    const value = Number(this.subtitleJobProgress?.percent);
    return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
  }

  get subtitleJobProgressMessage(): string {
    const progress = this.subtitleJobProgress;
    if (!progress) return '';
    if (progress.message) return progress.message;
    return this.jobPhaseLabel(progress.phase);
  }

  get subtitleJobIdLabel(): string {
    return this.activeJobId ? this.activeJobId.slice(0, 8) : '';
  }

  get subtitleActionHint(): string {
    const validation = this.subtitleValidationMessage;
    if (validation && this.subtitleDrafts.length) return validation;
    if (this.subtitleSaveState === 'saving') return '正在保存字幕修改，请等待保存和刷新完成';
    if (this.subtitleSaveState === 'failed' && this.subtitleSaveMessage) {
      return this.subtitleSaveMessage;
    }
    if (this.subtitleRefreshPending) return '字幕已保存，正在刷新片段；刷新完成后才能重新烧录';
    if (this.detailLoading) return '正在读取服务端字幕版本，请等待刷新完成';
    if (this.draftConflict) return '服务端版本已改变，请先放弃旧草稿并重新读取';
    if (this.busySegments.has(this.selectedSegmentId)) {
      if (this.workerState === 'unavailable' && this.subtitleJobProgress?.phase === 'queued') {
        return 'Windows Worker 当前不可用，任务已保留在队列；恢复 Worker 后会继续，请刷新查看状态';
      }
      return this.subtitleJobProgressMessage || '后台任务处理中，请等待任务完成';
    }
    if (this.subtitleDraftDirty) return '请先保存字幕修改，保存成功后才能重新烧录';
    if (!this.subtitleDrafts.length) return '当前没有字幕行；如需字幕可以新增并保存一行';
    return '字幕已保存。重新烧录会生成新的待确认成片，不会自动发布';
  }

  get selectedActionStatus(): string {
    return this.selectedSegment?.action_state?.status || '';
  }

  get selectedActionBusy(): boolean {
    return this.selectedSegment?.publish_approval === 'approved' || ['queued', 'uploading', 'uploaded', 'publishing', 'published', 'failed'].includes(this.selectedSegment?.upload_status || '') || this.detailLoading || this.subtitleRefreshPending || this.draftConflict || this.busySegments.has(this.selectedSegmentId) || ['pending', 'processing', 'running', 'blocked'].includes(this.selectedActionStatus);
  }

  segmentBusy(segment: StudioSegment | null | undefined): boolean {
    if (!segment) return false;
    return this.busySegments.has(segment.segment_id) || segmentActionBusy(segment);
  }

  get busySegmentCount(): number {
    const ids = new Set<string>(this.busySegments);
    for (const segment of this.detail?.segments || []) {
      if (segmentActionBusy(segment) && segment.segment_id) ids.add(segment.segment_id);
    }
    return ids.size;
  }

  samplePrimary(segment: StudioSegment | null | undefined): SamplePrimaryAction {
    return samplePrimaryAction(segment);
  }

  runSamplePrimary(segment: StudioSegment): void {
    const primary = samplePrimaryAction(segment);
    if (primary.kind === 'goto_subtitle') {
      this.selectSegment(segment);
      this.setStage('subtitle');
      return;
    }
    if (!primary.action) return;
    this.selectSegment(segment);
    this.runSegmentAction(primary.action, undefined, segment.segment_id);
  }

  get subtitlePosition() { return subtitlePosition(this.subtitleAlignment); }

  get subtitlePreviewShadow(): string {
    const width = Math.max(0, Number(this.subtitleOutline || 0));
    return width ? `0 0 ${width}px ${this.subtitleOutlineColor}` : 'none';
  }

  refresh(): void {
    this.saveDraft();
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
          const previousTaskId = this.selectedTaskId;
          const fallback = this.stageRecordings[0]?.task_id || this.filteredRecordings[0]?.task_id || '';
          this.selectedTaskId = fallback;
          this.selectedSegmentId = '';
          if (previousTaskId && !fallback) {
            this.error = '当前阶段暂无可用场次，请切换阶段或刷新清单';
          } else {
            this.error = '';
          }
          this.syncSelectionUrl();
        }
        if (this.selectedTaskId) this.loadDetail(this.selectedTaskId);
        else this.clearDetail();
        this.changeDetector.markForCheck();
      });
  }

  private syncSelectionUrl(): void {
    const url = new URL(window.location.href);
    url.searchParams.set('stage', this.activeStage);
    if (this.selectedTaskId) url.searchParams.set('source_task_id', this.selectedTaskId);
    else url.searchParams.delete('source_task_id');
    if (this.selectedSegmentId) url.searchParams.set('segment_id', this.selectedSegmentId);
    else url.searchParams.delete('segment_id');
    window.history.replaceState(window.history.state, '', url);
  }

  onRoomChanged(): void {
    this.selectedTaskId = '';
    this.selectedSegmentId = '';
    this.detail = null;
    this.refresh();
  }

  onStatusChanged(): void {
    this.saveDraft();
    if (!this.filteredRecordings.some((item) => item.task_id === this.selectedTaskId)) {
      this.selectedTaskId = this.filteredRecordings[0]?.task_id || '';
      this.selectedSegmentId = '';
      if (this.selectedTaskId) this.loadDetail(this.selectedTaskId);
      else this.clearDetail();
    }
    this.changeDetector.markForCheck();
  }

  setStage(stage: SliceStageId): void {
    if (this.activeStage === stage) return;
    this.saveDraft();
    this.activeStage = stage;
    const url = new URL(window.location.href);
    url.searchParams.set('stage', stage);
    window.history.replaceState(window.history.state, '', url);
    const preferred = this.stageRecordings[0]?.task_id;
    if (preferred && preferred !== this.selectedTaskId) {
      this.selectedTaskId = preferred;
      this.selectedSegmentId = '';
      this.loadDetail(preferred);
    } else if (this.selectedTaskId) {
      this.loadDetail(this.selectedTaskId);
    }
    this.changeDetector.markForCheck();
  }

  selectRecording(taskId: string): void {
    this.saveDraft();
    if (taskId === this.selectedTaskId && this.detail) return;
    this.selectedTaskId = taskId;
    this.selectedSegmentId = '';
    this.loadDetail(taskId);
  }

  deferUpload(): void {
    this.message.info('已保留在字幕精修板，稍后可再确认上传');
    this.changeDetector.markForCheck();
  }

  segmentJobPercent(segment: StudioSegment): number {
    if (segment.subtitle_needs_burn) return 0;
    const fromAction = Number(segment.action_state?.progress?.percent);
    if (Number.isFinite(fromAction)) return Math.max(0, Math.min(100, fromAction));
    if (String(segment.action_state?.status || '') === 'done' && segment.preview_available !== false && !segment.subtitle_needs_burn) return 100;
    if (segment.failure || segment.upload_status === 'failed') return 0;
    return 0;
  }

  sampleThumbLabel(segment: StudioSegment): string {
    if (segment.failure || segment.upload_status === 'failed') return '渲染失败';
    const upload = String(segment.upload_status || '');
    if (upload === 'published') return '已发布';
    if (['queued', 'uploading', 'uploaded', 'publishing'].includes(upload)) {
      return `上传中 · ${this.statusLabel(upload)}`;
    }
    if (segment.subtitle_needs_burn) return '字幕已保存，待重新烧录';
    const actionStatus = String(segment.action_state?.status || '');
    if (['pending', 'processing', 'running', 'blocked'].includes(actionStatus)) {
      return '成片生成中…';
    }
    if (segment.preview_available === false && !actionStatus) {
      return segment.preview_reason || '待重新生成成片';
    }
    if (segment.final_media_id && segment.preview_available !== false) return '已有可预览成片';
    return this.segmentJobMessage(segment);
  }

  segmentJobMessage(segment: StudioSegment): string {
    const upload = String(segment.upload_status || '');
    if (upload === 'published') return '已发布，无需再生成成片';
    if (['queued', 'uploading', 'uploaded', 'publishing'].includes(upload)) {
      return `已进入上传流程：${this.statusLabel(upload)}`;
    }
    if (segment.subtitle_needs_burn) {
      return segment.preview_reason || '字幕已保存，待重新烧录';
    }
    const progress = segment.action_state?.progress;
    if (progress?.message) return progress.message;
    const status = String(segment.action_state?.status || '');
    if (['pending', 'processing', 'running', 'blocked'].includes(status)) {
      return this.jobPhaseLabel(progress?.phase) || '等待 Windows Worker';
    }
    if (segment.preview_available === false) {
      return segment.preview_reason || '待重新生成成片';
    }
    if (segment.failure || segment.upload_status === 'failed') {
      return segment.failure?.summary || '成片失败，可重试';
    }
    return '等待生成可预览成片';
  }

  formatTimecode(seconds: number | undefined | null): string {
    const total = Math.max(0, Math.floor(Number(seconds || 0)));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }

  parseTimecode(value: string | number): number {
    if (typeof value === 'number') return Math.max(0, Number.isFinite(value) ? value : 0);
    const raw = String(value || '').trim();
    if (!raw) return 0;
    if (!raw.includes(':')) return Math.max(0, Number(raw) || 0);
    const parts = raw.split(':').map((part) => Number(part.trim()));
    if (parts.some((part) => !Number.isFinite(part) || part < 0)) return 0;
    if (parts.length >= 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    return parts[0] || 0;
  }

  updateRangeFromTimecode(boundary: RangeBoundary, value: string): void {
    if (boundary === 'start') this.startDraftText = value;
    else this.endDraftText = value;
    this.updateRange(boundary, this.parseTimecode(value), false);
  }

  selectSegment(segment: StudioSegment): void {
    this.saveDraft();
    const segmentChanged = this.selectedSegmentId !== segment.segment_id;
    this.selectedSegmentId = segment.segment_id;
    if (segmentChanged) {
      this.activeJobId = '';
      this.workerTriggerUnavailable = false;
      this.subtitleSaveState = 'idle';
      this.subtitleSaveMessage = '';
      this.subtitleRefreshPending = false;
    }
    this.titleDraft = segment.title || '';
    this.descriptionDraft = segment.description || '';
    this.tagsDraft = (segment.tags || []).join(', ');
    this.qualityReasonDraft = segment.quality_reason || '';
    this.startDraft = Number(segment.start_seconds || 0);
    this.endDraft = Number(segment.end_seconds || 0);
    this.startDraftText = this.formatTimecode(this.startDraft);
    this.endDraftText = this.formatTimecode(this.endDraft);
    this.rangeDirty = false;
    const style = segment.subtitle_style || {};
    this.subtitleFontName = String(style.font_name || 'Noto Sans SC');
    this.subtitleFontSize = Number(style.font_size || 20);
    this.subtitleMarginV = Number(style.margin_v || 60);
    this.subtitleAlignment = Number(style.alignment || 2);
    this.subtitleOutline = Number(style.outline || 2);
    this.subtitleTextColor = this.cssColour(style.primary_colour, '#ffffff');
    this.subtitleOutlineColor = this.cssColour(style.outline_colour, '#000000');
    this.subtitleDrafts = this.cloneSubtitleSegments(segment.subtitle_segments);
    this.draftKey = `${this.selectedTaskId}:${segment.segment_id}`;
    this.draftRevision = Number(segment.revision || 0);
    this.baseline = JSON.stringify(this.draftValues());
    const saved = this.drafts[this.draftKey];
    this.draftConflict = !!saved && saved.revision !== this.draftRevision;
    if (saved) {
      for (const field of draftFields) if (field in saved.values) (this as any)[field] = saved.values[field];
      this.draftRevision = saved.revision;
    }
    if (!Array.isArray(this.subtitleDrafts)) this.subtitleDrafts = [];
    this.activeSubtitleIndex = this.subtitleDrafts.length ? 0 : -1;
    this.subtitleTimeEditOpen = false;
    this.subtitleActionsIndex = -1;
    this.mediaMode = segment.final_media_id && (segment.upload_status === 'awaiting_publish' || this.activeStage === 'subtitle')
      ? 'final'
      : 'source';
    const url = new URL(window.location.href);
    url.searchParams.set('stage', this.activeStage);
    url.searchParams.set('source_task_id', this.selectedTaskId);
    url.searchParams.set('segment_id', segment.segment_id);
    window.history.replaceState(window.history.state, '', url);
    this.positionVideo();
    if (segment.action_state?.job_id && ['pending', 'processing'].includes(segment.action_state.status || '')) {
      this.waitForJob(
        segment.action_state.job_id,
        segment.segment_id,
        segment.action_state.action || 'job',
      );
    }
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
    if (tab !== 'subtitles') {
      this.subtitleTimeEditOpen = false;
      this.subtitleActionsIndex = -1;
    }
    this.changeDetector.markForCheck();
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

  updateRange(boundary: RangeBoundary, value: number, syncText = true): void {
    const number = Math.max(0, Number(value || 0));
    if (boundary === 'start') {
      this.startDraft = Math.min(number, Math.max(0, this.endDraft - 0.1));
    } else {
      this.endDraft = Math.max(number, this.startDraft + 0.1);
    }
    if (syncText) {
      this.startDraftText = this.formatTimecode(this.startDraft);
      this.endDraftText = this.formatTimecode(this.endDraft);
    }
    this.rangeDirty = true;
    this.changeDetector.markForCheck();
  }

  beginRangeDrag(event: PointerEvent, boundary: RangeBoundary): void {
    event.preventDefault();
    this.dragBoundary = boundary;
    this.dragMaxEnd = this.densityMaxEnd;
  }

  beginChartSelect(event: PointerEvent): void {
    if (!this.densityChart) return;
    event.preventDefault();
    const seconds = this.chartSecondsFromEvent(event);
    this.chartSelecting = true;
    this.missedSelectionActive = true;
    this.missedStartDraft = seconds;
    this.missedEndDraft = seconds + 0.1;
    this.missedStartDraftText = this.formatTimecode(this.missedStartDraft);
    this.missedEndDraftText = this.formatTimecode(this.missedEndDraft);
    this.changeDetector.markForCheck();
  }

  private chartSecondsFromEvent(event: PointerEvent): number {
    const bounds = this.densityChart!.nativeElement.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - bounds.left) / Math.max(bounds.width, 1)));
    return ratio * this.densityMaxEnd;
  }

  get hasMissedSelection(): boolean {
    return this.missedSelectionActive && this.missedEndDraft - this.missedStartDraft >= 1;
  }

  clearMissedSelection(): void {
    this.chartSelecting = false;
    this.missedSelectionActive = false;
    this.missedStartDraft = 0;
    this.missedEndDraft = 10;
    this.missedStartDraftText = '0:00:00';
    this.missedEndDraftText = '0:00:10';
    this.missedNote = '';
    this.changeDetector.markForCheck();
  }

  @HostListener('document:pointermove', ['$event'])
  onRangeDrag(event: PointerEvent): void {
    if (!this.densityChart) return;
    if (this.chartSelecting) {
      const seconds = this.chartSecondsFromEvent(event);
      if (seconds < this.missedStartDraft) {
        this.missedEndDraft = this.missedStartDraft + 0.1;
        this.missedStartDraft = seconds;
      } else {
        this.missedEndDraft = Math.max(seconds, this.missedStartDraft + 0.1);
      }
      this.missedStartDraftText = this.formatTimecode(this.missedStartDraft);
      this.missedEndDraftText = this.formatTimecode(this.missedEndDraft);
      this.changeDetector.markForCheck();
      return;
    }
    if (!this.dragBoundary) return;
    const bounds = this.densityChart.nativeElement.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - bounds.left) / Math.max(bounds.width, 1)));
    this.updateRange(this.dragBoundary, ratio * this.dragMaxEnd);
  }

  @HostListener('document:pointerup')
  endRangeDrag(): void {
    this.dragBoundary = null;
    this.chartSelecting = false;
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
    if (this.subtitleDrafts.length && !this.subtitleDraftsValid) {
      this.message.warning('请填写非空字幕，并检查每行的时间范围');
      return;
    }
    this.runSegmentAction('finalize', this.finalizePayload());
  }

  approvePublish(): void {
    if (this.selectedSegment?.final_media_id && !this.hasDraft) this.runSegmentAction('approve-publish', {
      expected_revision: this.selectedSegment.revision,
      final_media_id: this.selectedSegment.final_media_id,
    });
  }

  markMissedBoundary(boundary: RangeBoundary): void {
    if (this.mediaMode !== 'source') return;
    const seconds = this.currentVideoTime();
    if (boundary === 'start') {
      this.missedStartDraft = seconds;
      if (this.missedEndDraft <= seconds) this.missedEndDraft = seconds + 0.1;
    } else {
      this.missedEndDraft = Math.max(seconds, this.missedStartDraft + 0.1);
    }
    this.missedStartDraftText = this.formatTimecode(this.missedStartDraft);
    this.missedEndDraftText = this.formatTimecode(this.missedEndDraft);
    this.changeDetector.markForCheck();
  }

  updateMissedFromTimecode(boundary: RangeBoundary, value: string): void {
    const seconds = this.parseTimecode(value);
    if (boundary === 'start') {
      this.missedStartDraftText = value;
      this.missedStartDraft = seconds;
      if (this.missedEndDraft <= seconds) this.missedEndDraft = seconds + 0.1;
    } else {
      this.missedEndDraftText = value;
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
        this.clearMissedSelection();
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
    const payload: Record<string, unknown> = {
      expected_revision: this.draftRevision,
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
    if (this.subtitleDrafts.length) {
      payload.subtitle_segments = this.cloneSubtitleSegments(this.subtitleDrafts);
    }
    return payload;
  }

  scheduleDrop(): void {
    const segment = this.selectedSegment;
    if (!segment || this.selectedActionBusy) return;
    const id = segment.segment_id;
    this.pendingDrops[id] = {taskId: this.selectedTaskId, reason: this.qualityReasonDraft,
      revision: Number(segment.revision || 0), due: Date.now() + 5000};
    this.dropPending = true;
    this.persistSession();
    this.armDrop(id);
  }

  private armDrop(id: string): void {
    if (this.dropTimers.has(id)) clearTimeout(this.dropTimers.get(id));
    this.dropTimers.set(id, setTimeout(() => this.submitDrop(id), Math.max(0, this.pendingDrops[id].due - Date.now())));
  }

  submitDrop(id: string): void {
    const drop = this.pendingDrops[id];
    if (!drop || drop.uncertain) return;
    drop.uncertain = true;
    this.persistSession();
    this.api.segmentAction(id, 'drop', {reason: drop.reason, expected_revision: drop.revision})
      .pipe(takeUntil(this.destroyed)).subscribe({
        next: () => { this.undoDrop(id); this.refresh(); },
        error: () => { this.error = `片段 ${id} 丢弃结果未确认，请刷新核对后撤销本地记录或重新操作`; this.changeDetector.markForCheck(); }
      });
  }

  undoDrop(id = this.selectedSegmentId): void {
    clearTimeout(this.dropTimers.get(id));
    this.dropTimers.delete(id);
    delete this.pendingDrops[id];
    this.dropPending = Object.keys(this.pendingDrops).length > 0;
    this.persistSession();
    this.changeDetector.markForCheck();
  }

  get pendingDropIds(): string[] { return Object.keys(this.pendingDrops); }

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

  addSubtitleLine(): void {
    if (!this.selectedSegment || this.selectedActionBusy) return;
    const duration = this.selectedSegmentDuration;
    const previous = this.subtitleDrafts[this.subtitleDrafts.length - 1];
    const start = Math.min(duration, Math.max(0, Number(previous?.end || 0)));
    const end = Math.min(duration, start + Math.min(3, Math.max(0.1, duration - start)));
    if (end <= start) {
      this.message.warning('当前片段没有可用的新增字幕时间');
      return;
    }
    this.subtitleDrafts = [
      ...this.subtitleDrafts,
      {start, end, text: ''},
    ];
    this.activeSubtitleIndex = this.subtitleDrafts.length - 1;
    this.subtitleActionsIndex = -1;
    this.changeDetector.markForCheck();
  }

  removeSubtitleLine(index: number): void {
    if (this.selectedActionBusy) return;
    if (this.subtitleDrafts.length <= 1) {
      this.message.warning('至少保留一行字幕');
      return;
    }
    this.subtitleDrafts = this.subtitleDrafts.filter((_item, itemIndex) => itemIndex !== index);
    this.activeSubtitleIndex = Math.min(this.activeSubtitleIndex, this.subtitleDrafts.length - 1);
    this.subtitleActionsIndex = -1;
    this.changeDetector.markForCheck();
  }

  seekSubtitleLine(subtitle: StudioSubtitleSegment): void {
    this.activeSubtitleIndex = this.subtitleDrafts.indexOf(subtitle);
    const offset = Number(subtitle.start || 0);
    this.seekTo(this.mediaMode === 'final' ? offset : this.startDraft + offset);
    this.changeDetector.markForCheck();
  }

  onVideoTimeUpdate(event: Event): void {
    if (this.inspectorTab !== 'subtitles' || !this.subtitleDrafts.length) return;
    const video = event.target as HTMLVideoElement;
    const offset = this.mediaMode === 'final' ? video.currentTime : video.currentTime - this.startDraft;
    const activeIndex = this.subtitleDrafts.findIndex((subtitle) => (
      offset >= Number(subtitle.start || 0) && offset <= Number(subtitle.end || 0)
    ));
    if (activeIndex >= 0 && activeIndex !== this.activeSubtitleIndex) {
      this.activeSubtitleIndex = activeIndex;
      this.subtitleActionsIndex = -1;
      this.changeDetector.markForCheck();
    }
  }

  toggleSubtitleTimeEdit(): void {
    this.subtitleTimeEditOpen = !this.subtitleTimeEditOpen;
    this.subtitleActionsIndex = -1;
  }

  toggleSubtitleActions(index: number): void {
    this.activeSubtitleIndex = index;
    this.subtitleActionsIndex = this.subtitleActionsIndex === index ? -1 : index;
  }

  updateActiveSubtitleTime(boundary: RangeBoundary, value: number): void {
    const index = this.activeSubtitleIndex;
    const current = this.activeSubtitle;
    if (!current || index < 0) return;
    const number = Math.max(0, Number(value || 0));
    const start = boundary === 'start'
      ? Math.min(number, Math.max(0, Number(current.end || 0) - 0.1))
      : Number(current.start || 0);
    const end = boundary === 'end'
      ? Math.min(this.selectedSegmentDuration, Math.max(number, start + 0.1))
      : Number(current.end || 0);
    this.subtitleDrafts = this.subtitleDrafts.map((subtitle, itemIndex) => (
      itemIndex === index ? {...subtitle, start, end} : subtitle
    ));
    this.changeDetector.markForCheck();
  }

  formatSubtitleTime(value: number): string {
    const centiseconds = Math.max(0, Math.round(Number(value || 0) * 100));
    const minutes = Math.floor(centiseconds / 6000);
    const seconds = Math.floor((centiseconds % 6000) / 100);
    const fraction = centiseconds % 100;
    return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(fraction).padStart(2, '0')}`;
  }

  saveSubtitleEdits(): void {
    if (!this.selectedSegment) return;
    if (!this.subtitleDraftsValid) {
      this.message.warning(this.subtitleValidationMessage || '请检查字幕内容和时间范围');
      this.changeDetector.markForCheck();
      return;
    }
    if (this.selectedActionBusy) {
      this.message.info(this.subtitleActionHint);
      return;
    }
    this.subtitleSaveState = 'saving';
    this.subtitleSaveMessage = '正在保存字幕修改';
    this.runSegmentAction('subtitles', {
      expected_revision: this.draftRevision,
      subtitle_segments: this.cloneSubtitleSegments(this.subtitleDrafts),
    });
  }

  reburnSubtitles(): void {
    if (!this.selectedSegment) return;
    if (this.subtitleDraftDirty) {
      this.message.warning('请先保存字幕修改，保存成功后才能重新烧录');
      return;
    }
    if (this.selectedActionBusy) {
      this.message.info(this.subtitleActionHint);
      return;
    }
    this.runSegmentAction('reburn');
  }

  statusLabel(status: string | undefined): string {
    const labels: Record<string, string> = {
      all: '全部',
      ready: '待处理',
      pending: '排队中·等 Windows Worker',
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
      not_queued: '未入上传队列',
      queued: '排队上传',
      uploading: '上传中',
      uploaded: '已上传',
      publishing: '投稿中',
      published: '已发布',
      mimo_wait: '等待 MiMo 返回',
      mimo_result: '解析 MiMo 结果',
    };
    return labels[status || ''] || status || '未知';
  }

  private jobPhaseLabel(phase: string | undefined): string {
    const labels: Record<string, string> = {
      queued: '等待 Windows Worker',
      raw_render: '生成原始片段',
      asr: '语音转写',
      analysis: '保存转写结果',
      subtitle_burn: '字幕烧录',
      metadata: '写入投稿元数据',
      queue: '写入人工确认队列',
      complete: '处理完成',
      failed: '处理失败',
    };
    return labels[phase || ''] || '后台处理';
  }

  statusColor(status: string | undefined): string {
    const value = status || '';
    if (['failed', 'judge_failed', 'queue_failed'].includes(value)) return 'error';
    if (['done', 'keep', 'manual_keep', 'review_complete', 'published', 'uploaded'].includes(value)) {
      return 'success';
    }
    if (['pending', 'processing', 'running', 'uploading', 'publishing', 'queued', 'mimo_wait'].includes(value)) {
      return 'processing';
    }
    if (['review', 'ready', 'awaiting_publish', 'staged'].includes(value)) return 'warning';
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
    const state = String(this.detail?.review_state || '');
    return Boolean(
      this.detail &&
      !this.detail.segments?.length &&
      (state === 'source_review' || state === 'unprocessed') &&
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

  recordingTitle(item: StudioSourceRecording): string {
    const streamer = item.room_name || item.room_id || '未知主播';
    const recorded = item.recorded_at || this.fallbackRecordedLabel(item);
    return recorded ? `${streamer} · ${recorded}` : streamer;
  }

  private fallbackRecordedLabel(item: StudioSourceRecording): string {
    const name = item.source_name || item.source_rel_path || '';
    const match = name.match(/(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})/);
    if (!match) return '';
    return `${match[1]}-${match[2]}-${match[3]} ${match[4]}:${match[5]}:${match[6]}`;
  }

  sourceDateLabel(item: StudioSourceRecording): string {
    return item.recorded_at || this.fallbackRecordedLabel(item) || item.source_name || item.source_rel_path || '-';
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

  nextSubtitle(offset: number): void {
    if (!this.subtitleDrafts.length) return;
    const index = this.activeSubtitleIndex < 0 ? 0 : this.activeSubtitleIndex;
    const next = (index + offset + this.subtitleDrafts.length) % this.subtitleDrafts.length;
    const subtitle = this.subtitleDrafts[next];
    if (subtitle) this.seekSubtitleLine(subtitle);
  }

  @HostListener('document:keydown', ['$event'])
  onShortcut(event: KeyboardEvent): void {
    const target = event.target as HTMLElement | null;
    if (target?.closest('input, textarea, select, button, [contenteditable], [role=combobox]')) return;
    if (event.code === 'Space') {
      if (target?.tagName === 'VIDEO') return;
      const video = document.querySelector<HTMLVideoElement>('.source-video');
      if (video) { event.preventDefault(); if (video.paused) void video.play(); else video.pause(); }
      return;
    }
    if (this.mediaMode === 'final' && ['i', 'o'].includes(event.key.toLowerCase())) return;
    if (event.key.toLowerCase() === 'j') {
      event.preventDefault();
      this.inspectorTab === 'subtitles' ? this.nextSubtitle(1) : this.nextSegment(1);
    } else if (event.key.toLowerCase() === 'k') {
      event.preventDefault();
      this.inspectorTab === 'subtitles' ? this.nextSubtitle(-1) : this.nextSegment(-1);
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
    if (this.statusFilter === 'awaiting_publish') return Number(item.summary_counts?.['awaiting_publish'] || 0) > 0;
    if (this.statusFilter === 'needs_repair') return Number(item.summary_counts?.['needs_repair'] || 0) > 0;
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

  private clearDetail(): void {
    ++this.detailRequestId;
    this.detail = null;
    this.selectedSegmentId = '';
    this.draftKey = '';
    this.detailLoading = false;
    this.subtitleRefreshPending = false;
  }

  private loadDetail(taskId: string): void {
    this.saveDraft();
    this.draftKey = '';
    this.detail = null;
    const requestId = ++this.detailRequestId;
    this.detailLoading = true;
    this.api.getSourceRecording(taskId).pipe(takeUntil(this.destroyed)).subscribe({
      next: (detail) => {
        if (requestId !== this.detailRequestId || taskId !== this.selectedTaskId) return;
        this.detail = detail;
        this.detailLoading = false;
        if (detail.trash_job_id && ['pending', 'processing'].includes(detail.trash_status || '')) this.waitForRecordingJob(detail.trash_job_id);
        const stageSegments = filterSegmentsByStage(detail.segments || [], this.activeStage);
        const allowAnySegment = this.activeStage === 'recordings' || this.activeStage === 'burst';
        const pool = allowAnySegment ? (detail.segments || []) : stageSegments;
        const selected = pool.find((segment) => segment.segment_id === this.selectedSegmentId);
        const first = selected || pool[0];
        if (first) this.selectSegment(first);
        else this.selectedSegmentId = '';
        this.subtitleRefreshPending = false;
        this.changeDetector.markForCheck();
      },
      error: (error) => {
        if (requestId !== this.detailRequestId) return;
        this.clearDetail();
        this.subtitleRefreshPending = false;
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
    if (!segmentId) return;
    const target = this.detail?.segments?.find((segment) => segment.segment_id === segmentId)
      || (this.selectedSegment?.segment_id === segmentId ? this.selectedSegment : undefined);
    if (this.busySegments.has(segmentId) || segmentActionBusy(target)) {
      this.message.info('该片段已有任务在排队或处理中');
      this.changeDetector.markForCheck();
      return;
    }
    const taskId = this.selectedTaskId;
    const key = `${taskId}:${segmentId}`;
    const submitted = this.draftValues();
    const anyOtherBusy = Array.from(this.busySegments).some((id) => id !== segmentId)
      || (this.detail?.segments || []).some((segment) => segment.segment_id !== segmentId && segmentActionBusy(segment));
    this.busySegments.add(segmentId);
    this.api.segmentAction(segmentId, action, payload).pipe(
      timeout(SEGMENT_ACTION_TIMEOUT_MS),
      takeUntil(this.destroyed),
    ).subscribe({
      next: (result) => {
        if (key === this.draftKey) {
          const accepted = action === 'finalize' ? [...draftFields]
            : action === 'range' ? ['startDraft', 'endDraft']
            : action === 'subtitle-style' ? draftFields.filter(field => field.startsWith('subtitle') && field !== 'subtitleDrafts')
            : action === 'subtitles' ? ['subtitleDrafts'] : [];
          const baseline = JSON.parse(this.baseline || '{}');
          const updated = (result.segment || result) as Record<string, any>;
          for (const field of accepted) baseline[field] = submitted[field];
          if (action === 'subtitles' && Array.isArray(updated.subtitle_segments)) {
            const serverSubtitles = this.cloneSubtitleSegments(updated.subtitle_segments);
            baseline.subtitleDrafts = serverSubtitles;
            this.subtitleDrafts = serverSubtitles;
          }
          this.baseline = JSON.stringify(baseline);
          if (typeof updated.revision === 'number') this.draftRevision = updated.revision;
          this.saveDraft();
        } else if (action === 'finalize') {
          const draft = this.drafts[key];
          if (draft && JSON.stringify(draft.values) === JSON.stringify(submitted)) delete this.drafts[key];
        }
        this.persistSession();
        const jobId = this.jobIdFromResult(result);
        if (jobId) {
          this.activeJobId = jobId;
          this.jobProgressById[jobId] = {
            phase: 'queued',
            percent: 0,
            message: '已提交，等待 Windows Worker',
          };
          const workerTrigger = result.worker_trigger as Record<string, any> | undefined;
          const workerMessage = String(workerTrigger?.message || '').trim();
          this.workerTriggerUnavailable = ['unavailable', 'failed'].includes(
            String(workerTrigger?.status || ''),
          );
          if (this.workerTriggerUnavailable) {
            this.observationError = workerMessage || 'Windows Worker 当前不可用，任务已保留在队列';
            this.message.warning(`任务 ${jobId.slice(0, 8)} 已入队，但 Worker 尚未接管；任务会保留在队列`);
          } else if (action === 'finalize') {
            this.message.info('已入队生成样片，Worker 处理中（约数分钟）；完成后进入字幕精修');
          } else if (action === 'reburn' || action === 'render') {
            this.message.info(
              anyOtherBusy
                ? '已排队，Windows Worker 按序处理'
                : '已入队重新生成成片，Worker 按序处理',
            );
          } else {
            this.message.info(
              anyOtherBusy
                ? `已排队，Windows Worker 按序处理（任务 ${jobId.slice(0, 8)}）`
                : `已提交 Windows Worker，任务 ${jobId.slice(0, 8)}`,
            );
          }
          this.waitForJob(jobId, segmentId, action);
          return;
        }
        this.finishAction(
          segmentId,
          action,
          action === 'subtitles'
            ? '字幕已保存，片段仍在字幕精修；请点「重新烧录」生成成片'
            : '操作已保存',
        );
      },
      error: (error) => {
        this.busySegments.delete(segmentId);
        if (action === 'subtitles') {
          this.subtitleSaveState = 'failed';
          this.subtitleSaveMessage = this.describeError(error);
        }
        this.message.error(this.describeError(error));
        this.changeDetector.markForCheck();
      },
    });
  }

  private waitForJob(jobId: string, segmentId: string, action = 'job'): void {
    if (this.observedJobs.has(jobId)) return;
    this.observedJobs.add(jobId);
    this.busySegments.add(segmentId);
    this.activeJobId = jobId;
    this.actionBusy = false;
    timer(0, 1500).pipe(
      switchMap(() => this.api.getJob(jobId).pipe(catchError(() => {
        this.observationError = '后台任务仍需跟踪，暂时无法获取状态';
        this.changeDetector.markForCheck();
        return of(null);
      }), tap((job) => {
        if (job) {
          this.recordJobProgress(jobId, job);
          if (this.workerTriggerUnavailable && this.subtitleJobProgress?.phase === 'queued') {
            return;
          }
          this.workerTriggerUnavailable = false;
          this.observationError = '';
        }
      }))),
      filter((job): job is StudioActionJob => !!job && ['done', 'failed', 'blocked'].includes(String(job.status || ''))),
      take(1), takeUntil(this.destroyed)
    ).subscribe(job => {
      this.observedJobs.delete(jobId);
      if (job.status === 'done') {
        this.finishAction(
          segmentId,
          action,
          action === 'reburn'
            ? '字幕重烧完成，已生成待确认成片'
            : '后台处理完成',
        );
      } else {
        const failure = job.failure?.summary || job.error || '后台任务未完成';
        const recovery = job.failure?.recovery_action;
        this.finishAction(
          segmentId,
          action,
          recovery ? `${failure}；${recovery}` : failure,
          true,
        );
      }
    });
  }

  private recordJobProgress(jobId: string, job: StudioActionJob): void {
    this.activeJobId = jobId;
    const progress = job.progress || this.fallbackJobProgress(job.status);
    this.jobProgressById[jobId] = progress;
    this.changeDetector.markForCheck();
  }

  private fallbackJobProgress(status: string | undefined): StudioJobProgress {
    const normalized = String(status || '').toLowerCase();
    if (normalized === 'done') return {phase: 'complete', percent: 100, message: '处理完成'};
    if (['failed', 'blocked'].includes(normalized)) return {phase: 'failed', percent: 0, message: '处理失败'};
    return {phase: 'queued', percent: 0, message: '等待 Windows Worker 状态更新'};
  }

  private finishAction(
    segmentId: string,
    action: string,
    message: string,
    isError = false,
  ): void {
    this.busySegments.delete(segmentId);
    if (action === 'subtitles' && !isError) {
      this.subtitleSaveState = 'saved';
      this.subtitleSaveMessage = message;
      this.subtitleRefreshPending = true;
    }
    if (action === 'reburn' && !isError) this.subtitleRefreshPending = true;
    if (isError) this.message.error(message);
    else if (action === 'subtitles' && !isError) this.message.warning(message);
    else this.message.success(message);
    this.refresh();
    this.changeDetector.markForCheck();
  }

  private waitForRecordingJob(jobId: string): void {
    if (this.observedJobs.has(jobId)) return;
    this.observedJobs.add(jobId);
    this.actionBusy = false;
    timer(0, 1500)
      .pipe(
        switchMap(() => this.api.getJob(jobId).pipe(catchError(() => of<Record<string, unknown>>({status: "unknown"})))),
        filter((job) => ['done', 'failed', 'error', 'blocked'].includes(String(job.status || job.state || ''))),
        take(1),
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
        this.observedJobs.delete(jobId);
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
      next: (result) => {
        this.actionBusy = false;
        const state = result as Record<string, any>;
        if (['unavailable', 'empty', 'dependency_unavailable', 'failed', 'missing_videos_root'].includes(state?.status)) {
          this.message.warning(String(state.message || state.status));
          after?.();
          return;
        }
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
    if (error?.name === 'TimeoutError') {
      return '操作请求超时，结果未确认；请刷新后核对当前版本，再继续操作';
    }
    return String(error?.error?.detail || error?.message || '工作台接口不可用');
  }
}
