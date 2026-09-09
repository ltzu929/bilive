import { fakeAsync, tick } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { StudioSlicesComponent } from './studio-slices.component';
import { StudioSegment } from './studio-api.service';

describe('Studio review behavior', () => {
  let component: StudioSlicesComponent;
  let api: any;
  const a: StudioSegment = {segment_id: 'a', title: 'A', start_seconds: 1.9, end_seconds: 4.8,
    revision: 1, final_media_id: 'final-a', upload_status: 'awaiting_publish'};
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
    component = new StudioSlicesComponent(api, {info() {}, success() {}, error() {}, warning() {}} as any,
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

  it('shows the density overlay only on the source timeline', () => {
    component.detail = {
      task_id: 'source',
      room_id: '1',
      source_media_id: 'source-media',
      density_points: [
        {start_seconds: 0, end_seconds: 10, normalized: 0.2},
        {start_seconds: 90, end_seconds: 100, normalized: 1},
      ],
      segments: [a, b],
    };
    component.videoDuration = 120;
    component.mediaMode = 'source';
    expect(component.showDensityOverlay).toBeTrue();
    expect(component.videoDensityPath).toContain('M 0 10');
    expect(component.videoDensityPath).toContain('75.00');
    component.mediaMode = 'final';
    expect(component.showDensityOverlay).toBeFalse();
    expect(component.videoDensityPath).toBe('');
  });

  it('maps metadata duration and positions the source at the selected start', () => {
    component.selectSegment(a);
    const video = {
      currentTime: 0,
      duration: 120,
      muted: false,
      paused: true,
      ended: false,
      pause: jasmine.createSpy('pause'),
    } as unknown as HTMLVideoElement;
    component.sourceVideo = {nativeElement: video} as any;
    component.onVideoMetadata({currentTarget: video} as any);
    expect(component.videoDuration).toBe(120);
    expect(video.currentTime).toBe(1.9);
    expect(video.pause).toHaveBeenCalled();
  });

  it('clamps pointer seeking to the video duration without pausing playback', () => {
    const video = {
      currentTime: 40,
      duration: 120,
      paused: false,
      ended: false,
      pause: jasmine.createSpy('pause'),
    } as unknown as HTMLVideoElement;
    const timeline = {
      getBoundingClientRect: () => ({left: 10, width: 100}),
      setPointerCapture: jasmine.createSpy('setPointerCapture'),
    } as any;
    component.sourceVideo = {nativeElement: video} as any;
    component.videoTimeline = {nativeElement: timeline};
    component.videoDuration = 120;
    component.beginVideoSeek({button: 0, pointerId: 1, clientX: 100, preventDefault() {}} as any);
    expect(video.currentTime).toBe(108);
    expect(video.pause).not.toHaveBeenCalled();
    component.beginVideoSeek({button: 0, pointerId: 2, clientX: 1000, preventDefault() {}} as any);
    expect(video.currentTime).toBe(120);
  });

  it('formats player time with hours when needed', () => {
    expect(component.formatVideoTime(0)).toBe('0:00');
    expect(component.formatVideoTime(65)).toBe('1:05');
    expect(component.formatVideoTime(3661)).toBe('1:01:01');
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
