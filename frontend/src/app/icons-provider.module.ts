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
  CheckCircleOutline
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
