export type SliceStageId = 'recordings' | 'burst' | 'judge' | 'sample' | 'subtitle';

export const SLICE_STAGES: ReadonlyArray<{
  id: SliceStageId;
  step: string;
  label: string;
  hint: string;
}> = [
  {
    id: 'recordings',
    step: '01',
    label: '录播',
    hint: '全量源场次库存：查看状态、启动切片、进入整场生命周期。',
  },
  {
    id: 'burst',
    step: '02',
    label: '筛选爆点',
    hint: '弹幕密度召回与候选窗：跟踪扫描进度；失败/补标可进入既有工作台。',
  },
  {
    id: 'judge',
    step: '03',
    label: 'AI判断',
    hint: 'MiMo 结论与需人工候选：自动 keep 流向后续阶段，review/失败留在本板。',
  },
  {
    id: 'sample',
    step: '04',
    label: '样片',
    hint: '成片生产与失败恢复：可预览后自动进入字幕精修。',
  },
  {
    id: 'subtitle',
    step: '05',
    label: '字幕精修',
    hint: '末板主工作区：精修字幕后由你决定是否上传。',
  },
];

export interface StageSegmentLike {
  judge_status?: string;
  upload_status?: string;
  final_media_id?: string;
  preview_available?: boolean;
  preview_reason?: string;
  subtitle_needs_burn?: boolean;
  failure?: unknown;
  action_state?: {
    action?: string;
    status?: string;
  } | null;
}

export type SamplePrimaryAction =
  | { kind: 'reburn'; label: string; action: 'reburn' }
  | { kind: 'render'; label: string; action: 'render' }
  | { kind: 'busy'; label: string; action: null }
  | { kind: 'goto_subtitle'; label: string; action: null };

const ACTIVE_ACTION_STATUS_VALUES = new Set(['pending', 'processing', 'running', 'blocked']);

export function segmentActionBusy(segment: StageSegmentLike | null | undefined): boolean {
  if (!segment) return false;
  return ACTIVE_ACTION_STATUS_VALUES.has(String(segment.action_state?.status || ''));
}

export function samplePrimaryAction(segment: StageSegmentLike | null | undefined): SamplePrimaryAction {
  if (!segment) {
    return { kind: 'render', label: '生成成片', action: 'render' };
  }
  const upload = String(segment.upload_status || '');
  const hasFailure = Boolean(segment.failure) || upload === 'failed';
  if (hasFailure) {
    return { kind: 'render', label: '重试成片', action: 'render' };
  }
  if (segmentActionBusy(segment)) {
    return { kind: 'busy', label: '处理中', action: null };
  }
  if (segment.subtitle_needs_burn === true) {
    return { kind: 'reburn', label: '重新烧录成片', action: 'reburn' };
  }
  const hasFinal = Boolean(segment.final_media_id);
  const previewBlocked = segment.preview_available === false;
  if (hasFinal && !previewBlocked) {
    return { kind: 'goto_subtitle', label: '去字幕精修', action: null };
  }
  return { kind: 'render', label: '生成成片', action: 'render' };
}

export interface StageRecordingLike {
  status?: string;
  history_status?: string;
  summary_counts?: Record<string, number>;
}

export interface StageCounts {
  recordings: number;
  burst: number;
  judge: number;
  sample: number;
  subtitle: number;
}

const ACTIVE_ACTION_STATUSES = new Set(['pending', 'processing', 'running', 'blocked']);
const BURST_RECORDING_STATUSES = new Set(['pending', 'processing', 'running', 'failed']);
/** 已进入或完成上传，不再属于样片生产。 */
const SETTLED_UPLOAD_STATUSES = new Set([
  'awaiting_publish',
  'staged',
  'queued',
  'uploading',
  'uploaded',
  'publishing',
  'published',
]);

