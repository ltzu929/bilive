import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { NzIconModule } from 'ng-zorro-antd/icon';
import { NzSpinModule } from 'ng-zorro-antd/spin';
import { NzPageHeaderModule } from 'ng-zorro-antd/page-header';
import { NzButtonModule } from 'ng-zorro-antd/button';
import { NzCardModule } from 'ng-zorro-antd/card';
import { NzListModule } from 'ng-zorro-antd/list';
import { NzTagModule } from 'ng-zorro-antd/tag';
import { NzSelectModule } from 'ng-zorro-antd/select';
import { NzAlertModule } from 'ng-zorro-antd/alert';
import { NzEmptyModule } from 'ng-zorro-antd/empty';
import { NzDividerModule } from 'ng-zorro-antd/divider';
import { NzFormModule } from 'ng-zorro-antd/form';
import { NzInputModule } from 'ng-zorro-antd/input';
import { NzDescriptionsModule } from 'ng-zorro-antd/descriptions';
import { NzProgressModule } from 'ng-zorro-antd/progress';
import { NzStatisticModule } from 'ng-zorro-antd/statistic';
import { NzTableModule } from 'ng-zorro-antd/table';
import { NzSwitchModule } from 'ng-zorro-antd/switch';
import { NzTabsModule } from 'ng-zorro-antd/tabs';
import { NzPopconfirmModule } from 'ng-zorro-antd/popconfirm';
import { NzBadgeModule } from 'ng-zorro-antd/badge';

import { StudioRoutingModule } from './studio-routing.module';
import { StudioSlicesComponent } from './studio-slices.component';
import { StudioUploadsComponent } from './studio-uploads.component';
import { StudioSettingsComponent } from './studio-settings.component';

@NgModule({
  declarations: [
    StudioSlicesComponent,
    StudioUploadsComponent,
    StudioSettingsComponent,
  ],
  imports: [
    CommonModule,
    FormsModule,
    NzIconModule,
    NzSpinModule,
    NzPageHeaderModule,
    NzButtonModule,
    NzCardModule,
    NzListModule,
    NzTagModule,
    NzSelectModule,
    NzAlertModule,
    NzEmptyModule,
    NzDividerModule,
    NzFormModule,
    NzInputModule,
    NzDescriptionsModule,
    NzProgressModule,
    NzStatisticModule,
    NzTableModule,
    NzSwitchModule,
    NzTabsModule,
    NzPopconfirmModule,
    NzBadgeModule,
    StudioRoutingModule,
  ],
})
export class StudioModule {}
