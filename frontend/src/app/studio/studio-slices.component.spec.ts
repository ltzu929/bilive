import { fakeAsync, tick } from '@angular/core/testing';
import { NEVER, of, throwError } from 'rxjs';
import { StudioSlicesComponent } from './studio-slices.component';
import { StudioSegment } from './studio-api.service';

describe('Studio review behavior', () => {
  let component: StudioSlicesComponent;
  let api: any;
  let message: any;
  const a: StudioSegment = {segment_id: 'a', title: 'A', start_seconds: 1.9, end_seconds: 4.8,
    revision: 1, final_media_id: 'final-a', upload_status: 'awaiting_publish',
    subtitle_segments: [{start: 0, end: 1.2, text: '识别错误'}]};
  const b: StudioSegment = {segment_id: 'b', title: 'B', start_seconds: 8, end_seconds: 12, revision: 1};
  beforeEach(() => {
    sessionStorage.clear();
    api = {
      getMediaUrl: (id: string) => '/studio-api/media/' + id,
      getJob: jasmine.createSpy().and.returnValue(of({status: 'processing'})),
      segmentAction: jasmine.createSpy().and.returnValue(of({status: 'accepted', job_id: 'job-a'})),
      getRooms: () => of([]),
      getSourceRecordings: () => of([]),
      getSourceRecording: jasmine.createSpy().and.returnValue(of({
        task_id: 'source',
        room_id: '1',
        source_media_id: 'source-media',
        segments: [a, b],
      })),
    };
    message = {info() {}, success() {}, error: jasmine.createSpy(), warning() {}};
    component = new StudioSlicesComponent(api, message as any,
      {markForCheck() {}} as any, {value: {}, preferences$: of({refreshInterval: 30})} as any,
      {observe: () => of({matches: false})} as any);
    component.selectedTaskId = 'source';
    component.detail = {task_id: 'source', room_id: '1', source_media_id: 'source-media', segments: [a, b]};
  });
  afterEach(() => component.ngOnDestroy());

  it('sorts dates newest first and unknown dates last', () => {
    component.recordings = [
      {task_id: 'old', room_id: '1', recorded_at: '2026-09-04'},
      {task_id: 'unknown', room_id: '1'},
      {task_id: 'new', room_id: '1', recorded_at: '2026-09-05'},
    ];
    expect(component.filteredRecordings.map(x => x.task_id)).toEqual(['new', 'old', 'unknown']);
    component.queueOrder = 'oldest';
    expect(component.filteredRecordings.map(x => x.task_id)).toEqual(['old', 'new', 'unknown']);
    expect(component.groupedRecordings[0].items.map(x => x.task_id)).toEqual(['old', 'new', 'unknown']);
  });

  it('formats and parses timecodes for boundary editing', () => {
    expect(component.formatTimecode(2484)).toBe('0:41:24');
    expect(component.formatTimecode(0)).toBe('0:00:00');
    expect(component.parseTimecode('0:41:24')).toBe(2484);
    expect(component.parseTimecode('41:24')).toBe(2484);
    expect(component.parseTimecode('2484')).toBe(2484);
  });

  it('treats a chart drag as a missed-segment draft only when long enough', () => {
    component.missedSelectionActive = true;
    component.missedStartDraft = 10;
    component.missedEndDraft = 10.5;
    expect(component.hasMissedSelection).toBeFalse();
    component.missedEndDraft = 25;
    expect(component.hasMissedSelection).toBeTrue();
    component.clearMissedSelection();
    expect(component.hasMissedSelection).toBeFalse();
    expect(component.missedSelectionActive).toBeFalse();
    expect(component.missedStartDraftText).toBe('0:00:00');
  });

  it('keeps chart selection growing leftward without inverting the range', () => {
    component.detail = {
      task_id: 'source',
      room_id: '1',
      source_media_id: 'source-media',
      segments: [],
      density_points: [{start_seconds: 0, end_seconds: 100, normalized: 0.5}],
    } as any;
    component.densityChart = {
      nativeElement: {getBoundingClientRect: () => ({left: 0, width: 100})},
    } as any;
    component.beginChartSelect({clientX: 50, preventDefault() {}} as any);
    expect(component.missedStartDraft).toBeCloseTo(50, 1);
    expect(component.missedSelectionActive).toBeTrue();
    component.onRangeDrag({clientX: 20} as any);
    expect(component.missedStartDraft).toBeCloseTo(20, 1);
    expect(component.missedEndDraft).toBeGreaterThan(component.missedStartDraft);
    component.endRangeDrag();
    expect(component.chartSelecting).toBeFalse();
  });

  it('labels sample cards from real upload status instead of always generating', () => {
    expect(component.sampleThumbLabel({
      segment_id: 'p', judge_status: 'keep', upload_status: 'published',
    } as StudioSegment)).toBe('已发布');
    expect(component.sampleThumbLabel({
      segment_id: 'r', judge_status: 'keep', action_state: {action: 'finalize', status: 'processing'},
    } as StudioSegment)).toBe('成片生成中…');
    expect(component.segmentJobMessage({
      segment_id: 'p', judge_status: 'keep', upload_status: 'published',
    } as StudioSegment)).toBe('已发布，无需再生成成片');
  });

  it('explains queue and MiMo progress lag on the overview card', () => {
    component.progress = {status: 'queued', phase: 'queued'};
    expect(component.progressHint).toContain('Windows Worker');
    component.progress = {status: 'running', phase: 'mimo_wait', message: '等待 MiMo 返回'};
    expect(component.progressHint).toContain('写入工作台');
  });

  it('previews the actual final and requires an explicit source switch', () => {
    component.selectSegment(a);
    expect(component.selectedMediaUrl).toBe('/studio-api/media/final-a');
    component.setMediaMode('source');
    expect(component.selectedMediaUrl).toBe('/studio-api/media/source-media');
  });

  it('preserves A edits across A B A and session restoration', () => {
    component.selectSegment(a);
    component.titleDraft = 'My title';
    component.selectSegment(b);
    component.selectSegment(a);
    expect(component.titleDraft).toBe('My title');
    component.saveDraft();
    expect(JSON.parse(sessionStorage.getItem('bilive.review.session')!).drafts['source:a'].values.titleDraft).toBe('My title');
  });

  it('keeps a stale draft visible and blocks actions until reconciled', () => {
    component.selectSegment(a);
    component.titleDraft = 'My title';
    component.saveDraft();
    component.selectSegment({...a, revision: 2, title: 'Server title'});
    expect(component.titleDraft).toBe('My title');
    expect(component.draftConflict).toBeTrue();
    expect(component.selectedActionBusy).toBeTrue();
  });

  it('does not translate final playback time into source I/O edits', () => {
    component.selectSegment(a);
    component.onShortcut(new KeyboardEvent('keydown', {key: 'i'}));
    expect(component.startDraft).toBe(1.9);
  });

  it('does not approve a final with unsaved edits', () => {
    component.selectSegment(a);
    component.titleDraft = 'Unsaved';
    component.approvePublish();
    expect(api.segmentAction).not.toHaveBeenCalled();
  });

  it('switches stage boards and keeps drop items out of stage segment lists', () => {
    const dropped: StudioSegment = {segment_id: 'd', judge_status: 'drop'};
    const review: StudioSegment = {segment_id: 'r', judge_status: 'review'};
    const finalItem: StudioSegment = {
      segment_id: 'f',
      judge_status: 'keep',
      final_media_id: 'final-f',
      upload_status: 'awaiting_publish',
    };
    spyOn(component as any, 'loadDetail');
    component.detail = {task_id: 'source', room_id: '1', segments: [dropped, review, finalItem]};
    component.recordings = [
      {task_id: 'source', room_id: '1', status: 'done', summary_counts: {review: 1, keep: 1, awaiting_publish: 1}},
      {task_id: 'busy', room_id: '1', status: 'processing'},
    ];

    component.setStage('judge');
    expect(component.activeStage).toBe('judge');
    expect(component.stageSegments.map((item) => item.segment_id)).toEqual(['r']);

    component.setStage('subtitle');
    expect(component.stageSegments.map((item) => item.segment_id)).toEqual(['f']);
    expect(component.stageCounts.subtitle).toBe(1);
    expect(component.stageCounts.burst).toBe(1);
  });

  it('confirms upload through the existing approve-publish action', () => {
    spyOn(component as any, 'loadDetail');
    component.setStage('subtitle');
    component.selectSegment(a);
    component.approvePublish();
    expect(api.segmentAction).toHaveBeenCalledWith('a', 'approve-publish', {
      expected_revision: 1,
      final_media_id: 'final-a',
    });
  });

  it('defers upload without calling the API', () => {
    spyOn(component as any, 'loadDetail');
    component.setStage('subtitle');
    component.selectSegment(a);
    component.deferUpload();
    expect(api.segmentAction).not.toHaveBeenCalled();
  });

  it('saves manually corrected subtitle rows with the current revision', () => {
    api.segmentAction.and.returnValue(of({status: 'saved', segment: {
      ...a,
      revision: 2,
      subtitle_segments: [{start: 0, end: 1.2, text: '正确黑话'}],
    }}));
    component.selectSegment(a);
    component.subtitleDrafts[0].text = '正确黑话';

    component.saveSubtitleEdits();

    expect(api.segmentAction).toHaveBeenCalledWith('a', 'subtitles', {
      expected_revision: 1,
      subtitle_segments: [{start: 0, end: 1.2, text: '正确黑话'}],
    });
  });

  it('explains why a subtitle row beyond the segment disables saving', () => {
    const segment: StudioSegment = {
      ...a,
      subtitle_segments: [{start: 0, end: 3.14, text: '越界字幕'}],
    };
    component.selectSegment(segment);

    expect(component.subtitleDraftsValid).toBeFalse();
    expect(component.subtitleValidationMessage).toBe('第 1 行结束时间超出片段长度 0.24 秒');
    expect(component.subtitleActionHint).toContain('结束时间超出片段长度');
  });

  it('enables reburn after a successful subtitle save and keeps actions separate', () => {
    const savedSegment = {
      ...a,
      revision: 2,
      upload_status: 'not_queued',
      subtitle_segments: [{start: 0, end: 1.2, text: '正确黑话'}],
    };
    api.segmentAction.and.returnValues(
      of({status: 'saved', segment: savedSegment}),
      of({status: 'accepted', job_id: 'job-b'}),
    );
    api.getSourceRecordings = () => of([{task_id: 'source'}]);
    api.getSourceRecording = jasmine.createSpy().and.returnValue(of({
      task_id: 'source',
      segments: [savedSegment],
    }));
    component.selectSegment(a);
    component.subtitleDrafts[0].text = '正确黑话';

    component.saveSubtitleEdits();

    expect(component.subtitleDraftDirty).toBeFalse();
    expect(component.subtitleSaveState).toBe('saved');
    expect(component.subtitleRefreshPending).toBeFalse();
    expect(component.subtitleActionHint).toContain('重新烧录');

    component.reburnSubtitles();

    expect(api.segmentAction.calls.allArgs()).toEqual([
      ['a', 'subtitles', {
        expected_revision: 1,
        subtitle_segments: [{start: 0, end: 1.2, text: '正确黑话'}],
      }],
      ['a', 'reburn', undefined],
    ]);
  });

  it('follows the playing subtitle line and formats readable timecodes', () => {
    component.selectSegment(a);
    component.inspectorTab = 'subtitles';
    component.subtitleDrafts = [
      {start: 0, end: 1.2, text: '第一句'},
      {start: 1.2, end: 2.8, text: '第二句'},
    ];

    component.onVideoTimeUpdate({target: {currentTime: 1.8}} as unknown as Event);

    expect(component.activeSubtitleIndex).toBe(1);
    expect(component.subtitleProgressLabel).toBe('当前第 2 / 2 行');
    expect(component.formatSubtitleTime(1.72)).toBe('00:01.72');
  });

  it('adjusts only the active subtitle timing within the segment', () => {
    component.selectSegment(a);
    component.subtitleDrafts = [
      {start: 0, end: 1.2, text: '第一句'},
      {start: 1.2, end: 2.8, text: '第二句'},
    ];
    component.activeSubtitleIndex = 1;

    component.updateActiveSubtitleTime('start', 1.9);
    expect(component.subtitleDrafts).toEqual([
      {start: 0, end: 1.2, text: '第一句'},
      {start: 1.9, end: 2.8, text: '第二句'},
    ]);

    component.updateActiveSubtitleTime('end', 99);
    expect(component.subtitleDrafts[1].end).toBe(component.selectedSegmentDuration);
  });

  it('selects a subtitle row before opening its actions', () => {
    component.selectSegment(a);
    component.subtitleDrafts = [
      {start: 0, end: 1.2, text: '第一句'},
      {start: 1.2, end: 2.8, text: '第二句'},
    ];

    component.toggleSubtitleActions(1);

    expect(component.activeSubtitleIndex).toBe(1);
    expect(component.subtitleActionsIndex).toBe(1);
  });

  it('tracks beyond 90 seconds, survives GET failure and never repeats POST', fakeAsync(() => {
    component.selectSegment(a);
    component.finalizeSegment();
    tick(91000);
    expect(component.busySegments.has('a')).toBeTrue();
    api.getJob.and.returnValue(throwError(() => new Error('offline')));
    tick(1500);
    expect(component.busySegments.has('a')).toBeTrue();
    api.getJob.and.returnValue(of({status: 'done'}));
    tick(1500);
    expect(component.busySegments.has('a')).toBeFalse();
    expect(api.segmentAction.calls.count()).toBe(1);
  }));

  it('shows intermediate action-job progress before the terminal result', fakeAsync(() => {
    api.getJob.and.returnValues(
      of({status: 'processing', progress: {phase: 'asr', percent: 55, message: '正在进行语音转写'}}),
      of({status: 'done', progress: {phase: 'complete', percent: 100, message: '处理完成'}}),
    );
    spyOn(component, 'refresh');
    component.selectSegment(a);

    component.finalizeSegment();
    tick(0);

    expect(component.subtitleJobProgressMessage).toBe('正在进行语音转写');
    expect(component.subtitleJobProgressPercent).toBe(55);
    expect(component.busySegments.has('a')).toBeTrue();

    tick(1500);

    expect(component.subtitleJobProgress?.phase).toBe('complete');
    expect(component.subtitleJobProgressPercent).toBe(100);
    expect(component.busySegments.has('a')).toBeFalse();
  }));

  it('explains that a queued job is waiting for an unavailable worker', fakeAsync(() => {
    component.worker = {status: 'unavailable'};
    message.warning = jasmine.createSpy('warning');
    api.segmentAction.and.returnValue(of({
      status: 'accepted',
      job_id: 'b'.repeat(32),
      worker_trigger: {status: 'unavailable', message: '2235 unavailable'},
    }));
    api.getJob.and.returnValue(of({
      status: 'pending',
      progress: {phase: 'queued', percent: 0, message: '等待 Windows Worker'},
    }));
    component.selectSegment(a);

    component.reburnSubtitles();
    tick(0);

    expect(component.subtitleActionHint).toContain('Worker 当前不可用');
    expect(component.observationError).toBe('2235 unavailable');
    expect(message.warning).toHaveBeenCalledWith(
      '任务 bbbbbbbb 已入队，但 Worker 尚未接管；任务会保留在队列',
    );

    api.getJob.and.returnValue(of({
      status: 'done',
      progress: {phase: 'complete', percent: 100, message: '处理完成'},
    }));
    tick(1500);
  }));

  it('releases the action state and reports an uncertain timeout', fakeAsync(() => {
    component.selectSegment(a);
    api.segmentAction.and.returnValue(NEVER);

    component.saveSubtitleStyle();
    expect(component.busySegments.has('a')).toBeTrue();

    tick(45000);

    expect(component.busySegments.has('a')).toBeFalse();
    expect(message.error).toHaveBeenCalledWith(
      '操作请求超时，结果未确认；请刷新后核对当前版本，再继续操作',
    );
  }));

  it('captures independent drop targets and reasons', fakeAsync(() => {
    component.selectSegment(a);
    component.qualityReasonDraft = 'Reason A';
    component.scheduleDrop();
    component.selectSegment(b);
    component.qualityReasonDraft = 'Reason B';
    component.scheduleDrop();
    tick(5000);
    expect(api.segmentAction.calls.allArgs()).toEqual([
      ['a', 'drop', {reason: 'Reason A', expected_revision: 1}],
      ['b', 'drop', {reason: 'Reason B', expected_revision: 1}],
    ]);
  }));

  it('clears stale detail when the source list becomes empty', () => {
    component.selectSegment(a);
    component.refresh();
    expect(component.detail).toBeNull();
    expect(component.selectedMediaUrl).toBe('');
  });

  it('silently falls back when a stage deep-link task id is gone', () => {
    component.selectedTaskId = 'missing-task';
    component.selectedSegmentId = 'gone';
    component.activeStage = 'burst';
    const live = {task_id: 'live-1', room_id: '1', status: 'processing'};
    component.recordings = [live];
    api.getSourceRecordings = () => of([live]);
    api.getSourceRecording = jasmine.createSpy().and.returnValue(of({
      task_id: 'live-1',
      room_id: '1',
      segments: [],
    }));

    component.refresh();

    expect(component.selectedTaskId).toBe('live-1');
    expect(component.selectedSegmentId).toBe('');
    expect(component.error).toBe('');
  });

  it('reports only when the current stage has no usable recording', () => {
    component.selectedTaskId = 'missing-task';
    component.recordings = [];
    api.getSourceRecordings = () => of([]);
    component.refresh();
    expect(component.selectedTaskId).toBe('');
    expect(component.error).toContain('暂无可用场次');
  });

  it('allows queueing another segment while one is processing', () => {
    message.info = jasmine.createSpy('info');
    api.segmentAction.and.returnValue(of({status: 'accepted', job_id: 'job-c'}));
    api.getJob.and.returnValue(of({status: 'pending'}));
    const busySegment: StudioSegment = {
      segment_id: 'busy-1',
      judge_status: 'keep',
      action_state: {action: 'render', status: 'processing'},
    };
    const idleSegment: StudioSegment = {
      segment_id: 'idle-1',
      judge_status: 'keep',
      final_media_id: '',
    };
    component.detail = {task_id: 'source', room_id: '1', segments: [busySegment, idleSegment]};

    expect(component.segmentBusy(busySegment)).toBeTrue();
    expect(component.segmentBusy(idleSegment)).toBeFalse();

    (component as any).runSegmentAction('render', undefined, 'idle-1');

    expect(api.segmentAction).toHaveBeenCalledWith('idle-1', 'render', undefined);
    expect(message.info).toHaveBeenCalledWith(jasmine.stringMatching(/排队|已入队/));
  });

  it('does not silently ignore a busy segment action', () => {
    message.info = jasmine.createSpy('info');
    const busySegment: StudioSegment = {
      segment_id: 'busy-1',
      judge_status: 'keep',
      action_state: {action: 'render', status: 'processing'},
    };
    component.detail = {task_id: 'source', room_id: '1', segments: [busySegment]};

    (component as any).runSegmentAction('render', undefined, 'busy-1');

    expect(api.segmentAction).not.toHaveBeenCalled();
    expect(message.info).toHaveBeenCalledWith('该片段已有任务在排队或处理中');
  });

  it('keeps subtitle needs-burn segments on the subtitle board with reburn copy', () => {
    const needsBurn: StudioSegment = {
      segment_id: 'nb',
      judge_status: 'keep',
      subtitle_needs_burn: true,
      preview_available: false,
      preview_reason: '字幕已修改，请重新生成最终成片',
      upload_status: 'not_queued',
    };
    component.detail = {task_id: 'source', room_id: '1', segments: [needsBurn]};
    component.activeStage = 'subtitle';

    expect(component.stageSegments.map((item) => item.segment_id)).toEqual(['nb']);
    expect(component.sampleThumbLabel(needsBurn)).toBe('字幕已保存，待重新烧录');
    expect(component.segmentJobMessage(needsBurn)).toContain('字幕');
    expect(component.samplePrimary(needsBurn)).toEqual({
      kind: 'reburn',
      label: '重新烧录成片',
      action: 'reburn',
    });
    expect(component.segmentJobPercent(needsBurn)).toBe(0);
  });

  it('announces finalize queueing toward the subtitle board', () => {
    message.info = jasmine.createSpy('info');
    api.segmentAction.and.returnValue(of({status: 'accepted', job_id: 'job-finalize'}));
    api.getJob.and.returnValue(of({status: 'pending'}));
    component.selectSegment(a);

    component.finalizeSegment();

    expect(message.info).toHaveBeenCalledWith(
      '已入队生成样片，Worker 处理中（约数分钟）；完成后进入字幕精修',
    );
  });
});
