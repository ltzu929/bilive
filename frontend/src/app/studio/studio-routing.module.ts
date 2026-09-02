import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';

import { StudioSlicesComponent } from './studio-slices.component';
import { StudioUploadsComponent } from './studio-uploads.component';
import { StudioSettingsComponent } from './studio-settings.component';

const routes: Routes = [
  {
    path: 'slices',
    component: StudioSlicesComponent,
  },
  {
    path: 'uploads',
    component: StudioUploadsComponent,
  },
  {
    path: 'settings',
    component: StudioSettingsComponent,
  },
  { path: '', pathMatch: 'full', redirectTo: 'slices' },
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule],
})
export class StudioRoutingModule {}
