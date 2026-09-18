import {
  computeStageCounts,
  filterSegmentsByStage,
  isSliceStageId,
  recordingInBurst,
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

  it('does not park approve_publish processing on the sample board when final exists', () => {
    expect(
      segmentStage({
        judge_status: 'keep',
        final_media_id: 'media-1',
        action_state: { action: 'approve_publish', status: 'processing' },
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

  it('computes aggregate stage counts for the top rail', () => {
    const counts = computeStageCounts([
      { status: 'processing', summary_counts: { review: 1 } },
      { status: 'done', summary_counts: { keep: 2, awaiting_publish: 1, review: 1, judge_failed: 1 } },
    ]);
    expect(counts.recordings).toBe(2);
    expect(counts.burst).toBe(1);
    expect(counts.judge).toBe(3);
    expect(counts.sample).toBe(1);
    expect(counts.subtitle).toBe(1);
  });

  it('filters detail segments for stage boards and validates stage ids', () => {
    const segments = [
      { segment_id: 'drop', judge_status: 'drop' },
      { segment_id: 'review', judge_status: 'review' },
      { segment_id: 'final', judge_status: 'keep', final_media_id: 'f' },
      { segment_id: 'render', judge_status: 'keep', action_state: { status: 'processing' } },
    ];
    expect(filterSegmentsByStage(segments, 'judge').map((item) => item.segment_id)).toEqual(['review']);
    expect(filterSegmentsByStage(segments, 'sample').map((item) => item.segment_id)).toEqual(['render']);
    expect(filterSegmentsByStage(segments, 'subtitle').map((item) => item.segment_id)).toEqual(['final']);
    expect(isSliceStageId('subtitle')).toBeTrue();
    expect(isSliceStageId('uploads')).toBeFalse();
  });
});
