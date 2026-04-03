import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';

import { DashboardResponse, GroupDetail } from '../models/dashboard.models';

@Injectable({ providedIn: 'root' })
export class DashboardService {
  private readonly http = inject(HttpClient);

  fetchDashboardSnapshot() {
    return this.http.get<DashboardResponse>('/api/dashboard');
  }

  fetchGroupDetail(groupId: number) {
    return this.http.get<GroupDetail>(`/api/groups/${groupId}`);
  }

  purgeInventory() {
    return this.http.post('/api/inventory/purge', {});
  }

  startScan() {
    return this.http.post('/api/scan/filesystem', {});
  }

  stopScan() {
    return this.http.post('/api/scan/stop', {});
  }
}
