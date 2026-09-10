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

  it('saves manually corrected subtitle rows with the current revision', () => {
    api.segmentAction.and.returnValue(of({status: 'saved', segment: {...a, revision: 2}}));
    component.selectSegment(a);
    component.subtitleDrafts[0].text = '正确黑话';

    component.saveSubtitleEdits();

    expect(api.segmentAction).toHaveBeenCalledWith('a', 'subtitles', {
      expected_revision: 1,
      subtitle_segments: [{start: 0, end: 1.2, text: '正确黑话'}],
    });
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
});
