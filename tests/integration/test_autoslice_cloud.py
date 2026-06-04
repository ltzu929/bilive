import unittest

import pytest


pytestmark = pytest.mark.integration


class BaseCloudTest(unittest.TestCase):
    file_path = "your_video_path"
    artist = "your_artist"


class TestGeminiMain(BaseCloudTest):
    def test_gemini_generate_title(self):
        # from src.autoslice.mllm_sdk.gemini_new_sdk import gemini_generate_title
        from src.autoslice.mllm_sdk.gemini_old_sdk import gemini_generate_title

        title = gemini_generate_title(self.file_path, self.artist)
        self.assertIsNotNone(title)


class TestQwenMain(BaseCloudTest):
    def test_qwen_generate_title(self):
        from src.autoslice.mllm_sdk.qwen_sdk import qwen_generate_title

        title = qwen_generate_title(self.file_path, self.artist)
        self.assertIsNotNone(title)


class TestSenseNovaMain(BaseCloudTest):
    def test_sensenova_generate_title(self):
        from src.autoslice.mllm_sdk.sensenova_sdk import sensenova_generate_title

        title = sensenova_generate_title(self.file_path, self.artist)
        self.assertIsNotNone(title)


class TestZhipuMain(BaseCloudTest):
    def test_zhipu_generate_title(self):
        from src.autoslice.mllm_sdk.zhipu_sdk import zhipu_glm_4v_plus_generate_title

        title = zhipu_glm_4v_plus_generate_title(self.file_path, self.artist)
        self.assertIsNotNone(title)


class TestQwenOmniMain(BaseCloudTest):
    def test_qwen_omni_analyze(self):
        from src.autoslice.mllm_sdk.qwen_omni_sdk import qwen_omni_analyze

        result = qwen_omni_analyze(self.file_path, self.artist)
        self.assertIsNotNone(result)
        self.assertIsInstance(result.title, str)
        self.assertGreaterEqual(result.quality_score, 0)
        self.assertLessEqual(result.quality_score, 1)
