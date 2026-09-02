import { SubPageContentDirective } from './sub-page-content.directive';
import { TemplateRef } from '@angular/core';

describe('SubPageContentDirective', () => {
  it('should create an instance', () => {
    const directive = new SubPageContentDirective({} as TemplateRef<unknown>);
    expect(directive).toBeTruthy();
  });
});
