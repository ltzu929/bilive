import { NgModule } from '@angular/core';
import { NZ_ICONS, NzIconModule } from 'ng-zorro-antd/icon';

import {
  MenuFoldOutline,
  MenuUnfoldOutline,
  FormOutline,
  DashboardOutline,
  InfoCircleOutline,
  ScissorOutline,
  SettingOutline,
  UnorderedListOutline,
  UploadOutline,
  GithubOutline,
  ReloadOutline,
  PlayCircleOutline,
  CheckCircleOutline,
  PauseCircleOutline,
  AudioMutedOutline,
  SoundOutline,
  FullscreenOutline,
  FullscreenExitOutline
} from '@ant-design/icons-angular/icons';

const icons = [
  MenuFoldOutline,
  MenuUnfoldOutline,
  FormOutline,
  DashboardOutline,
  GithubOutline,
  InfoCircleOutline,
  ScissorOutline,
  SettingOutline,
  UnorderedListOutline,
  UploadOutline,
  ReloadOutline,
  PlayCircleOutline,
  CheckCircleOutline,
  PauseCircleOutline,
  AudioMutedOutline,
  SoundOutline,
  FullscreenOutline,
  FullscreenExitOutline,
];

@NgModule({
  imports: [NzIconModule],
  exports: [NzIconModule],
  providers: [
    { provide: NZ_ICONS, useValue: icons }
  ]
})
export class IconsProviderModule {
}
