import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  OnDestroy,
  OnInit,
} from '@angular/core';

import { NzNotificationService } from 'ng-zorro-antd/notification';
import { EMPTY, Subscription, interval, of } from 'rxjs';
import { catchError, concatAll, switchMap } from 'rxjs/operators';

import { retry } from 'src/app/shared/rx-operators';
import { StorageService } from '../core/services/storage.service';
import { TaskService } from './shared/services/task.service';
import { DataSelection, TaskData } from './shared/task.model';

const SELECTION_STORAGE_KEY = 'app-tasks-selection';
const REVERSE_STORAGE_KEY = 'app-tasks-reverse';

@Component({
  selector: 'app-tasks',
  templateUrl: './tasks.component.html',
  styleUrls: ['./tasks.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TasksComponent implements OnInit, OnDestroy {
  loading: boolean = true;
  dataList: TaskData[] = [];
  selection: DataSelection;
  reverse: boolean;
  filterTerm = '';

  private dataSubscription?: Subscription;
  private readonly visibilityChangeHandler = (): void => {
    if (document.visibilityState === 'visible') {
      this.syncTaskData();
    } else {
      this.desyncTaskData();
    }
  };

  constructor(
    private changeDetector: ChangeDetectorRef,
    private notification: NzNotificationService,
    private storage: StorageService,
    private taskService: TaskService
  ) {
    this.selection = this.retrieveSelection();
    this.reverse = this.retrieveReverse();

  }

  ngOnInit(): void {
    document.addEventListener('visibilitychange', this.visibilityChangeHandler);
    this.syncTaskData();
  }

  ngOnDestroy(): void {
    document.removeEventListener('visibilitychange', this.visibilityChangeHandler);
    this.desyncTaskData();
  }

  onSelectionChanged(selection: DataSelection): void {
    this.selection = selection;
    this.storeSelection(selection);
    this.desyncTaskData();
    this.syncTaskData();
  }

  onReverseChanged(reverse: boolean): void {
    this.reverse = reverse;
    this.storeReverse(reverse);
    if (reverse) {
      this.dataList = [...this.dataList.reverse()];
      this.changeDetector.markForCheck();
    }
  }

  private retrieveSelection(): DataSelection {
    const selection = this.storage.getData(
      SELECTION_STORAGE_KEY
    ) as DataSelection | null;
    return selection !== null ? selection : DataSelection.ALL;
  }

  private retrieveReverse(): boolean {
    return this.storage.getData(REVERSE_STORAGE_KEY) === 'true';
  }

  private storeSelection(value: DataSelection): void {
    this.storage.setData(SELECTION_STORAGE_KEY, value);
  }

  private storeReverse(value: boolean): void {
    this.storage.setData(REVERSE_STORAGE_KEY, value.toString());
  }

  private syncTaskData(): void {
    this.desyncTaskData();
    this.dataSubscription = of(of(0), interval(1000))
      .pipe(
        concatAll(),
        switchMap(() => this.taskService.getAllTaskData(this.selection)),
        retry(10, 3000),
        catchError((error: HttpErrorResponse) => {
          this.notification.error('获取任务数据出错', error.message, { nzDuration: 0 });
          return EMPTY;
        })
      )
      .subscribe(
        (dataList) => {
          this.loading = false;
          this.dataList = this.reverse ? dataList.reverse() : dataList;
          this.changeDetector.markForCheck();
        },
        () => undefined
      );
  }

  private desyncTaskData(): void {
    this.dataSubscription?.unsubscribe();
  }
}
