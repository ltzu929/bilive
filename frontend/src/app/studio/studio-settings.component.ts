import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  OnInit,
} from '@angular/core';
import { NzMessageService } from 'ng-zorro-antd/message';
import {
  StudioApiService,
  StudioRoom,
  StudioStreamerProfile,
  StudioStreamerProfileResponse,
  StudioStreamerRecommendation,
} from './studio-api.service';
import { StudioPreferencesService } from './studio-preferences.service';

@Component({
  selector: 'app-studio-settings',
  templateUrl: './studio-settings.component.html',
  styleUrls: ['./studio-settings.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StudioSettingsComponent implements OnInit {
  loading = true;
  dashboardSettings: Record<string, any> = {};
  refreshInterval = 30;
  compactQueue = false;
  collapseSidebar = false;
  rooms: StudioRoom[] = [];
  profileRoomId = '';
  profileLoading = false;
  profileBusy = false;
  profileError = '';
  profile: StudioStreamerProfile = {};
  recommendations: StudioStreamerRecommendation[] = [];
  experiences: Array<Record<string, unknown>> = [];
  displayNameDraft = '';
  aliasesDraft = '';
  defaultTagsDraft = '';
  defaultDescriptionDraft = '';
  approvedGuidanceDraft = '';
  burstRatioDraft = '';
  burstWindowDraft = '';
  burstContextDraft = '';
  burstMergeGapDraft = '';
  burstTopNDraft = '';
  subtitleFontNameDraft = 'Noto Sans SC';
  subtitleFontSizeDraft = '20';
  subtitleMarginVDraft = '60';
  subtitleAlignmentDraft = '2';
  subtitleOutlineDraft = '2';
  subtitleTextColorDraft = '#ffffff';
  subtitleOutlineColorDraft = '#000000';
  private profileRequestId = 0;

  constructor(
    private api: StudioApiService,
    private message: NzMessageService,
    private changeDetector: ChangeDetectorRef,
    private preferences: StudioPreferencesService
  ) {}

  ngOnInit(): void {
    const stored = this.preferences.value;
    this.refreshInterval = stored.refreshInterval;
    this.compactQueue = stored.compactQueue;
    this.collapseSidebar = stored.collapseSidebar;
    this.api.getDashboardSettings().subscribe({
      next: (settings) => {
        this.dashboardSettings = settings || {};
        this.loading = false;
        this.changeDetector.markForCheck();
      },
      error: () => {
        this.loading = false;
        this.changeDetector.markForCheck();
      },
    });
    this.api.getRooms().subscribe({
      next: (rooms) => {
        this.rooms = rooms || [];
        if (!this.profileRoomId) this.profileRoomId = this.rooms[0]?.room_id || '';
        this.loadStreamerProfile();
        this.changeDetector.markForCheck();
      },
      error: (error) => {
        this.profileError = this.describeError(error);
        this.changeDetector.markForCheck();
      },
    });
  }

  save(): void {
    this.preferences.save({
      refreshInterval: this.refreshInterval,
      compactQueue: this.compactQueue,
      collapseSidebar: this.collapseSidebar,
    });
    this.message.success('工作台偏好已保存到当前浏览器');
  }

  loadStreamerProfile(): void {
    const roomId = this.profileRoomId;
    if (!roomId) return;
    const requestId = ++this.profileRequestId;
    this.profileLoading = true;
    this.profileError = '';
    this.api.getStreamerProfile(roomId).subscribe({
      next: (response) => {
        if (requestId !== this.profileRequestId) return;
        this.applyProfileResponse(response);
        this.profileLoading = false;
        this.changeDetector.markForCheck();
      },
      error: (error) => {
        if (requestId !== this.profileRequestId) return;
        this.profileLoading = false;
        this.profileError = this.describeError(error);
        this.changeDetector.markForCheck();
      },
    });
    this.api.getStreamerExperiences(roomId).subscribe({
      next: (experiences) => {
        if (requestId !== this.profileRequestId) return;
        this.experiences = experiences || [];
        this.changeDetector.markForCheck();
      },
      error: () => {
        if (requestId === this.profileRequestId) this.experiences = [];
      },
    });
  }

  saveStreamerProfile(): void {
    if (!this.profileRoomId || this.profileBusy) return;
    const options: Record<string, number> = {};
    for (const [key, value] of [
      ['burst_ratio', this.burstRatioDraft],
      ['burst_window', this.burstWindowDraft],
      ['burst_context', this.burstContextDraft],
      ['burst_merge_gap', this.burstMergeGapDraft],
      ['burst_top_n', this.burstTopNDraft],
    ]) {
      const text = String(value || '').trim();
      if (!text) continue;
      const number = Number(text);
      if (!Number.isFinite(number)) {
        this.message.warning(`${key} 必须是数字`);
        return;
      }
      options[key] = number;
    }
    const style = {
      font_name: this.subtitleFontNameDraft.trim() || 'Noto Sans SC',
      font_size: Number(this.subtitleFontSizeDraft || 20),
      margin_v: Number(this.subtitleMarginVDraft || 60),
      alignment: Number(this.subtitleAlignmentDraft || 2),
      outline: Number(this.subtitleOutlineDraft || 2),
      primary_colour: this.assColour(this.subtitleTextColorDraft),
      outline_colour: this.assColour(this.subtitleOutlineColorDraft),
    };
    if (
      ![style.font_size, style.margin_v, style.alignment, style.outline].every(
        (value) => Number.isFinite(value)
      )
    ) {
      this.message.warning('字幕样式数值无效');
      return;
    }
    this.profileBusy = true;
    this.api.updateStreamerProfile(this.profileRoomId, {
      display_name: this.displayNameDraft.trim(),
      aliases: this.splitList(this.aliasesDraft),
      default_tags: this.splitList(this.defaultTagsDraft),
      default_description: this.defaultDescriptionDraft,
      default_slice_options: options,
      default_subtitle_style: style,
      approved_guidance: this.approvedGuidanceDraft,
    }).subscribe({
      next: (response) => {
        this.applyProfileResponse(response);
        this.profileBusy = false;
        this.message.success('主播档案已保存');
        this.changeDetector.markForCheck();
      },
      error: (error) => {
        this.profileBusy = false;
        this.message.error(this.describeError(error));
        this.changeDetector.markForCheck();
      },
    });
  }

  applyRecommendation(recommendation: StudioStreamerRecommendation): void {
    const recommendationId = String(recommendation.recommendation_id || '');
    if (!this.profileRoomId || !recommendationId || this.profileBusy) return;
    this.profileBusy = true;
    this.api.applyStreamerRecommendation(this.profileRoomId, recommendationId).subscribe({
      next: (response) => {
        this.applyProfileResponse(response);
        const local = this.recommendations.find(
          (item) => item.recommendation_id === recommendationId
        );
        if (local) local.status = 'applied';
        this.profileBusy = false;
        this.message.success('建议已应用到该主播档案');
        this.changeDetector.markForCheck();
      },
      error: (error) => {
        this.profileBusy = false;
        this.message.error(this.describeError(error));
        this.changeDetector.markForCheck();
      },
    });
  }

  recommendationBasis(recommendation: StudioStreamerRecommendation): string {
    return (recommendation.basis || [])
      .map((item) => String(item.reason_type || item.experience_type || '人工样本'))
      .join('、');
  }

  experienceLabel(experience: Record<string, unknown>): string {
    const type = String(experience.experience_type || '');
    const labels: Record<string, string> = {
      positive: '正样本',
      negative: '负样本',
      missed_segment_positive: '漏切正样本',
      recording_no_content: '整场无内容',
      technical_failure: '技术失败',
    };
    return labels[type] || type || '经验';
  }

  private applyProfileResponse(response: StudioStreamerProfileResponse): void {
    if (response.profile) {
      this.profile = response.profile;
      this.displayNameDraft = String(response.profile.display_name || '');
      this.aliasesDraft = (response.profile.aliases || []).join(', ');
      this.defaultTagsDraft = (response.profile.default_tags || []).join(', ');
      this.defaultDescriptionDraft = String(response.profile.default_description || '');
      this.approvedGuidanceDraft = String(response.profile.approved_guidance || '');
      const options = response.profile.default_slice_options || {};
      this.burstRatioDraft = this.draftNumber(options.burst_ratio);
      this.burstWindowDraft = this.draftNumber(options.burst_window);
      this.burstContextDraft = this.draftNumber(options.burst_context);
      this.burstMergeGapDraft = this.draftNumber(options.burst_merge_gap);
      this.burstTopNDraft = this.draftNumber(options.burst_top_n);
      const style = response.profile.default_subtitle_style || {};
      this.subtitleFontNameDraft = String(style.font_name || 'Noto Sans SC');
      this.subtitleFontSizeDraft = this.draftNumber(style.font_size, '20');
      this.subtitleMarginVDraft = this.draftNumber(style.margin_v, '60');
      this.subtitleAlignmentDraft = this.draftNumber(style.alignment, '2');
      this.subtitleOutlineDraft = this.draftNumber(style.outline, '2');
      this.subtitleTextColorDraft = this.cssColour(style.primary_colour, '#ffffff');
      this.subtitleOutlineColorDraft = this.cssColour(style.outline_colour, '#000000');
    }
    if (response.recommendations) this.recommendations = response.recommendations;
  }

  private splitList(value: string): string[] {
    return value
      .split(/[,，]/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  private draftNumber(value: unknown, fallback = ''): string {
    return value == null || value === '' ? fallback : String(value);
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

  private describeError(error: any): string {
    return String(error?.error?.detail || error?.message || '工作台接口不可用');
  }
}
