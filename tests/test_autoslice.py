import unittest

from src.autoslice.analysis_result import AnalysisResult

from src.autoslice.slice_quality_filter import should_retain_slice


class BaseTest(unittest.TestCase):
    file_path = "your_video_path"
    artist = "your_artist"


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


class TestSliceQualityFilter(unittest.TestCase):
    def test_should_retain_high_quality(self):
        result = AnalysisResult(
            title="测试",
            description="内容",
            quality_score=0.8,
            retain_recommendation=True
        )
        self.assertTrue(should_retain_slice(result, 0.6))

    def test_should_skip_low_quality(self):
        result = AnalysisResult(
            title="测试",
            description="内容",
            quality_score=0.4,
            retain_recommendation=True
        )
        self.assertFalse(should_retain_slice(result, 0.6))

    def test_should_skip_not_recommended(self):
        result = AnalysisResult(
            title="测试",
            description="内容",
            quality_score=0.8,
            retain_recommendation=False,
            quality_reason="内容空洞"
        )
        self.assertFalse(should_retain_slice(result, 0.6))

    def test_should_skip_none_result(self):
        self.assertFalse(should_retain_slice(None, 0.6))


class TestKeywordExtraction(unittest.TestCase):
    def test_extracts_chinese_keywords(self):
        from src.autoslice.mllm_sdk.audio_analyzer import extract_keywords
        result = extract_keywords("今天打了一把排位赛，真的太厉害了！哈哈，好棒！")
        self.assertTrue(any("排位" in w or "厉害" in w for w in result))
        self.assertTrue(len(result) > 0)

    def test_filters_stopwords(self):
        from src.autoslice.mllm_sdk.audio_analyzer import extract_keywords
        result = extract_keywords("的那个就是在嗯")
        self.assertEqual(result, [])

    def test_max_keywords(self):
        from src.autoslice.mllm_sdk.audio_analyzer import extract_keywords
        result = extract_keywords("排位赛厉害好棒太强了牛逼绝了", max_keywords=3)
        self.assertLessEqual(len(result), 3)


class TestQualityScoring(unittest.TestCase):
    def test_excited_content_scores_higher(self):
        from src.autoslice.mllm_sdk.audio_analyzer import analyze_audio_content
        high = analyze_audio_content("哈哈好厉害！太强了这波操作！666！牛逼！绝了！")
        low = analyze_audio_content("嗯好的然后就是然后那个就是嗯对")
        self.assertGreater(high["audio_quality"], low["audio_quality"])

    def test_short_transcript_returns_low_quality(self):
        from src.autoslice.mllm_sdk.audio_analyzer import analyze_audio_content
        result = analyze_audio_content("嗯")
        self.assertLessEqual(result["audio_quality"], 0.3)

    def test_filler_heavy_gets_penalized(self):
        from src.autoslice.mllm_sdk.audio_analyzer import analyze_audio_content
        result = analyze_audio_content("嗯额然后就是那个嗯额然后就是那个")
        self.assertLess(result["audio_quality"], 0.5)

    def test_quality_score_in_range(self):
        from src.autoslice.mllm_sdk.audio_analyzer import analyze_audio_content
        result = analyze_audio_content("今天我们来打排位赛，这把打得还行吧")
        self.assertGreaterEqual(result["audio_quality"], 0.1)
        self.assertLessEqual(result["audio_quality"], 1.0)


if __name__ == "__main__":
    unittest.main()