export function segmentStage(segment: StageSegmentLike | null | undefined): SliceStageId | null {
  if (!segment) return null;
  const judge = String(segment.judge_status || 'review');
  if (judge === 'drop') return null;

  const action = segment.action_state || {};
  const actionStatus = String(action.status || '');
  const actionName = String(action.action || '');
  const upload = String(segment.upload_status || '');
  const hasFinal = Boolean(segment.final_media_id);
  const previewBlocked = segment.preview_available === false;
  const hasFailure = Boolean(segment.failure) || upload === 'failed';
  const isKeep = judge === 'keep' || judge === 'manual_keep';

  if (isKeep) {
    if (hasFailure) return 'sample';
    if (upload === 'published') return null;
    if (['queued', 'uploading', 'uploaded', 'publishing'].includes(upload)) {
      return hasFinal && !previewBlocked ? 'subtitle' : null;
    }
    // 字幕/样式修改后后端作废成片；留在字幕精修板，主操作为重新烧录。
    if (segment.subtitle_needs_burn === true) return 'subtitle';
    if (ACTIVE_ACTION_STATUSES.has(actionStatus) && actionName !== 'approve_publish') {
      return 'sample';
    }
    if (upload === 'awaiting_publish' || upload === 'staged') {
      return hasFinal && !previewBlocked ? 'subtitle' : 'sample';
    }
    if (hasFinal && !previewBlocked) return 'subtitle';
    return 'sample';
  }

  return 'judge';
}

export function recordingInBurst(recording: StageRecordingLike | null | undefined): boolean {
  if (!recording) return false;
  const status = String(recording.status || '');
  const history = String(recording.history_status || '');
  if (BURST_RECORDING_STATUSES.has(status)) return true;
  return history === 'pending' || history === 'processing';
}

/** 样片板应展示的数量：keep 中尚未进入上传/发布闭环，且不在字幕待重烧的部分。 */
export function sampleOutstandingCount(
  counts: Record<string, number> | null | undefined
): number {
  const num = (key: string) => Number((counts || {})[key] || 0);
  const keep = num('keep') + num('manual_keep');
  const settled =
    num('awaiting_publish') +
    num('published') +
    num('upload_in_progress') +
    num('subtitle_needs_burn');
  return Math.max(0, keep - settled);
}

export function stageCountFromRecordings(
  recordings: ReadonlyArray<StageRecordingLike>,
  stage: SliceStageId
): number {
  if (stage === 'recordings') return recordings.length;
  if (stage === 'burst') {
    return recordings.filter((item) => recordingInBurst(item)).length;
  }
  return recordings.reduce((total, item) => total + stageCountFromSummary(item.summary_counts, stage), 0);
}

export function stageCountFromSummary(
  counts: Record<string, number> | null | undefined,
  stage: SliceStageId
): number {
  const source = counts || {};
  const num = (key: string) => Number(source[key] || 0);
  switch (stage) {
    case 'judge':
      return num('review') + num('judge_failed');
    case 'sample':
      return sampleOutstandingCount(source);
    case 'subtitle':
      return num('awaiting_publish') + num('subtitle_needs_burn');
    case 'burst':
    case 'recordings':
    default:
      return 0;
  }
}

export function computeStageCounts(recordings: ReadonlyArray<StageRecordingLike>): StageCounts {
  return {
    recordings: stageCountFromRecordings(recordings, 'recordings'),
    burst: stageCountFromRecordings(recordings, 'burst'),
    judge: stageCountFromRecordings(recordings, 'judge'),
    sample: stageCountFromRecordings(recordings, 'sample'),
    subtitle: stageCountFromRecordings(recordings, 'subtitle'),
  };
}

export function filterSegmentsByStage<T extends StageSegmentLike>(
  segments: ReadonlyArray<T> | null | undefined,
  stage: SliceStageId
): T[] {
  const list = segments || [];
  if (stage === 'recordings' || stage === 'burst') return [...list];
  return list.filter((segment) => segmentStage(segment) === stage);
}

export function isSliceStageId(value: unknown): value is SliceStageId {
  return SLICE_STAGES.some((stage) => stage.id === value);
}

export { SETTLED_UPLOAD_STATUSES };
