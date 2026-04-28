import unittest
from src.autoslice.mllm_sdk.sensenova_sdk import sensenova_generate_title
from src.autoslice.mllm_sdk.qwen_sdk import qwen_generate_title
from src.autoslice.analysis_result import AnalysisResult, Highlight, TrimSuggestion

# from src.autoslice.mllm_sdk.gemini_new_sdk import gemini_generate_title
from src.autoslice.mllm_sdk.gemini_old_sdk import gemini_generate_title
from src.autoslice.mllm_sdk.zhipu_sdk import zhipu_glm_4v_plus_generate_title


class BaseTest(unittest.TestCase):
    file_path = "your_video_path"
    artist = "your_artist"


class TestGeminiMain(BaseTest):
    def test_gemini_generate_title(self):
        title = gemini_generate_title(self.file_path, self.artist)
        self.assertIsNotNone(title)


class TestQwenMain(BaseTest):
    def test_qwen_generate_title(self):
        title = qwen_generate_title(self.file_path, self.artist)
        self.assertIsNotNone(title)


class TestSenseNovaMain(BaseTest):
    def test_sensenova_generate_title(self):
        title = sensenova_generate_title(self.file_path, self.artist)
        self.assertIsNotNone(title)


class TestZhipuMain(BaseTest):
    def test_zhipu_generate_title(self):
        title = zhipu_glm_4v_plus_generate_title(self.file_path, self.artist)
        self.assertIsNotNone(title)


class TestAnalysisResult(unittest.TestCase):
    def test_from_dict(self):
        data = {
            "title": "测试标题",
            "description": "测试描述",
            "tags": ["游戏", "直播"],
            "content_type": "gameplay",
            "quality_score": 0.85,
            "retain_recommendation": True,
            "quality_reason": "精彩操作",
            "highlights": [{"start": 5.0, "end": 10.0, "score": 0.9}],
            "emotion_peak_time": 8.0
        }
        result = AnalysisResult.from_dict(data)
        self.assertEqual(result.title, "测试标题")
        self.assertEqual(result.quality_score, 0.85)
        self.assertEqual(len(result.highlights), 1)

    def test_to_dict(self):
        result = AnalysisResult(
            title="标题",
            description="描述",
            tags=["标签"],
            quality_score=0.7
        )
        d = result.to_dict()
        self.assertEqual(d["title"], "标题")
        self.assertEqual(d["quality_score"], 0.7)

    def test_to_json_file(self):
        result = AnalysisResult(title="测试", description="内容")
        output_path = "test_analysis.json"
        result.to_json_file(output_path)
        import os
        self.assertTrue(os.path.exists(output_path))
        os.remove(output_path)


if __name__ == "__main__":
    unittest.main()
