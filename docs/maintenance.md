# 维护手册

## 历史媒体只读审计

```powershell
python -m src.maintenance.runtime_cleanup `
  --videos-root .\Videos `
  --report .\logs\maintenance\mp4-audit.json `
  --audit-mp4
```

审计要求 ffprobe 可读取正时长、同时存在音视频流，并通过首中尾解码。

## FLV 恢复

默认只报告：

```powershell
python -m src.maintenance.runtime_cleanup `
  --videos-root .\Videos `
  --report .\logs\maintenance\flv-recovery.json
```

执行转封装：

```powershell
python -m src.maintenance.runtime_cleanup `
  --videos-root .\Videos `
  --report .\logs\maintenance\flv-recovery-executed.json `
  --execute
```

只有确认无效的小文件才允许增加 `--delete-invalid`。任何转封装或验证失败都会
保留源文件和已有 MP4。

## 上传数据库重置

执行前自动生成只读 SQLite 备份：

```powershell
python -m src.maintenance.runtime_cleanup `
  --videos-root .\Videos `
  --db-path .\src\db\data.db `
  --backup-dir .\logs\maintenance\database-backups `
  --report .\logs\maintenance\runtime-reset.json `
  --execute
```
