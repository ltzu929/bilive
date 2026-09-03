import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface StudioRoom {
  room_id: string;
  name?: string;
}

export interface StudioSourceRecording {
  task_id: string;
  room_id: string;
  room_name?: string;
  recorded_at?: string;
  source_name?: string;
  source_rel_path?: string;
  source_media_id?: string;
  status?: string;
  message?: string;
  source_size_mb?: number;
  segment_count?: number;
  summary_counts?: Record<string, number>;
  failure?: Record<string, unknown> | null;
  updated_at?: number;
  review_state?: string;
  retention_deadline?: string;
  retention_warning?: boolean;
  retention_expired?: boolean;
  trash_eligible?: boolean;
  trash_status?: string;
  trash_block_reason?: string;
  trash_job_id?: string;
}

export interface StudioSegment {
  segment_id: string;
  title?: string;
  description?: string;
  tags?: string[];
  judge_status?: string;
  upload_status?: string;
  publish_approval?: string;
  publish_approved_at?: string;
  start_seconds?: number;
  end_seconds?: number;
  candidate_media_id?: string;
  quality_score?: number;
  completeness_score?: number;
  confidence?: number;
  danmaku_count?: number;
  burst_ratio?: number;
  quality?: Record<string, unknown>;
  quality_reason?: string;
  judge_error?: string;
  failure?: {
    summary?: string;
    technical_details?: string;
    recovery_action?: string;
  } | null;
  action_state?: {
    action?: string;
    status?: string;
    job_id?: string;
  };
  subtitle_style?: Record<string, number | string>;
  manual_origin?: string;
  missed_reason?: string;
  review_note?: string;
}

export interface StudioSourceDetail extends StudioSourceRecording {
  density_points?: Array<{
    start_seconds?: number;
    end_seconds?: number;
    count?: number;
    normalized?: number;
  }>;
  segments?: StudioSegment[];
  history_status?: string;
}

export interface UploadDashboard {
  queue_counts?: Record<string, number>;
  items?: Array<{
    id?: number;
    name?: string;
    room?: string;
    status?: string;
    attempts?: number;
    last_error?: string;
    bvid?: string;
    updated_at?: number;
  }>;
  database?: string;
  worker?: Record<string, unknown>;
}

export interface SliceDashboard {
  status_counts?: Record<string, number>;
  total?: number;
  items?: Array<Record<string, unknown>>;
  queue?: { pending_tasks?: number; pending_sources?: string[] };
  directory?: string;
}

export interface StudioStreamerProfile {
  room_id?: string;
  display_name?: string;
  aliases?: string[];
  default_tags?: string[];
  default_description?: string;
  default_slice_options?: Record<string, number>;
  default_subtitle_style?: Record<string, number | string>;
  approved_guidance?: string;
  updated_at?: string;
}

export interface StudioStreamerRecommendation {
  recommendation_id?: string;
  status?: string;
  evidence_status?: string;
  sample_size?: number;
  positive_count?: number;
  negative_count?: number;
  evidence_ids?: string[];
  basis?: Array<Record<string, unknown>>;
  changes?: Record<string, unknown>;
  message?: string;
}

export interface StudioStreamerProfileResponse {
  profile?: StudioStreamerProfile;
  recommendations?: StudioStreamerRecommendation[];
}

@Injectable({ providedIn: 'root' })
export class StudioApiService {
  constructor(private http: HttpClient) {}

  private path(path: string): string {
    return `/studio-api${path}`;
  }

  getRooms(): Observable<StudioRoom[]> {
    return this.http.get<StudioRoom[]>(this.path('/rooms'));
  }

  getSourceRecordings(roomId?: string): Observable<StudioSourceRecording[]> {
    let params = new HttpParams();
    if (roomId) params = params.set('room_id', roomId);
    return this.http.get<StudioSourceRecording[]>(this.path('/source-recordings'), {
      params,
    });
  }

  getSourceRecording(taskId: string): Observable<StudioSourceDetail> {
    return this.http.get<StudioSourceDetail>(
      this.path(`/source-recordings/${encodeURIComponent(taskId)}`)
    );
  }

