# src/autoslice/analysis_result.py
# Copyright (c) 2024 bilive.

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import json
from src.log.logger import scan_log


@dataclass
class Highlight:
    """精彩时刻数据"""
    start: float
    end: float
    score: float
    desc: Optional[str] = None


@dataclass
class TrimSuggestion:
    """裁剪建议"""
    trim_start: float
    trim_end: float
    reason: str


@dataclass
class AnalysisResult:
    """OMNI 分析结果数据类"""
    # 上传必需字段
    title: str
    description: str
    tags: List[str] = field(default_factory=list)
    content_type: str = "other"  # gameplay/chat/singing/dance/other

    # 质量评估
    quality_score: float = 0.5
    retain_recommendation: bool = True
    quality_reason: str = ""

    # MCP 剪辑数据（待办功能使用）
    highlights: List[Highlight] = field(default_factory=list)
    emotion_peak_time: float = 0.0
    suggested_trim: Optional[TrimSuggestion] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnalysisResult":
        """从字典解析"""
        highlights = []
        for h in data.get("highlights", []):
            highlights.append(Highlight(
                start=h.get("start", 0.0),
                end=h.get("end", 0.0),
                score=h.get("score", 0.0),
                desc=h.get("desc")
            ))

        trim_data = data.get("suggested_trim")
        suggested_trim = None
        if trim_data:
            suggested_trim = TrimSuggestion(
                trim_start=trim_data.get("trim_start", 0.0),
                trim_end=trim_data.get("trim_end", 0.0),
                reason=trim_data.get("reason", "")
            )

        return cls(
            title=data.get("title", ""),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            content_type=data.get("content_type", "other"),
            quality_score=data.get("quality_score", 0.5),
            retain_recommendation=data.get("retain_recommendation", True),
            quality_reason=data.get("quality_reason", ""),
            highlights=highlights,
            emotion_peak_time=data.get("emotion_peak_time", 0.0),
            suggested_trim=suggested_trim
        )

    @classmethod
    def from_json(cls, json_str: str) -> Optional["AnalysisResult"]:
        """从 JSON 字符串解析

        Args:
            json_str: JSON 格式的字符串

        Returns:
            AnalysisResult 对象，解析失败时返回 None
        """
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except json.JSONDecodeError as e:
            scan_log.error(f"Failed to parse JSON string: {e}")
            return None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "content_type": self.content_type,
            "quality_score": self.quality_score,
            "retain_recommendation": self.retain_recommendation,
            "quality_reason": self.quality_reason,
            "highlights": [
                {"start": h.start, "end": h.end, "score": h.score, "desc": h.desc}
                for h in self.highlights
            ],
            "emotion_peak_time": self.emotion_peak_time,
            "suggested_trim": {
                "trim_start": self.suggested_trim.trim_start,
                "trim_end": self.suggested_trim.trim_end,
                "reason": self.suggested_trim.reason
            } if self.suggested_trim else None
        }

    def to_json_file(self, output_path: str) -> bool:
        """保存为 JSON 文件

        Args:
            output_path: 输出文件路径

        Returns:
            保存成功返回 True，失败返回 False
        """
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except (IOError, OSError) as e:
            scan_log.error(f"Failed to write JSON file '{output_path}': {e}")
            return False