import {
  computeStageCounts,
  filterSegmentsByStage,
  isSliceStageId,
  recordingInBurst,
  sampleOutstandingCount,
  samplePrimaryAction,
  segmentActionBusy,
  segmentStage,
  stageCountFromSummary,
} from './slice-stage';

describe('slice-stage derivation', () => {
  it('excludes dropped segments from active boards', () => {
    expect(segmentStage({ judge_status: 'drop' })).toBeNull();
  });

  it('routes review and judge_failed to the AI judge board', () => {
    expect(segmentStage({ judge_status: 'review' })).toBe('judge');
    expect(segmentStage({ judge_status: 'judge_failed' })).toBe('judge');
    expect(segmentStage({})).toBe('judge');
  });

  it('keeps production and failed keeps on the sample board', () => {
    expect(
      segmentStage({
        judge_status: 'keep',
        action_state: { action: 'finalize', status: 'processing' },
      })
    ).toBe('sample');
    expect(
      segmentStage({
        judge_status: 'keep',
        failure: { summary: 'ffmpeg failed' },
      })
    ).toBe('sample');
    expect(segmentStage({ judge_status: 'manual_keep' })).toBe('sample');
  });

  it('moves previewable finals to the subtitle board', () => {
    expect(
      segmentStage({
        judge_status: 'keep',
        final_media_id: 'media-1',
        upload_status: 'awaiting_publish',
      })
    ).toBe('subtitle');
    expect(
      segmentStage({
        judge_status: 'keep',
        final_media_id: 'media-1',
        preview_available: false,
      })
    ).toBe('sample');
  });

  it('keeps subtitle-needs-burn keeps on the subtitle board', () => {
    expect(
      segmentStage({
        judge_status: 'keep',
        preview_available: false,
        subtitle_needs_burn: true,
        upload_status: 'not_queued',
      })
    ).toBe('subtitle');
    expect(
      segmentStage({
        judge_status: 'keep',
        subtitle_needs_burn: true,
        failure: { summary: 'burn failed' },
      })
    ).toBe('sample');
    expect(
      segmentStage({
        judge_status: 'keep',
        subtitle_needs_burn: true,
        upload_status: 'published',
      })
    ).toBeNull();
  });

  it('derives a single sample-board primary action per scene', () => {
    expect(
      samplePrimaryAction({
        judge_status: 'keep',
        failure: { summary: 'ffmpeg failed' },
      })
    ).toEqual({ kind: 'render', label: '重试成片', action: 'render' });
    expect(
      samplePrimaryAction({
        judge_status: 'keep',
        action_state: { action: 'finalize', status: 'processing' },
      }).kind
    ).toBe('busy');
    expect(
      samplePrimaryAction({
        judge_status: 'keep',
        subtitle_needs_burn: true,
      })
    ).toEqual({ kind: 'reburn', label: '重新烧录成片', action: 'reburn' });
    expect(
      samplePrimaryAction({
        judge_status: 'keep',
        final_media_id: '',
      }).action
    ).toBe('render');
    expect(
      samplePrimaryAction({
        judge_status: 'keep',
        final_media_id: 'media-1',
        preview_available: true,
      }).kind
    ).toBe('goto_subtitle');
    expect(segmentActionBusy({ action_state: { status: 'pending' } })).toBeTrue();
    expect(segmentActionBusy({ action_state: { status: 'done' } })).toBeFalse();
  });

  it('does not park approve_publish processing on the sample board when final exists', () => {
    expect(
      segmentStage({
        judge_status: 'keep',
        final_media_id: 'media-1',
        action_state: { action: 'approve_publish', status: 'processing' },
      })
    ).toBe('subtitle');
  });

  it('keeps published keeps off the sample board even without a local final', () => {
    expect(
      segmentStage({
        judge_status: 'keep',
        upload_status: 'published',
        action_state: { action: 'approve_publish', status: 'done' },
      })
    ).toBeNull();
    expect(
      segmentStage({
        judge_status: 'keep',
        upload_status: 'uploading',
        final_media_id: '',
      })
    ).toBeNull();
    expect(
      segmentStage({
        judge_status: 'keep',
        upload_status: 'uploading',
        final_media_id: 'media-2',
      })
    ).toBe('subtitle');
  });

  it('treats processing or failed recordings as burst-board inventory', () => {
    expect(recordingInBurst({ status: 'processing' })).toBeTrue();
    expect(recordingInBurst({ status: 'failed' })).toBeTrue();
    expect(recordingInBurst({ history_status: 'processing' })).toBeTrue();
    expect(recordingInBurst({ status: 'done', history_status: 'done' })).toBeFalse();
  });

  it('derives navigation counts from summary_counts without new APIs', () => {
    expect(stageCountFromSummary({ review: 2, judge_failed: 1 }, 'judge')).toBe(3);
    expect(
      stageCountFromSummary({ keep: 3, manual_keep: 1, awaiting_publish: 2 }, 'sample')
    ).toBe(2);
    expect(stageCountFromSummary({ awaiting_publish: 4 }, 'subtitle')).toBe(4);
  });

  it('counts subtitle needs-burn keeps on the subtitle badge, not sample', () => {
    expect(
      stageCountFromSummary({ keep: 2, subtitle_needs_burn: 1, awaiting_publish: 1 }, 'subtitle')
    ).toBe(2);
    expect(
      stageCountFromSummary({ keep: 2, subtitle_needs_burn: 1, awaiting_publish: 1 }, 'sample')
    ).toBe(0);
    expect(sampleOutstandingCount({ keep: 3, subtitle_needs_burn: 2, awaiting_publish: 1 })).toBe(0);
  });

  it('excludes published and in-flight uploads from sample outstanding counts', () => {
    expect(sampleOutstandingCount({ keep: 2, published: 1 })).toBe(1);
    expect(sampleOutstandingCount({ keep: 2, upload_in_progress: 2 })).toBe(0);
    expect(sampleOutstandingCount({ keep: 1, manual_keep: 1, awaiting_publish: 1 })).toBe(1);
    expect(stageCountFromSummary({ keep: 3, published: 1, upload_in_progress: 1 }, 'sample')).toBe(1);
  });

  it('computes aggregate stage counts for the top rail', () => {
    const counts = computeStageCounts([
      { status: 'processing', summary_counts: { review: 1 } },
      { status: 'done', summary_counts: { keep: 2, awaiting_publish: 1, review: 1, judge_failed: 1 } },
      { status: 'done', summary_counts: { keep: 1, published: 1 } },
    ]);
    expect(counts.recordings).toBe(3);
    expect(counts.burst).toBe(1);
    expect(counts.judge).toBe(3);
    expect(counts.sample).toBe(1);
    expect(counts.subtitle).toBe(1);
  });

  it('filters detail segments for stage boards and validates stage ids', () => {
    const segments = [
      { segment_id: 'drop', judge_status: 'drop' },
      { segment_id: 'review', judge_status: 'review' },
      { segment_id: 'final', judge_status: 'keep', final_media_id: 'f', upload_status: 'awaiting_publish' },
      { segment_id: 'render', judge_status: 'keep', action_state: { status: 'processing' } },
      { segment_id: 'published', judge_status: 'keep', upload_status: 'published' },
    ];
    expect(filterSegmentsByStage(segments, 'judge').map((item) => item.segment_id)).toEqual(['review']);
    expect(filterSegmentsByStage(segments, 'sample').map((item) => item.segment_id)).toEqual(['render']);
    expect(filterSegmentsByStage(segments, 'subtitle').map((item) => item.segment_id)).toEqual(['final']);
    expect(isSliceStageId('subtitle')).toBeTrue();
    expect(isSliceStageId('uploads')).toBeFalse();
  });
});
