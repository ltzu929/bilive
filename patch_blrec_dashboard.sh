#!/bin/bash
# Patch blrec's index.html to add a link to the slice dashboard
INDEX=/home/ubuntu/miniforge/envs/bilive/lib/python3.12/site-packages/blrec/data/webapp/index.html

if ! grep -q "slice-dashboard-link" "$INDEX" 2>/dev/null; then
    sed -i 's|<app-root>|<a href="http://192.168.31.157:2234/tasks" id="slice-dashboard-link" style="position:fixed;top:8px;right:16px;z-index:9999;background:#1890ff;color:#fff;padding:6px 14px;border-radius:4px;text-decoration:none;font-size:13px;font-family:sans-serif">切片面板</a>\n<app-root>|' "$INDEX"
    echo "Patched blrec index.html"
else
    echo "Already patched"
fi