  getSliceProgress(): Observable<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>(this.path('/slice-progress'));
  }

  getSliceDiagnostics(): Observable<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>(this.path('/slice-diagnostics'));
  }

  getWorkerStatus(): Observable<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>(this.path('/worker-trigger/status'));
  }

  startSlice(taskId?: string): Observable<Record<string, unknown>> {
    return this.http.post<Record<string, unknown>>(this.path('/slice/start'),
      taskId ? { task_id: taskId } : {}
    );
  }

  wakeWorker(): Observable<Record<string, unknown>> {
    return this.http.post<Record<string, unknown>>(this.path('/worker-trigger/wake'), {});
  }

  stopWorker(): Observable<Record<string, unknown>> {
    return this.http.post<Record<string, unknown>>(this.path('/worker-trigger/stop'), {});
  }

  getJob(jobId: string): Observable<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>(
      this.path(`/jobs/${encodeURIComponent(jobId)}`)
    );
  }

  segmentAction(
    segmentId: string,
    action: string,
    payload?: Record<string, unknown>
  ): Observable<Record<string, unknown>> {
    return this.http.post<Record<string, unknown>>(
      this.path(`/segments/${encodeURIComponent(segmentId)}/${action}`),
      payload || {}
    );
  }

  getUploadDashboard(): Observable<UploadDashboard> {
    return this.http.get<UploadDashboard>(this.path('/upload-dashboard'));
  }

  getDashboardSettings(): Observable<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>(this.path('/dashboard-settings'));
  }

  createMissedSegment(
    taskId: string,
    payload: Record<string, unknown>
  ): Observable<Record<string, unknown>> {
    return this.http.post<Record<string, unknown>>(
      this.path(`/source-recordings/${encodeURIComponent(taskId)}/missed-segments`),
      payload
    );
  }

  completeSourceReview(
    taskId: string,
    confirmedNoContent = false
  ): Observable<Record<string, unknown>> {
    return this.http.post<Record<string, unknown>>(
      this.path(`/source-recordings/${encodeURIComponent(taskId)}/review-complete`),
      { confirmed_no_content: confirmedNoContent }
    );
  }

  trashSourceRecording(taskId: string): Observable<Record<string, unknown>> {
    return this.http.post<Record<string, unknown>>(
      this.path(`/source-recordings/${encodeURIComponent(taskId)}/trash`),
      {}
    );
  }

  getStreamerProfile(roomId: string): Observable<StudioStreamerProfileResponse> {
    return this.http.get<StudioStreamerProfileResponse>(
      this.path(`/streamers/${encodeURIComponent(roomId)}/profile`)
    );
  }

  updateStreamerProfile(
    roomId: string,
    payload: Record<string, unknown>
  ): Observable<StudioStreamerProfileResponse> {
    return this.http.patch<StudioStreamerProfileResponse>(
      this.path(`/streamers/${encodeURIComponent(roomId)}/profile`),
      payload
    );
  }

  getStreamerExperiences(roomId: string): Observable<Array<Record<string, unknown>>> {
    return this.http.get<Array<Record<string, unknown>>>(
      this.path(`/streamers/${encodeURIComponent(roomId)}/experiences`)
    );
  }

  applyStreamerRecommendation(
    roomId: string,
    recommendationId: string
  ): Observable<StudioStreamerProfileResponse> {
    return this.http.post<StudioStreamerProfileResponse>(
      this.path(
        `/streamers/${encodeURIComponent(roomId)}/recommendations/${encodeURIComponent(recommendationId)}/apply`
      ),
      {}
    );
  }

  getSliceDashboard(): Observable<SliceDashboard> {
    return this.http.get<SliceDashboard>(this.path('/slice-dashboard'));
  }

  getSlicePerformance(): Observable<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>(this.path('/slice-performance'));
  }

  saveFeedback(sliceId: string, payload: Record<string, unknown>): Observable<Record<string, unknown>> {
    return this.http.patch<Record<string, unknown>>(
      this.path(`/slices/${encodeURIComponent(sliceId)}/feedback`),
      payload
    );
  }

  getMediaUrl(mediaId: string, preview = false): string {
    const resource = preview ? 'preview' : 'media';
    return this.path(`/${resource}/${encodeURIComponent(mediaId)}`);
  }
}
