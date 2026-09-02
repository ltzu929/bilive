import { DataurlPipe } from './dataurl.pipe';
import { DomSanitizer } from '@angular/platform-browser';

describe('DataurlPipe', () => {
  it('create an instance', () => {
    const sanitizer = {
      bypassSecurityTrustUrl: (url: string) => url,
    } as unknown as DomSanitizer;
    const pipe = new DataurlPipe(sanitizer);
    expect(pipe).toBeTruthy();
  });
});
