import { DestroyRef } from '@angular/core';
import { fakeAsync, TestBed, tick } from '@angular/core/testing';

import { InventoryStateService } from './inventory-state.service';

describe('InventoryStateService', () => {
  let service: InventoryStateService;

  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState(window.history.state, '', window.location.pathname);

    TestBed.configureTestingModule({
      providers: [InventoryStateService],
    });

    service = TestBed.inject(InventoryStateService);
    TestBed.runInInjectionContext(() => {
      service.initialize(TestBed.inject(DestroyRef));
    });
  });

  afterEach(() => {
    window.localStorage.clear();
    window.history.replaceState(window.history.state, '', window.location.pathname);
  });

  it('should persist filters to url and storage', fakeAsync(() => {
    service.setFilenameQuery('movie alpha');
    service.setCheckFilter('ko');
    service.setTrackerFilter('example');
    service.setLocationFilter('tv');
    service.setFileFilter('video');
    service.sortBy('filenames_display');
    tick(200);
    TestBed.flushEffects();

    expect(window.location.search).toContain('q=movie+alpha');
    expect(window.location.search).toContain('check=ko');
    expect(window.location.search).toContain('tracker=example');
    expect(window.location.search).toContain('location=tv');
    expect(window.location.search).toContain('type=video');
    expect(window.location.search).toContain('sort=filenames_display');
    expect(window.location.search).toContain('direction=asc');
    expect(JSON.parse(window.localStorage.getItem('arr-inventory.filters') || '{}')).toEqual({
      q: 'movie alpha',
      check: 'ko',
      tracker: 'example',
      location: 'tv',
      type: 'video',
      sort: 'filenames_display',
      direction: 'asc',
    });
  }));
});
