# 上传管线

## 流程

```
upload.py 每 120s 轮询 SQLite upload_queue
  ↓ 取出未锁定记录
  ↓
1. 登录验证 (GET api.bilibili.com/x/web-interface/nav)
   → 未登录则加载 cookie.json
  ↓
2. 切片上传：generate_slice_data() 从 ffmpeg 元数据读标题
   整场上传：generate_video_data() 按模板生成标题
  ↓
3. preupload → chunk upload → finish (CDN 上传)
  ↓
4. POST member.bilibili.com/x/vu/client/add (发布)
   ⚠️ code=-101 "账号未登录" (已知未解决)
  ↓
5. 失败 → locked=1, 最多重试 3 次
```

## 关键代码

| 步骤 | 文件 |
|------|------|
| 上传消费 | `src/upload/upload.py` |
| B站 SDK | `src/upload/bilitool/` |
| 切片数据 | `src/upload/generate_upload_data.py` → `generate_slice_data()` |
| 队列管理 | `src/db/conn.py` → SQLite `upload_queue` 表 |

## Cookie 认证

### 格式问题

bilitool 期望 JSON 格式 (`{data: {cookie_info: {cookies: [...]}}}`)，而 `.secrets/bilibili.cookie` 是分号分隔文本。运行 `python sync_cookie.py` 自动转换。

### 发布接口 code=-101（未解决）

即使 cookie 在 GET 请求中验证为已登录，POST `/x/vu/client/add` 仍返回 code=-101。已尝试：不同 Referer、csrf 位置、SESSDATA 编解码——均无效。视频文件已成功上传到 CDN，仅最后发布失败。

详见 [`known-issues.md`](known-issues.md)。

### blrec 的 cookie

blrec 从 `settings.toml` 的 `[header] cookie` 直接读取，用于下载原画流。录制不受发布接口问题影响。
