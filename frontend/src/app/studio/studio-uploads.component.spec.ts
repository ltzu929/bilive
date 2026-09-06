import { StudioUploadsComponent } from './studio-uploads.component';
import { of, Subject } from 'rxjs';

describe('Studio uploads', () => {
  it('requests a bounded status-filtered page without slice stop control', () => {
    const api = {getUploadDashboard: jasmine.createSpy().and.returnValue(of({items: [], filtered_total: 120}))};
    const component = new StudioUploadsComponent(api as any, {} as any, {markForCheck() {}} as any);
    component.statusFilter = 'failed';
    component.changePage(2);
    expect(api.getUploadDashboard).toHaveBeenCalledWith('failed', 2);
    expect((component as any).stopWorker).toBeUndefined();
    component.ngOnDestroy();
  });
  it('does not replace the current page with an older response', () => {
    const oldPage = new Subject<any>(); const newPage = new Subject<any>();
    const api = {getUploadDashboard: jasmine.createSpy().and.returnValues(oldPage, newPage)};
    const component = new StudioUploadsComponent(api as any, {} as any, {markForCheck() {}} as any);
    component.changePage(1); component.changePage(2);
    newPage.next({items:[{name:'page2'}], queue_counts:{}});
    oldPage.next({items:[{name:'page1'}], queue_counts:{}});
    expect(component.dashboard.items?.[0].name).toBe('page2');
    component.ngOnDestroy();
  });

  it('shows unavailable business state without a success toast', () => {
    const api = {getUploadDashboard: () => of({database:'unavailable: missing',items:[],queue_counts:{}}), wakeWorker: () => of({status:'unavailable'})};
    const messages = {success:jasmine.createSpy(),warning:jasmine.createSpy()};
    const component = new StudioUploadsComponent(api as any, messages as any, {markForCheck() {}} as any);
    component.wakeWorker();
    expect(messages.success).not.toHaveBeenCalled();
    expect(messages.warning).toHaveBeenCalled();
    expect(component.error).toContain('数据库');
    component.ngOnDestroy();
  });

});
